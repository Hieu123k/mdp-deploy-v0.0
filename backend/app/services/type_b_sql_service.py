"""Type B SQL surface (prompt 52) - a READ-ONLY two-way bridge between a simple SELECT and the
visual builder plan.

SAFETY: user SQL is NEVER executed. It is parsed to an AST with sqlglot, checked against a tiny
subset (single SELECT; plain ``table.col`` projection; single-column equi-JOINs; schema whitelist),
and mapped to the SAME structured plan the builder uses. Everything outside the subset - any DDL/DML,
statement stacking, functions, subqueries, set operations, ``*``, expressions - is rejected with a
clear error and never touches the DB or the query builder. ``generate_type_b_sql`` is the inverse:
plan -> canonical SQL text (no DB access).
"""
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from app.schemas.data_model import DataModelCreate
from app.services.db_browser_service import IDENTIFIER_PATTERN
from app.services.type_b_mapping_service import (
    ALLOWED_TYPE_B_SCHEMAS,
    LATEST_CONFIG_TYPE,
    TypeBMappingError,
    _normalize_postgres_type,
    _source_columns_by_name,
    validate_type_b_mapping,
)


class TypeBSqlError(Exception):
    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        super().__init__("Type B SQL is outside the supported subset")


def _fail(field: str, message: str) -> None:
    raise TypeBSqlError([{"field": field, "message": message}])


def _ident(value: Any, field: str) -> str:
    text = "" if value is None else str(value)
    if not IDENTIFIER_PATTERN.fullmatch(text):
        _fail(field, f"{field} '{text}' must be a lowercase snake_case identifier")
    return text


def _wl_schema(value: Any, field: str) -> str:
    """Identifier-validate AND whitelist a schema. Used by BOTH parse and generate so the two
    surfaces are symmetric (generate never renders a non-whitelisted schema like pg_catalog)."""
    schema = _ident(value, field)
    if schema not in ALLOWED_TYPE_B_SCHEMAS:
        _fail(field, f"schema '{schema}' is not allowed (use mdp_staging, public, or mdp_data)")
    return schema


# Clauses that move a query outside the read-only mapping subset. WHERE/filters belong to outbound,
# not to the mapping definition, so they are rejected here too.
_DISALLOWED_SELECT_ARGS = (
    "where", "group", "having", "order", "limit", "offset", "distinct", "with",
    "qualify", "windows", "pivots", "sample", "cluster", "sort", "distribute",
    "into", "locks", "hint", "kind", "operation_modifiers",
)
# Defence in depth: a valid subset query contains none of these node types anywhere.
_DANGEROUS_NODES: tuple[tuple[type, str], ...] = (
    (exp.Subquery, "a subquery"),
    (exp.Union, "a set operation (UNION/INTERSECT/EXCEPT)"),
    (exp.Func, "a function call"),
    (exp.Star, "'*'"),
    (exp.Window, "a window function"),
    (exp.Lateral, "a lateral join"),
    (exp.Case, "a CASE expression"),
)


def _table_parts(table: exp.Table, field: str) -> tuple[str, str, str]:
    """(schema, table, alias_or_table) with whitelist + identifier checks. Rejects 3-part names."""
    if table.text("catalog"):
        _fail(field, "three-part names (catalog.schema.table) are not allowed")
    schema = table.text("db")
    name = table.name
    if not schema:
        _fail(field, f"table '{name}' must be schema-qualified (e.g. mdp_data.{name})")
    schema = _ident(schema, "schema")
    name = _ident(name, "table")
    if schema not in ALLOWED_TYPE_B_SCHEMAS:
        _fail(field, f"schema '{schema}' is not allowed (use mdp_staging, public, or mdp_data)")
    alias = _ident(table.alias, "alias") if table.alias else name
    return schema, name, alias


