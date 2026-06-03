#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# TIPA DW - Ora2Pg (LINUX ULTIMATE: AUTO-DISCOVERY + CLEAN DROP)
# Credentials are loaded from .env (gitignored). Copy .env.example -> .env first.
# Usage:
#   ./migrate.sh -Table V2_PRO_F0911 -TsCol upmj
#   ./migrate.sh -Table V2_PRO_F4311 -TsCol pdupmj -TestRows 1000
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

# Tham số mặc định
TABLE="V2_PRO_F0911"
TS_COL="upmj"
TEST_ROWS=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Màu mè hiển thị cho Terminal (giống Windows)
C_CYAN=$'\e[36m'; C_GREEN=$'\e[32m'; C_YELLOW=$'\e[33m'; C_RED=$'\e[31m'; C_MAGENTA=$'\e[35m'; C_END=$'\e[0m'

# Đọc tham số truyền vào
while [[ $# -gt 0 ]]; do
    case "$1" in
        -Table|-table|--table) TABLE="$2"; shift 2 ;;
        -TsCol|-tscol|--tscol) TS_COL="$2"; shift 2 ;;
        -TestRows|-testrows|--rows) TEST_ROWS="$2"; shift 2 ;;
        *) echo "Tham số không hợp lệ: $1"; exit 1 ;;
    esac
done

# ── Load credentials from .env (gitignored; copy from .env.example) ──
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a; source "$SCRIPT_DIR/.env"; set +a
else
    echo "${C_RED}Missing .env — copy .env.example to .env and fill in credentials.${C_END}"; exit 1
fi
: "${ORACLE_HOST:?set ORACLE_HOST in .env}"; : "${ORACLE_SID:?set ORACLE_SID in .env}"; : "${ORACLE_PORT:?set ORACLE_PORT in .env}"
: "${ORACLE_USER:?set ORACLE_USER in .env}"; : "${ORACLE_PWD:?set ORACLE_PWD in .env}"
: "${PG_HOST:?set PG_HOST in .env}"; : "${PG_PORT:?set PG_PORT in .env}"; : "${PG_DBNAME:?set PG_DBNAME in .env}"
: "${PG_USER:?set PG_USER in .env}"; : "${PG_PWD:?set PG_PWD in .env}"

# ── Render config/ora2pg.conf from template + .env (rendered file is gitignored) ──
sed -e "s|__ORACLE_DSN__|dbi:Oracle:host=${ORACLE_HOST};sid=${ORACLE_SID};port=${ORACLE_PORT}|" \
    -e "s|__ORACLE_USER__|${ORACLE_USER}|" \
    -e "s|__ORACLE_PWD__|${ORACLE_PWD}|" \
    -e "s|__PG_DSN__|dbi:Pg:dbname=${PG_DBNAME};host=${PG_HOST};port=${PG_PORT}|" \
    -e "s|__PG_USER__|${PG_USER}|" \
    -e "s|__PG_PWD__|${PG_PWD}|" \
    "$SCRIPT_DIR/config/ora2pg.conf.example" > "$SCRIPT_DIR/config/ora2pg.conf"

echo "${C_CYAN}===================================================${C_END}"
echo "${C_CYAN}TIPA DW Migration via Ora2Pg Docker (Linux Edition)${C_END}"
echo "${C_CYAN}Table Target: $TABLE${C_END}"
echo "${C_CYAN}===================================================${C_END}"

# ── Hàm chạy Perl siêu mượt trong Container ───────────
run_perl() {
    local PerlCode="$1"
    local tmpLocal=$(mktemp /tmp/ora2pg_XXXXXX.pl)
    echo "$PerlCode" > "$tmpLocal"
    docker cp "$tmpLocal" tipa_ora2pg:/tmp/run.pl >/dev/null
    local result=$(docker exec tipa_ora2pg perl /tmp/run.pl 2>&1)
    docker exec tipa_ora2pg rm -f /tmp/run.pl >/dev/null 2>&1
    rm -f "$tmpLocal"
    echo "$result"
}

