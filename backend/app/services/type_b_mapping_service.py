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
    "uuid": "text",  # uuid columns (e.g. surrogate `id`) link as text — no more "Unsupported"
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

# Type B "latest version only" dedup config. Persisted ADDITIVELY as one entry inside the SHARED
# ``relationships`` JSON (no new DB column) - the join planner ignores it (it has no left/right).
LATEST_CONFIG_TYPE = "latest_config"
DEFAULT_RECENCY_COLUMN = "updated_at"
# Recency must be orderable "newest-first": a timestamp/date or a number. text/boolean/json/uuid
# are rejected so a silently-meaningless sort can't slip through.
SORTABLE_RECENCY_TYPES = {"integer", "float", "date", "datetime"}


def _is_sortable_recency(data_type: str) -> bool:
    return _normalize_postgres_type(data_type) in SORTABLE_RECENCY_TYPES


def _read_latest_config(relationships: list[dict[str, Any]] | None) -> tuple[bool, str | None]:
    """Pull the persisted ``latest_config`` entry out of the SHARED relationships JSON. Returns
    ``(latest_only, recency_column)`` - the source of truth for saved-model reload / outbound."""
    for rel in (relationships or []):
        if isinstance(rel, dict) and rel.get("type") == LATEST_CONFIG_TYPE:
            return bool(rel.get("latest_only")), rel.get("recency_column")
    return False, None


def _extract_latest_config(
    data_model_in: DataModelCreate, *, allow_relationship_fallback: bool = True
) -> tuple[bool, str | None]:
    """Resolve the dedup config from a payload.

    On create/edit the explicit top-level fields are the SOLE source of truth
    (``allow_relationship_fallback=False``): a stale ``latest_config`` entry left in the inbound
    ``relationships`` JSON must NOT resurrect ``latest_only=True``, or validation would skip the
    PK/fan-out guards for a model that persistence stores WITHOUT dedup (validation/persistence
    divergence). Only the saved-model reconstruction paths (outbound + mapped-preview), which carry
    no top-level field, opt into the relationships fallback so a saved deduped model still dedups."""
    latest_only = bool(getattr(data_model_in, "latest_only", False))
    recency_column = getattr(data_model_in, "recency_column", None)
    if allow_relationship_fallback and (not latest_only or not recency_column):
        rel_latest, rel_recency = _read_latest_config(data_model_in.relationships)
        latest_only = latest_only or rel_latest
        recency_column = recency_column or rel_recency
    return latest_only, recency_column


def _q(identifier: str) -> str:
    """Double-quote an identifier. Callers MUST have ``validate_identifier``-d it first (the pattern
    ``^[a-z][a-z0-9_]*$`` makes an embedded quote impossible), so this is injection-safe."""
    return f'"{identifier}"'