def parse_type_b_sql(
    db: Any,
    sql: str,
    *,
    primary_key: str | None = None,
    latest_only: bool = False,
    recency_column: str | None = None,
) -> dict[str, Any]:
    """Parse a subset SELECT into the builder plan. NEVER executes the user's SQL. Raises
    ``TypeBSqlError`` for anything outside the subset. Reads the catalog (information_schema) for data
    types; in addition, when a matching ``primary_key`` is supplied it runs the SAME read-only Type B
    validator as the builder, which issues lightweight LIMIT-1 / COUNT probes against the named source
    tables to surface non-blocking warnings (still read-only - no user SQL is ever executed)."""
    sql = (sql or "").strip()
    if not sql:
        _fail("sql", "SQL is empty.")

    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except (ParseError, TokenError) as exc:
        _fail("sql", f"SQL could not be parsed: {exc}")
    if len(statements) != 1:
        _fail("sql", "Only a single SELECT statement is allowed (no statement stacking or extra ';').")
    select = statements[0]
    if not isinstance(select, exp.Select):
        _fail(
            "sql",
            "Only a single read-only SELECT is allowed. DDL/DML (DROP/ALTER/CREATE/TRUNCATE/INSERT/"
            "UPDATE/DELETE/MERGE/GRANT/RENAME) and set operations are rejected.",
        )
    for arg in _DISALLOWED_SELECT_ARGS:
        if select.args.get(arg):
            _fail("sql", f"Unsupported SQL: '{arg.upper()}' is outside the Type B subset.")
    for node_type, label in _DANGEROUS_NODES:
        if select.find(node_type):
            _fail("sql", f"Unsupported SQL: {label} is outside the Type B subset.")

    from_node = select.args.get("from")
    if from_node is None or not isinstance(from_node.this, exp.Table):
        _fail("sql", "FROM must be a single base table (schema.table).")
    base_schema, base_table, base_alias = _table_parts(from_node.this, "from")
    alias_map: dict[str, tuple[str, str]] = {base_alias: (base_schema, base_table)}

    relationships: list[dict[str, Any]] = []
    for join in select.args.get("joins") or []:
        side = str(join.args.get("side") or "").upper()
        kind = str(join.args.get("kind") or "").upper()
        if join.args.get("using"):
            _fail("sql", "JOIN ... USING is outside the subset; use ON a.col = b.col.")
        if join.args.get("method"):
            _fail("sql", "NATURAL/method joins are outside the subset.")
        if side in ("RIGHT", "FULL") or kind == "CROSS":
            _fail("sql", "Only LEFT JOIN and INNER JOIN are supported.")
        join_type = "left" if side == "LEFT" else "inner"
        if not isinstance(join.this, exp.Table):
            _fail("sql", "JOIN target must be a table (schema.table); subqueries are not allowed.")
        rs, rt, ralias = _table_parts(join.this, "join")
        if ralias in alias_map or rt in {t for (_, t) in alias_map.values()}:
            _fail("sql", f"duplicate table/alias '{ralias}' in the query.")

        on = join.args.get("on")
        if on is None:
            _fail("sql", "every JOIN needs an ON a.col = b.col condition (CROSS/comma joins are rejected).")
        while isinstance(on, exp.Paren):
            on = on.this
        if not isinstance(on, exp.EQ):
            _fail("sql", "JOIN ON must be a single equality a.col = b.col (AND/OR/functions are rejected).")
        left_col, right_col = on.this, on.expression
        if not (isinstance(left_col, exp.Column) and isinstance(right_col, exp.Column)):
            _fail("sql", "JOIN ON must compare two columns (a.col = b.col).")

        alias_map[ralias] = (rs, rt)
        resolved = []
        for col in (left_col, right_col):
            qualifier = col.table
            if not qualifier:
                _fail("sql", "columns in JOIN ON must be qualified (alias.col).")
            if qualifier not in alias_map:
                _fail("sql", f"unknown table/alias '{qualifier}' in JOIN ON.")
            resolved.append((alias_map[qualifier], _ident(col.name, "column")))
        right_match = [r for r in resolved if r[0] == (rs, rt)]
        left_match = [r for r in resolved if r[0] != (rs, rt)]
        if len(right_match) != 1 or len(left_match) != 1:
            _fail("sql", "JOIN ON must link the joined table to a previously joined table (no self-joins).")
        relationships.append({
            "type": join_type,
            "left": {"table": left_match[0][0][1], "column": left_match[0][1]},
            "right": {"schema": rs, "table": rt, "column": right_match[0][1]},
        })

    attributes: list[dict[str, Any]] = []
    for projection in select.expressions:
        alias_name = None
        column = projection
        if isinstance(projection, exp.Alias):
            alias_name = projection.alias
            column = projection.this
        if not isinstance(column, exp.Column):
            _fail("sql", "each selected item must be a plain column 'table.col' (no '*', functions, or expressions).")
        qualifier = column.table
        if not qualifier:
            _fail("sql", "each selected column must be qualified (table.col).")
        if qualifier not in alias_map:
            _fail("sql", f"unknown table/alias '{qualifier}' in the column list.")
        schema, real_table = alias_map[qualifier]
        column_name = _ident(column.name, "column")
        attr_name = _ident(alias_name, "attribute name") if alias_name else column_name
        attributes.append({
            "name": attr_name,
            "source_schema": schema,
            "source_table": real_table,
            "source_column": column_name,
            "data_type": None,
        })
    if not attributes:
        _fail("sql", "the SELECT must project at least one column.")

    # Fill data_type from the catalog (information_schema read only). Reject unknown/unsupported cols.
    columns_cache: dict[tuple[str, str], dict[str, Any]] = {}
    for attribute in attributes:
        st = (attribute["source_schema"], attribute["source_table"])
        if st not in columns_cache:
            try:
                columns_cache[st] = _source_columns_by_name(db, st[0], st[1])
            except TypeBMappingError as exc:
                raise TypeBSqlError(exc.errors) from exc
        info = columns_cache[st].get(attribute["source_column"])
        if info is None:
            _fail("sql", f"column {st[0]}.{st[1]}.{attribute['source_column']} does not exist.")
        data_type = _normalize_postgres_type(info["data_type"])
        if data_type is None:
            _fail("sql", f"column {st[0]}.{st[1]}.{attribute['source_column']} has unsupported type {info['data_type']}.")
        attribute["data_type"] = data_type

    selected_tables: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for schema, table in [(base_schema, base_table)] + [
        (r["right"]["schema"], r["right"]["table"]) for r in relationships
    ]:
        if (schema, table) not in seen:
            seen.add((schema, table))
            selected_tables.append({"schema": schema, "table": table})

    plan: dict[str, Any] = {
        "status": "success",
        "selected_tables": selected_tables,
        "base": {"schema": base_schema, "table": base_table},
        "relationships": relationships,
        "attributes": attributes,
        "primary_key": primary_key,
        "latest_only": bool(latest_only),
        "recency_column": recency_column,
        "warnings": _validate_plan_warnings(
            db, attributes, relationships, primary_key, latest_only, recency_column
        ),
    }
    return plan


