from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.data_model import DataModel
from app.schemas.data_model import DataModelCreate
from app.services.db_browser_service import (
    DbBrowserNotFoundError,
    DbBrowserValidationError,
    list_columns,
    serialize_value,
    validate_identifier,
)


ALLOWED_TYPE_B_SCHEMAS = {"mdp_staging", "public", "mdp_data"}
VIEW_PRIMARY_KEY_WARNING = (
    "Primary key source column is from a view. Nullability cannot be reliably "
    "enforced by information_schema."
)
NULLABLE_PRIMARY_KEY_WARNING = (
    "Primary key source column is nullable. Ensure values are unique and not null."
)
PRIMARY_KEY_NULL_VALUES_WARNING = "Primary key source column contains null values."
POSTGRES_TO_PLATFORM_TYPES = {
    "text": "text",
    "character varying": "text",
    "varchar": "text",
    "character": "text",
    "char": "text",
    "integer": "integer",
    "bigint": "integer",
    "smallint": "integer",
    "numeric": "float",
    "double precision": "float",
    "real": "float",
    "decimal": "float",
    "boolean": "boolean",
    "date": "date",
    "timestamp": "datetime",
    "timestamp without time zone": "datetime",
    "timestamp with time zone": "datetime",
    "json": "json",
    "jsonb": "json",
}


class TypeBMappingError(Exception):
    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        super().__init__("Type B mapping validation failed")


def _dialect_name(db: Session) -> str:
    return db.bind.dialect.name