# 1. Start container
echo "${C_YELLOW}[1/7] Starting ora2pg container...${C_END}"
docker compose up -d
sleep 2

# 2. AUTO-DISCOVERY
echo "${C_YELLOW}[2/7] Auto-Discovering Object in Oracle...${C_END}"
discoverPerl=$(cat << 'EOF'
use DBI;
eval {
    my $dbh = DBI->connect("dbi:Oracle:host=__ORACLE_HOST__;sid=__ORACLE_SID__;port=__ORACLE_PORT__", "__ORACLE_USER__", "__ORACLE_PWD__", { RaiseError => 1, PrintError => 0 });
    my $tbl = uc('__TABLE__');
    my ($owner, $type) = $dbh->selectrow_array("SELECT owner, object_type FROM all_objects WHERE object_name = ? AND owner IN ('SYSTEM', '__ORACLE_USER_UC__') AND ROWNUM = 1", undef, $tbl);
    if ($owner) {
        my ($cnt) = $dbh->selectrow_array("SELECT COUNT(*) FROM $owner.$tbl");
        print "FOUND|$owner|$type|$cnt";
    } else {
        print "NOT_FOUND";
    }
    $dbh->disconnect;
};
if ($@) { print "ERROR: $@"; }
EOF
)
discoverPerl="${discoverPerl//__TABLE__/$TABLE}"
discoverPerl="${discoverPerl//__ORACLE_HOST__/$ORACLE_HOST}"
discoverPerl="${discoverPerl//__ORACLE_SID__/$ORACLE_SID}"
discoverPerl="${discoverPerl//__ORACLE_PORT__/$ORACLE_PORT}"
discoverPerl="${discoverPerl//__ORACLE_USER_UC__/$(echo "$ORACLE_USER" | tr '[:lower:]' '[:upper:]')}"
discoverPerl="${discoverPerl//__ORACLE_USER__/$ORACLE_USER}"
discoverPerl="${discoverPerl//__ORACLE_PWD__/$ORACLE_PWD}"
discovery=$(run_perl "$discoverPerl")

IFS='|' read -r -a parts <<< "$discovery"
if [[ "${parts[0]}" != "FOUND" ]]; then
    echo "${C_RED}  FAIL: Could not find $TABLE in Oracle!${C_END}"
    exit 1
fi

OracleSchema="${parts[1]}"
ObjectType="${parts[2]}"
OracleCount="$(echo -e "${parts[3]}" | tr -d '[:space:]')"

echo "  ${C_GREEN}-> Discovered: Schema [$OracleSchema], Type [$ObjectType], Rows [$OracleCount]${C_END}"

if (( TEST_ROWS > 0 )); then
    expectedRows=$(( OracleCount < TEST_ROWS ? OracleCount : TEST_ROWS ))
    echo "  ${C_YELLOW}-> Will migrate: $expectedRows rows (TEST MODE)${C_END}"
else
    expectedRows=$OracleCount
fi

# 3. Update config dynamically
echo -e "\n${C_YELLOW}[3/7] Updating config dynamically...${C_END}"
CONFIG="config/ora2pg.conf"
TMP_CONF=$(mktemp)

# Dọn dẹp rác config cũ
grep -v -E '^(SCHEMA|ALLOW|MODIFY_TYPE|VIEW_AS_TABLE|EXPORT_SCHEMA|DEFAULT_NUMERIC|DROP_IF_EXISTS|WHERE|#\s*WHERE)' "$CONFIG" > "$TMP_CONF"

# Bơm config mới vào
{
    echo "SCHEMA           $OracleSchema"
    echo "ALLOW            $TABLE"
    echo "MODIFY_TYPE      $TABLE:*:text"
    echo "EXPORT_SCHEMA    0"
    echo "DEFAULT_NUMERIC  numeric"
    echo "DROP_IF_EXISTS   1"
} >> "$TMP_CONF"