def _validate_plan_warnings(
    db: Any,
    attributes: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    primary_key: str | None,
    latest_only: bool,
    recency_column: str | None,
) -> list[dict[str, str]]:
    """Run the parsed plan through the EXISTING validator (join type, fan-out, PK-unique, type-match)
    so SQL-defined mappings are checked exactly like builder ones. Non-blocking: returned as warnings
    (the builder still updates) and only when a primary key is known. Never raises."""
    if not primary_key or not any(a["name"] == primary_key for a in attributes):
        return []
    rels: list[dict[str, Any]] = [
        {"type": r["type"], "left": r["left"], "right": r["right"]} for r in relationships
    ]
    if latest_only:
        entry: dict[str, Any] = {"type": LATEST_CONFIG_TYPE, "latest_only": True}
        if recency_column:
            entry["recency_column"] = recency_column
        rels.append(entry)
    try:
        payload = DataModelCreate.model_validate({
            "name": "sql_preview",
            "display_name": "SQL preview",
            "type": "B",
            "primary_key": primary_key,
            "attributes": [
                {**a, "is_primary_key": a["name"] == primary_key} for a in attributes
            ],
            "relationships": rels,
            "latest_only": bool(latest_only),
            "recency_column": recency_column,
        })
        result = validate_type_b_mapping(db, payload)
        return list(result.get("warnings", []))
    except TypeBMappingError as exc:
        return list(exc.errors)
    except Exception:  # pragma: no cover - pydantic/edge; never block the plan
        return []