def _qualified_table(schema_name: str, table_name: str, dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return f"{schema_name}.{table_name}"
    return table_name


def _attribute_payload(attribute: Any) -> dict[str, Any]:
    return attribute.model_dump(exclude_none=True) if hasattr(attribute, "model_dump") else dict(attribute)


def _normalize_postgres_type(data_type: str) -> str | None:
    normalized = data_type.lower()
    if normalized.startswith("character varying"):
        normalized = "character varying"
    if normalized.startswith("timestamp with time zone"):
        normalized = "timestamp with time zone"
    if normalized.startswith("timestamp without time zone"):
        normalized = "timestamp without time zone"
    if normalized.startswith("timestamp"):
        normalized = "timestamp"
    if normalized.startswith("numeric") or normalized.startswith("decimal"):
        normalized = normalized.split("(")[0]
    return POSTGRES_TO_PLATFORM_TYPES.get(normalized)


def _source_columns_by_name(
    db: Session,
    source_schema: str,
    source_table: str,
) -> dict[str, dict[str, Any]]:
    try:
        columns = list_columns(db, source_schema, source_table)
    except (DbBrowserValidationError, DbBrowserNotFoundError) as exc:
        raise TypeBMappingError(
            [{"field": "source_table", "message": str(exc)}]
        ) from exc
    return {column["column_name"]: column for column in columns}


def _source_object_type(db: Session, source_schema: str, source_table: str) -> str:
    dialect_name = _dialect_name(db)
    if dialect_name == "postgresql":
        result = db.execute(
            text(
                """
                SELECT table_type
                FROM information_schema.tables
                WHERE table_schema = :schema AND table_name = :table
                """
            ),
            {"schema": source_schema, "table": source_table},
        ).scalar_one_or_none()
        return result or "UNKNOWN"

    result = db.execute(
        text("SELECT type FROM sqlite_master WHERE name = :table"),
        {"table": source_table},
    ).scalar_one_or_none()
    return "VIEW" if result == "view" else "BASE TABLE"


def _primary_key_null_count(
    db: Session,
    source_schema: str,
    source_table: str,
    source_column: str,
) -> int:
    dialect_name = _dialect_name(db)
    table_ref = _qualified_table(source_schema, source_table, dialect_name)
    result = db.execute(
        text(f"SELECT COUNT(*) FROM {table_ref} WHERE {source_column} IS NULL")
    ).scalar_one()
    return int(result)


ALLOWED_JOIN_TYPES = {"left", "inner"}


def _q(identifier: str) -> str:
    """Double-quote an identifier. Callers MUST have ``validate_identifier``-d it first (the pattern
    ``^[a-z][a-z0-9_]*$`` makes an embedded quote impossible), so this is injection-safe."""
    return f'"{identifier}"'


def _quoted_table_ref(schema_name: str, table_name: str, dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return f"{_q(schema_name)}.{_q(table_name)}"
    return _q(table_name)


def _column_not_unique(db: Session, schema: str, table: str, column: str) -> bool:
    """True if non-null values of ``column`` contain duplicates (data-based, portable across
    postgres + sqlite). Used for the fan-out guard (a join's right key) and PK uniqueness. An empty
    table has no duplicates → treated as unique. Conservative: if the probe errors, treat as NOT
    unique so a fan-out is blocked rather than silently allowed."""
    ref = _quoted_table_ref(schema, table, _dialect_name(db))
    sql = (
        f"SELECT 1 FROM {ref} WHERE {_q(column)} IS NOT NULL "
        f"GROUP BY {_q(column)} HAVING COUNT(*) > 1 LIMIT 1"
    )
    try:
        return db.execute(text(sql)).first() is not None
    except Exception:  # pragma: no cover - defensive; missing tables are caught earlier
        return True


def _resolve_join_plan(
    db: Session,
    *,
    relationships: list[dict[str, Any]] | None,
    attr_tables: set[tuple[str, str]],
    base: tuple[str, str],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> dict[str, Any] | None:
    """Validate the relationships/joins and return a join plan, or ``None`` for a single-table model.

    Plan = ``{"alias_by_table": {(schema,table): alias}, "joins": [ordered emit list]}``. Enforces:
    identifier-safety on every schema/table/column; ``right.schema`` ∈ allowed; join columns same
    platform type; ``right.column`` UNIQUE (fan-out guard — N:1/1:1) unless ``allow_fanout``;
    connectivity from the base table (no orphan attribute tables)."""
    rels = relationships or []
    if not rels:
        for s, t in sorted(attr_tables - {base}):
            errors.append({
                "field": "relationships",
                "message": (
                    f"Source table {s}.{t} is not joined to the base table {base[0]}.{base[1]} — "
                    "add a relationship/join or remove its attributes."
                ),
            })
        return None

    parsed: list[dict[str, Any]] = []
    right_tables: set[tuple[str, str]] = set()
    for i, rel in enumerate(rels):
        if not isinstance(rel, dict):
            errors.append({"field": f"relationships[{i}]", "message": "join must be an object"})
            continue
        jtype = rel.get("type") or "left"
        if jtype not in ALLOWED_JOIN_TYPES:
            errors.append({"field": f"relationships[{i}].type", "message": "type must be left|inner"})
        left = rel.get("left") or {}
        right = rel.get("right") or {}
        lt, lc = left.get("table"), left.get("column")
        rs, rt, rc = right.get("schema"), right.get("table"), right.get("column")
        ok = True
        for field, value in (
            ("left.table", lt), ("left.column", lc),
            ("right.schema", rs), ("right.table", rt), ("right.column", rc),
        ):
            if not value:
                errors.append({"field": f"relationships[{i}].{field}", "message": "required"})
                ok = False
                continue
            try:
                validate_identifier(value, field)
            except DbBrowserValidationError as exc:
                errors.append({"field": f"relationships[{i}].{field}", "message": str(exc)})
                ok = False
        if rs and rs not in ALLOWED_TYPE_B_SCHEMAS:
            errors.append({
                "field": f"relationships[{i}].right.schema",
                "message": "right.schema must be one of: mdp_staging, public, mdp_data",
            })
            ok = False
        if not ok:
            continue
        parsed.append({
            "i": i, "type": jtype, "lt": lt, "lc": lc, "rs": rs, "rt": rt, "rc": rc,
            "allow_fanout": bool(rel.get("allow_fanout")),
        })
        right_tables.add((rs, rt))

    if errors:
        return None

    all_known = set(attr_tables) | {base} | right_tables
    for p in parsed:
        candidates = sorted({(s, t) for (s, t) in all_known if t == p["lt"]})
        if not candidates:
            errors.append({
                "field": f"relationships[{p['i']}].left.table",
                "message": f"left.table '{p['lt']}' is not a known source table",
            })
        elif len(candidates) > 1:
            errors.append({
                "field": f"relationships[{p['i']}].left.table",
                "message": f"left.table '{p['lt']}' is ambiguous across schemas — only one base/joined table may be named this",
            })
        else:
            p["left_st"] = candidates[0]
            p["right_st"] = (p["rs"], p["rt"])
    if errors:
        return None

    cols_cache: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}

    def _cols(st: tuple[str, str]) -> dict[str, dict[str, Any]]:
        if st not in cols_cache:
            cols_cache[st] = _source_columns_by_name(db, st[0], st[1])
        return cols_cache[st]

    for p in parsed:
        left_cols, right_cols = _cols(p["left_st"]), _cols(p["right_st"])
        lci, rci = left_cols.get(p["lc"]), right_cols.get(p["rc"])
        if lci is None:
            errors.append({
                "field": f"relationships[{p['i']}].left.column",
                "message": f"column {p['lc']} not found in {p['left_st'][0]}.{p['left_st'][1]}",
            })
        if rci is None:
            errors.append({
                "field": f"relationships[{p['i']}].right.column",
                "message": f"column {p['rc']} not found in {p['right_st'][0]}.{p['right_st'][1]}",
            })
        if lci and rci:
            lt_type = _normalize_postgres_type(lci["data_type"])
            rt_type = _normalize_postgres_type(rci["data_type"])
            if lt_type != rt_type:
                errors.append({
                    "field": f"relationships[{p['i']}]",
                    "message": (
                        f"join column type mismatch: {p['lt']}.{p['lc']} ({lci['data_type']}) "
                        f"vs {p['rt']}.{p['rc']} ({rci['data_type']})"
                    ),
                })
            elif _column_not_unique(db, p["right_st"][0], p["right_st"][1], p["rc"]):
                if p["allow_fanout"]:
                    warnings.append({
                        "field": f"relationships[{p['i']}]",
                        "message": (
                            f"fan-out allowed: {p['rt']}.{p['rc']} is not unique — one base row may "
                            "expand into several rows in the result."
                        ),
                    })
                else:
                    errors.append({
                        "field": f"relationships[{p['i']}].right.column",
                        "message": (
                            f"{p['rt']}.{p['rc']} is not unique → this join would fan out (N:M). "
                            "Join on a unique key, or set allow_fanout=true to permit it."
                        ),
                    })
    if errors:
        return None

    # Connectivity + emit order: greedily add joins whose left side is already in the FROM.
    alias_by_table: dict[tuple[str, str], str] = {base: "t0"}
    added: set[tuple[str, str]] = {base}
    ordered: list[dict[str, Any]] = []
    remaining = list(parsed)
    progressed = True
    while progressed and remaining:
        progressed = False
        still: list[dict[str, Any]] = []
        for p in remaining:
            if p["left_st"] in added:
                progressed = True
                if p["right_st"] not in added:
                    alias_by_table[p["right_st"]] = f"t{len(alias_by_table)}"
                    added.add(p["right_st"])
                    ordered.append(p)
                else:
                    warnings.append({
                        "field": f"relationships[{p['i']}]",
                        "message": f"redundant join: {p['rt']} is already reachable; the extra edge is ignored",
                    })
            else:
                still.append(p)
        remaining = still
    for p in remaining:
        errors.append({
            "field": f"relationships[{p['i']}].left.table",
            "message": f"left.table '{p['lt']}' is not reachable from the base table {base[0]}.{base[1]}",
        })
    for s, t in sorted(attr_tables - added):
        errors.append({
            "field": "relationships",
            "message": f"Source table {s}.{t} is not connected to the base table {base[0]}.{base[1]}",
        })
    if errors:
        return None
    return {"alias_by_table": alias_by_table, "joins": ordered}


def build_type_b_from_clause(
    db: Session, validation: dict[str, Any]
) -> tuple[str, dict[tuple[str, str], str]]:
    """Shared FROM/JOIN builder for preview AND outbound. Returns (from_sql, alias_by_table).
    Single-table → ``"<base> t0"``; multi-table → base + ordered LEFT/INNER JOINs from the plan."""
    dialect = _dialect_name(db)
    base = (validation["source_schema"], validation["source_table"])
    plan = validation.get("join_plan")
    from_sql = f"{_quoted_table_ref(base[0], base[1], dialect)} t0"
    if not plan:
        return from_sql, {base: "t0"}
    alias_by_table = plan["alias_by_table"]
    for p in plan["joins"]:
        left_alias = alias_by_table[p["left_st"]]
        right_alias = alias_by_table[p["right_st"]]
        join_kw = "LEFT JOIN" if p["type"] == "left" else "INNER JOIN"
        from_sql += (
            f" {join_kw} {_quoted_table_ref(p['rs'], p['rt'], dialect)} {right_alias}"
            f" ON {left_alias}.{_q(p['lc'])} = {right_alias}.{_q(p['rc'])}"
        )
    return from_sql, alias_by_table


def type_b_qualified_column(
    alias_by_table: dict[tuple[str, str], str], mapped_column: dict[str, Any]
) -> str:
    """``alias."col"`` for a mapped column, using its own (schema, table) → alias."""
    alias = alias_by_table[(mapped_column["source_schema"], mapped_column["source_table"])]
    return f"{alias}.{_q(mapped_column['source_column'])}"


def validate_type_b_mapping(
    db: Session,
    data_model_in: DataModelCreate,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if data_model_in.type != "B":
        errors.append({"field": "type", "message": "Mapping validation only supports Type B models"})

    primary_attributes = [
        attribute.name for attribute in data_model_in.attributes if attribute.is_primary_key
    ]
    primary_key = data_model_in.primary_key or (primary_attributes[0] if primary_attributes else None)
    if not primary_key:
        errors.append(
            {
                "field": "primary_key",
                "message": "Type B models require primary_key or one primary key attribute",
            }
        )

    attribute_payloads = [_attribute_payload(attribute) for attribute in data_model_in.attributes]
    attr_tables: set[tuple[str, str]] = set()
    for index, attribute in enumerate(attribute_payloads):
        for field in ("name", "source_schema", "source_table", "source_column"):
            value = attribute.get(field)
            if not value:
                errors.append(
                    {
                        "field": f"attributes[{index}].{field}",
                        "message": f"Type B attributes require {field}",
                    }
                )
                continue
            try:
                validate_identifier(value, field)
            except DbBrowserValidationError as exc:
                errors.append({"field": f"attributes[{index}].{field}", "message": str(exc)})

        source_schema = attribute.get("source_schema")
        source_table = attribute.get("source_table")
        if source_schema and source_schema not in ALLOWED_TYPE_B_SCHEMAS:
            errors.append(
                {
                    "field": f"attributes[{index}].source_schema",
                    "message": "source_schema must be one of: mdp_staging, public, mdp_data",
                }
            )
        if source_schema and source_table:
            attr_tables.add((source_schema, source_table))

    if primary_key and primary_key not in {attribute["name"] for attribute in attribute_payloads}:
        errors.append(
            {"field": "primary_key", "message": "primary_key must match one of the attribute names"}
        )

    if errors:
        raise TypeBMappingError(errors)

    # The BASE table is the primary-key attribute's table — the driving table that joins hang off
    # (each join brings in a lookup on its unique key, N:1, so the result stays PK-unique).
    primary_attribute = next((a for a in attribute_payloads if a["name"] == primary_key), None)
    if primary_attribute is None or not primary_attribute.get("source_table"):
        raise TypeBMappingError(
            [{"field": "primary_key", "message": "Primary key attribute must map to a source table/column"}]
        )
    base = (primary_attribute["source_schema"], primary_attribute["source_table"])

    # Multi-table: validate the join graph (connectivity from base, type-match, fan-out guard).
    # Single-table (no relationships, every attribute on the base) → join_plan is None.
    join_plan = _resolve_join_plan(
        db,
        relationships=data_model_in.relationships,
        attr_tables=attr_tables,
        base=base,
        errors=errors,
        warnings=warnings,
    )
    if errors:
        raise TypeBMappingError(errors)

    columns_by_table: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}

    def _table_cols(st: tuple[str, str]) -> dict[str, dict[str, Any]]:
        if st not in columns_by_table:
            columns_by_table[st] = _source_columns_by_name(db, st[0], st[1])
        return columns_by_table[st]

    mapped_columns: list[dict[str, Any]] = []
    mapped_attributes: set[str] = set()
    source_column_by_attribute: dict[str, dict[str, Any]] = {}
    for index, attribute in enumerate(attribute_payloads):
        st = (attribute["source_schema"], attribute["source_table"])
        source_column = attribute["source_column"]
        source_column_info = _table_cols(st).get(source_column)
        if source_column_info is None:
            errors.append(
                {
                    "field": f"attributes[{index}].source_column",
                    "message": f"Source column not found: {st[0]}.{st[1]}.{source_column}",
                }
            )
            continue

        source_platform_type = _normalize_postgres_type(source_column_info["data_type"])
        if source_platform_type is None:
            errors.append(
                {
                    "field": f"attributes[{index}].source_column",
                    "message": f"Unsupported source data type: {source_column_info['data_type']}",
                }
            )
            continue
        if source_platform_type != attribute["data_type"]:
            errors.append(
                {
                    "field": f"attributes[{index}].data_type",
                    "message": (
                        f"Declared data_type {attribute['data_type']} is incompatible with "
                        f"source column type {source_column_info['data_type']}"
                    ),
                }
            )
            continue

        mapped_columns.append(
            {
                "attribute": attribute["name"],
                "source_schema": st[0],
                "source_table": st[1],
                "source_column": source_column,
                "source_data_type": source_column_info["data_type"],
                "model_data_type": attribute["data_type"],
            }
        )
        mapped_attributes.add(attribute["name"])
        source_column_by_attribute[attribute["name"]] = source_column_info

    # Primary key must map to a compatible column ON THE BASE table, and be unique there.
    if primary_key not in mapped_attributes:
        errors.append(
            {"field": "primary_key", "message": "Primary key attribute must map to an existing compatible source_column"}
        )
    elif (primary_attribute["source_schema"], primary_attribute["source_table"]) != base:
        errors.append({"field": "primary_key", "message": "Primary key attribute must belong to the base table"})
    else:
        pk_info = source_column_by_attribute[primary_key]
        source_object_type = _source_object_type(db, base[0], base[1])
        if source_object_type == "VIEW":
            warnings.append({"field": "primary_key", "message": VIEW_PRIMARY_KEY_WARNING})
        elif pk_info.get("is_nullable") == "YES":
            warnings.append({"field": "primary_key", "message": NULLABLE_PRIMARY_KEY_WARNING})
        if _primary_key_null_count(db, base[0], base[1], pk_info["column_name"]):
            warnings.append({"field": "primary_key", "message": PRIMARY_KEY_NULL_VALUES_WARNING})
        if _column_not_unique(db, base[0], base[1], pk_info["column_name"]):
            errors.append(
                {
                    "field": "primary_key",
                    "message": (
                        f"Primary key column {base[0]}.{base[1]}.{pk_info['column_name']} is not unique "
                        "— it must uniquely identify a row."
                    ),
                }
            )

    if errors:
        raise TypeBMappingError(errors)

    return {
        "status": "success",
        "message": "Type B mapping is valid",
        "warnings": warnings,
        "source_schema": base[0],
        "source_table": base[1],
        "join_plan": join_plan,
        "mapped_columns": mapped_columns,
    }


def preview_type_b_mapping(
    db: Session,
    data_model_in: DataModelCreate,
    *,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    validation = validate_type_b_mapping(db, data_model_in)
    return _preview_mapping(
        db,
        model_name=data_model_in.name,
        validation=validation,
        limit=limit,
        offset=offset,
    )


def preview_saved_type_b_model(
    db: Session,
    data_model: DataModel,
    *,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    if data_model.type != "B":
        raise TypeBMappingError(
            [{"field": "type", "message": "Mapped preview is only supported for Type B data models"}]
        )
    payload = {
        "name": data_model.name,
        "display_name": data_model.display_name,
        "type": data_model.type,
        "category": data_model.category,
        "description": data_model.description,
        "business_definition": data_model.business_definition,
        "owner_department": data_model.owner_department,
        "source_system": data_model.source_system,
        "primary_key": data_model.primary_key,
        "attributes": data_model.attributes,
        "relationships": data_model.relationships,
        "refresh_policy": data_model.refresh_policy,
        "sensitivity_level": data_model.sensitivity_level,
        "ai_enabled": data_model.ai_enabled,
        "status": data_model.status,
    }
    data_model_in = DataModelCreate.model_validate(payload)
    return preview_type_b_mapping(db, data_model_in, limit=limit, offset=offset)


def _preview_mapping(
    db: Session,
    *,
    model_name: str,
    validation: dict[str, Any],
    limit: int,
    offset: int,
) -> dict[str, Any]:
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    from_sql, alias_by_table = build_type_b_from_clause(db, validation)
    mapped_columns = validation["mapped_columns"]
    select_columns = ", ".join(
        f"{type_b_qualified_column(alias_by_table, column)} AS {_q(column['attribute'])}"
        for column in mapped_columns
    )
    rows = db.execute(
        text(f"SELECT {select_columns} FROM {from_sql} LIMIT :limit OFFSET :offset"),
        {"limit": limit, "offset": offset},
    ).mappings()
    data = [
        {key: serialize_value(value) for key, value in row.items()}
        for row in rows
    ]
    return {
        "status": "success",
        "model": model_name,
        "source_schema": validation["source_schema"],
        "source_table": validation["source_table"],
        "warnings": validation["warnings"],
        "limit": limit,
        "offset": offset,
        "count": len(data),
        "data": data,
    }