if [[ "$ObjectType" == *"VIEW"* ]]; then
    echo "VIEW_AS_TABLE    $TABLE" >> "$TMP_CONF"
fi

if (( TEST_ROWS > 0 )); then
    echo "" >> "$TMP_CONF"
    echo "WHERE            ROWNUM <= $TEST_ROWS" >> "$TMP_CONF"
fi

mv "$TMP_CONF" "$CONFIG"

# 4. Auto-Schema Creation
echo -e "\n${C_MAGENTA}[4/7] Generating and Creating PostgreSQL Schema...${C_END}"
echo -e "  -> Extracting DDL from Oracle...\033[0m"
docker exec tipa_ora2pg bash -c "ora2pg -c /config/ora2pg.conf -t TABLE -b /tmp -o auto_schema.sql" > /dev/null 2>&1

echo -e "  -> Executing DDL in PostgreSQL...\033[0m"
schemaExecPerl=$(cat << 'EOF'
use DBI;
eval {
    my $dbh = DBI->connect("dbi:Pg:dbname=__PG_DBNAME__;host=__PG_HOST__;port=__PG_PORT__", "__PG_USER__", "__PG_PWD__", { RaiseError => 1, PrintWarn => 0, AutoCommit => 1 });
    $dbh->do("SET client_min_messages = warning;");

    my $tbl_lc = lc('__TABLE__');
    $dbh->do(qq{DROP TABLE IF EXISTS public."$tbl_lc" CASCADE;});
    $dbh->do(qq{DROP VIEW IF EXISTS public."$tbl_lc" CASCADE;});

    open my $fh, "<", "/tmp/auto_schema.sql" or die "Cannot open schema file";
    my $sql = do { local $/; <$fh> };
    close $fh;

    $sql =~ s/^\\.*//mg;
    $dbh->do($sql) if $sql =~ /\S/;
    $dbh->disconnect;
    print "OK";
};
if ($@) { print "FAIL: $@"; }
EOF
)
schemaExecPerl="${schemaExecPerl//__TABLE__/$TABLE}"
schemaExecPerl="${schemaExecPerl//__PG_DBNAME__/$PG_DBNAME}"
schemaExecPerl="${schemaExecPerl//__PG_HOST__/$PG_HOST}"
schemaExecPerl="${schemaExecPerl//__PG_PORT__/$PG_PORT}"
schemaExecPerl="${schemaExecPerl//__PG_USER__/$PG_USER}"
schemaExecPerl="${schemaExecPerl//__PG_PWD__/$PG_PWD}"
schemaResult=$(run_perl "$schemaExecPerl")

if [[ "$schemaResult" == "OK" ]]; then
    echo "  ${C_GREEN}-> Schema created successfully! (Old traces wiped clean)${C_END}"
else
    echo "  ${C_RED}-> WARNING: Schema creation failed: $schemaResult${C_END}"
    exit 1
fi

# 5. Run migration COPY
echo -e "\n${C_YELLOW}[5/7] Running ora2pg -t COPY...${C_END}"
START_TIME=$(date +%s)
docker exec tipa_ora2pg ora2pg -c /config/ora2pg.conf -t COPY
END_TIME=$(date +%s)
DURATION=$(( END_TIME - START_TIME ))
printf "  ${C_GREEN}Duration: %02d:%02d:%02d${C_END}\n" $((DURATION/3600)) $(((DURATION%3600)/60)) $((DURATION%60))