def _quoted_table_ref(schema_name: str, table_name: str, dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return f"{_q(schema_name)}.{_q(table_name)}"
    return _q(table_name)


def _dedup_relation_sql(
    schema_name: str,
    table_name: str,
    *,
    dedup_key: str,
    recency: str,
    tiebreak: str | None,
    dialect_name: str,
) -> str:
    """A "latest row per key" subquery that replaces a raw table reference when ``latest_only`` is
    on. Every identifier here was ``validate_identifier``-d upstream (PK/join columns, recency,
    schema/table), so ``_q`` quoting is injection-safe. Postgres -> DISTINCT ON; other dialects
    (the sqlite test bind) -> an equivalent ROW_NUMBER window so the dedup is portable."""
    ref = _quoted_table_ref(schema_name, table_name, dialect_name)
    dk, rec = _q(dedup_key), _q(recency)
    tb = f", {_q(tiebreak)} DESC" if tiebreak else ""
    if dialect_name == "postgresql":
        return f"(SELECT DISTINCT ON ({dk}) * FROM {ref} ORDER BY {dk}, {rec} DESC NULLS LAST{tb})"
    # sqlite: NULLs already sort last under DESC; ROW_NUMBER needs sqlite >= 3.25.
    rn = _q("_mdp_rn")
    return (
        f"(SELECT * FROM (SELECT *, ROW_NUMBER() OVER "
        f"(PARTITION BY {dk} ORDER BY {rec} DESC{tb}) AS {rn} FROM {ref}) WHERE {rn} = 1)"
    )


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
    latest_only: bool = False,
) -> dict[str, Any] | None:
    """Validate the relationships/joins and return a join plan, or ``None`` for a single-table model.

    Plan = ``{"alias_by_table": {(schema,table): alias}, "joins": [ordered emit list]}``. Enforces:
    identifier-safety on every schema/table/column; ``right.schema`` ∈ allowed; join columns same
    platform type; ``right.column`` UNIQUE (fan-out guard — N:1/1:1) unless ``allow_fanout``;
    connectivity from the base table (no orphan attribute tables)."""
    # The relationships column is SHARED: only JOIN-shaped entries (with left/right) are joins here.
    # Other entries — e.g. {"type": "template_metadata", "config": ...} written by the template
    # service — are ignored by the join planner (they carry documentation/config, not a SQL join).
    rels = [
        rel for rel in (relationships or [])
        if isinstance(rel, dict) and (rel.get("left") is not None or rel.get("right") is not None)
    ]
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
            # latest_only wraps the right table in DISTINCT ON (rc) -> rc IS unique in the deduped
            # subquery, so the fan-out guard no longer applies. Type-match above still enforced.
            elif latest_only:
                pass
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
    emitted_by_right: dict[tuple[str, str], dict[str, Any]] = {}
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
                    emitted_by_right[p["right_st"]] = p
                    # INNER joins can DROP base rows that have no match (a by-key lookup of such a row
                    # then 404s) — make that explicit rather than silent.
                    if p["type"] == "inner":
                        warnings.append({
                            "field": f"relationships[{p['i']}]",
                            "message": (
                                f"INNER JOIN to {p['rt']} drops rows with no match (a primary-key lookup "
                                "of a dropped row returns 404). Use a LEFT join to keep them."
                            ),
                        })
                else:
                    # A second edge reaching an already-joined table (diamond / a join INTO the base).
                    # If it differs from the emitted edge (type or ON columns), silently dropping it
                    # would change which rows the query returns → HARD ERROR (don't guess intent).
                    kept = emitted_by_right.get(p["right_st"])
                    same = kept is not None and (p["type"], p["left_st"], p["lc"], p["rc"]) == (
                        kept["type"], kept["left_st"], kept["lc"], kept["rc"]
                    )
                    if same:
                        warnings.append({
                            "field": f"relationships[{p['i']}]",
                            "message": f"duplicate identical join to {p['rt']} ignored",
                        })
                    else:
                        errors.append({
                            "field": f"relationships[{p['i']}]",
                            "message": (
                                f"conflicting join: {p['rt']} is already joined a different way (type or "
                                "ON columns differ, or this joins into the base) — remove the duplicate "
                                "edge or make the two joins identical."
                            ),
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
    latest_only = bool(validation.get("latest_only"))
    dedup_meta = validation.get("dedup_meta_by_table") or {}

    def _relation(schema_name: str, table_name: str) -> str:
        # When latest_only is on, each source relation becomes a "newest row per key" subquery so
        # joins/SELECT run over already-deduped rows (PK unique + every join collapses to 1:1).
        meta = dedup_meta.get((schema_name, table_name)) if latest_only else None
        if meta:
            return _dedup_relation_sql(
                schema_name,
                table_name,
                dedup_key=meta["dedup_key"],
                recency=meta["recency"],
                tiebreak=meta.get("tiebreak"),
                dialect_name=dialect,
            )
        return _quoted_table_ref(schema_name, table_name, dialect)

    from_sql = f"{_relation(base[0], base[1])} t0"
    if not plan:
        return from_sql, {base: "t0"}
    alias_by_table = plan["alias_by_table"]
    for p in plan["joins"]:
        left_alias = alias_by_table[p["left_st"]]
        right_alias = alias_by_table[p["right_st"]]
        join_kw = "LEFT JOIN" if p["type"] == "left" else "INNER JOIN"
        from_sql += (
            f" {join_kw} {_relation(p['rs'], p['rt'])} {right_alias}"
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
    *,
    latest_from_relationships: bool = False,
) -> dict[str, Any]:
    # ``latest_from_relationships`` is True ONLY for saved-model reconstruction (outbound / saved
    # mapped-preview), where the dedup flag lives in the persisted relationships JSON rather than a
    # top-level field. On create/edit it stays False so the explicit top-level field is authoritative.
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

    # "Latest version only" dedup config (Type B). When on, the builder wraps each source relation
    # in a newest-row-per-key subquery, so the PK/right-key uniqueness guards below are relaxed
    # (the dedup makes them structurally unique) - but recency must still exist + be sortable.
    latest_only, recency_column = _extract_latest_config(
        data_model_in, allow_relationship_fallback=latest_from_relationships
    )

    # Multi-table: validate the join graph (connectivity from base, type-match, fan-out guard).
    # Single-table (no relationships, every attribute on the base) → join_plan is None.
    join_plan = _resolve_join_plan(
        db,
        relationships=data_model_in.relationships,
        attr_tables=attr_tables,
        base=base,
        errors=errors,
        warnings=warnings,
        latest_only=latest_only,
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
        # latest_only dedups the base by its PK source column (DISTINCT ON), so a base with several
        # rows per key becomes one-row-per-key -> the uniqueness error no longer applies. Without
        # dedup this stays a hard error.
        if not latest_only and _column_not_unique(db, base[0], base[1], pk_info["column_name"]):
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

    # Resolve the per-table dedup metadata (base PK + each join's right key) and validate the
    # recency column exists + is sortable in every deduped table. This is the only place that can
    # raise the ``recency_column`` field error - no silent fallback.
    dedup_meta_by_table: dict[tuple[str, str], dict[str, Any]] = {}
    if latest_only:
        recency_column = recency_column or DEFAULT_RECENCY_COLUMN
        # recency_column ends up quoted into the dedup ORDER BY - identifier-validate it explicitly
        # (defence in depth on top of the per-table existence check) so an unsafe string can never
        # reach generated SQL, exactly like the join columns above.
        try:
            validate_identifier(recency_column, "recency_column")
        except DbBrowserValidationError as exc:
            raise TypeBMappingError([{"field": "recency_column", "message": str(exc)}]) from exc
        base_pk_column = source_column_by_attribute[primary_key]["column_name"]
        dedup_targets: dict[tuple[str, str], str] = {base: base_pk_column}
        if join_plan:
            for p in join_plan["joins"]:
                dedup_targets[p["right_st"]] = p["rc"]
        for st, dedup_key in dedup_targets.items():
            cols = _table_cols(st)
            rec_info = cols.get(recency_column)
            if rec_info is None:
                errors.append({
                    "field": "recency_column",
                    "message": (
                        f"Recency column '{recency_column}' not found in {st[0]}.{st[1]} - pick a "
                        "timestamp/number column that exists in every deduplicated table."
                    ),
                })
                continue
            if not _is_sortable_recency(rec_info["data_type"]):
                errors.append({
                    "field": "recency_column",
                    "message": (
                        f"Recency column '{recency_column}' in {st[0]}.{st[1]} is not sortable "
                        f"(need timestamp/date/number), got {rec_info['data_type']}."
                    ),
                })
                continue
            # A stable surrogate id makes DISTINCT ON deterministic when recency ties; skip if none.
            tiebreak = "id" if ("id" in cols and "id" not in {dedup_key, recency_column}) else None
            dedup_meta_by_table[st] = {
                "dedup_key": dedup_key,
                "recency": recency_column,
                "tiebreak": tiebreak,
            }
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
        "latest_only": latest_only,
        "recency_column": recency_column if latest_only else None,
        "dedup_meta_by_table": dedup_meta_by_table,
    }


def preview_type_b_mapping(
    db: Session,
    data_model_in: DataModelCreate,
    *,
    limit: int = 20,
    offset: int = 0,
    latest_from_relationships: bool = False,
) -> dict[str, Any]:
    validation = validate_type_b_mapping(
        db, data_model_in, latest_from_relationships=latest_from_relationships
    )
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
    # Saved model: the dedup flag lives in the persisted relationships JSON, not a top-level field.
    return preview_type_b_mapping(
        db, data_model_in, limit=limit, offset=offset, latest_from_relationships=True
    )


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