def generate_type_b_sql(
    *,
    base: dict[str, Any] | None,
    attributes: list[dict[str, Any]],
    relationships: list[dict[str, Any]] | None = None,
    primary_key: str | None = None,
    latest_only: bool = False,
    recency_column: str | None = None,
) -> dict[str, str]:
    """Plan -> canonical subset SQL text (no DB access, no execution). Inverse of parse_type_b_sql so
    the two surfaces round-trip. latest_only/PK live in the builder; latest_only adds a read-only
    leading comment describing the dedup (it is not re-parsed, by design)."""
    mapped = [a for a in (attributes or []) if a.get("source_table") and a.get("source_column")]
    if not mapped:
        _fail("attributes", "no mapped columns to generate SQL from.")
    rels = [
        r for r in (relationships or [])
        if isinstance(r, dict) and r.get("left") and r.get("right")
        and r.get("left", {}).get("table") and r.get("right", {}).get("table")
    ]

    right_tables = {(r["right"]["schema"], r["right"]["table"]) for r in rels}
    if base and base.get("table"):
        base_schema, base_table = base.get("schema"), base.get("table")
    else:
        candidates = [
            (a["source_schema"], a["source_table"]) for a in mapped
            if (a["source_schema"], a["source_table"]) not in right_tables
        ]
        if not candidates:
            _fail("base", "could not determine the base table (every table is a join target).")
        base_schema, base_table = candidates[0]
    base_schema = _wl_schema(base_schema, "schema")  # whitelist parity with parse
    base_table = _ident(base_table, "table")

    # Order joins greedily from the base so the generated FROM/JOIN chain is always valid SQL.
    present = {base_table}
    ordered: list[dict[str, Any]] = []
    remaining = list(rels)
    progressed = True
    while progressed and remaining:
        progressed = False
        still = []
        for r in remaining:
            if r["left"]["table"] in present:
                ordered.append(r)
                present.add(r["right"]["table"])
                progressed = True
            else:
                still.append(r)
        remaining = still
    ordered.extend(remaining)  # unreachable joins still rendered; the validator reports them

    projection = []
    for attribute in mapped:
        table = _ident(attribute["source_table"], "table")
        column = _ident(attribute["source_column"], "column")
        name = attribute.get("name")
        if name and name != column:
            projection.append(f"  {table}.{column} AS {_ident(name, 'attribute name')}")
        else:
            projection.append(f"  {table}.{column}")

    lines = ["SELECT", ",\n".join(projection), f"FROM {base_schema}.{base_table}"]
    for r in ordered:
        keyword = "LEFT JOIN" if r["type"] == "left" else "INNER JOIN"
        rs = _wl_schema(r["right"]["schema"], "schema")
        rt = _ident(r["right"]["table"], "table")
        rc = _ident(r["right"]["column"], "column")
        lt = _ident(r["left"]["table"], "table")
        lc = _ident(r["left"]["column"], "column")
        lines.append(f"{keyword} {rs}.{rt} ON {lt}.{lc} = {rt}.{rc}")

    sql = "\n".join(lines)
    if latest_only:
        # Identifier-validate recency before it goes into the comment so generate's output can never
        # contain attacker-controlled multi-line text (parity with validate_type_b_mapping).
        try:
            recency = _ident(recency_column or "updated_at", "recency_column")
        except TypeBSqlError:
            recency = "updated_at"
        comment = (
            f"-- latest_only is ON: the executed query keeps the newest row per key per table\n"
            f"-- (DISTINCT ON, recency column '{recency}'); toggle it in the builder, not in SQL.\n"
        )
        sql = comment + sql
    return {"sql": sql}