# 6. Verify Data
echo -e "\n${C_YELLOW}[6/7] Verifying Data...${C_END}"
pgCountPerlTemplate=$(cat << 'EOF'
use DBI;
my $dbh = DBI->connect("dbi:Pg:dbname=__PG_DBNAME__;host=__PG_HOST__;port=__PG_PORT__", "__PG_USER__", "__PG_PWD__") or die $DBI::errstr;
my ($n) = $dbh->selectrow_array(qq{SELECT COUNT(*) FROM public.__TABLE__});
print $n;
$dbh->disconnect;
EOF
)
pgCountPerl="${pgCountPerlTemplate//__TABLE__/$TABLE}"
pgCountPerl="${pgCountPerl//__PG_DBNAME__/$PG_DBNAME}"
pgCountPerl="${pgCountPerl//__PG_HOST__/$PG_HOST}"
pgCountPerl="${pgCountPerl//__PG_PORT__/$PG_PORT}"
pgCountPerl="${pgCountPerl//__PG_USER__/$PG_USER}"
pgCountPerl="${pgCountPerl//__PG_PWD__/$PG_PWD}"
pgCount=$(run_perl "$pgCountPerl")
echo "  PG rows after load: $pgCount"

if [[ "$expectedRows" == "$pgCount" ]]; then
    echo "  ${C_GREEN}COUNT MATCH - OK${C_END}"
else
    echo "  ${C_RED}MISMATCH: expected=$expectedRows PG=$pgCount${C_END}"
fi

if (( TEST_ROWS > 0 )); then
    echo -e "\n${C_YELLOW}TEST DONE: Mode limit rows - Skipping seeding.${C_END}"
    exit 0
fi

# 7. Seed Node-RED
echo -e "\n${C_YELLOW}[7/7] Seeding last_max_cursor for Node-RED...${C_END}"
jdeTable="${TABLE#V2_PRO_}"
tsColLower=$(echo "$TS_COL" | tr '[:upper:]' '[:lower:]')

seedPerlTemplate=$(cat << 'EOF'
use DBI;
my $dbh = DBI->connect("dbi:Pg:dbname=__PG_DBNAME__;host=__PG_HOST__;port=__PG_PORT__", "__PG_USER__", "__PG_PWD__") or die $DBI::errstr;

my ($maxTs) = $dbh->selectrow_array(qq{SELECT COALESCE(MAX(__TSCOL__::bigint), 0) FROM public.__TABLE__});
$dbh->do(q{
    INSERT INTO dw_sync_schedules
        (table_name, pg_table, oracle_schema, sync_type, ts_col,
         interval_sec, row_limit, enabled, last_max_cursor)
    VALUES (?, ?, '__SCHEMA__', 'incremental', '__TSCOL__', 300, 0, true, ?)
    ON CONFLICT (table_name) DO UPDATE SET
        sync_type = 'incremental', enabled = true,
        last_max_cursor = EXCLUDED.last_max_cursor, interval_sec = 300
}, {}, "__JDE__", "__TABLE__", "$maxTs");
print "  Node-RED Schedule seeded for __JDE__ with Cursor: $maxTs\n";
$dbh->disconnect;
EOF
)
seedPerl="${seedPerlTemplate//__TABLE__/$TABLE}"
seedPerl="${seedPerl//__JDE__/$jdeTable}"
seedPerl="${seedPerl//__TSCOL__/$tsColLower}"
seedPerl="${seedPerl//__SCHEMA__/$OracleSchema}"
seedPerl="${seedPerl//__PG_DBNAME__/$PG_DBNAME}"
seedPerl="${seedPerl//__PG_HOST__/$PG_HOST}"
seedPerl="${seedPerl//__PG_PORT__/$PG_PORT}"
seedPerl="${seedPerl//__PG_USER__/$PG_USER}"
seedPerl="${seedPerl//__PG_PWD__/$PG_PWD}"

run_perl "$seedPerl" | while read -r line; do echo "  $line"; done

echo -e "\n${C_GREEN}===================================================${C_END}"
echo "${C_GREEN}DONE: $OracleSchema.$TABLE${C_END}"
echo "${C_GREEN}===================================================${C_END}"
