# TIPA DW — Ora2Pg Linux Production Kit

Migrate JDE tables from Oracle into the PostgreSQL mirror (`uns_db`) via an ora2pg
Docker container, then seed the Node-RED incremental scheduler.

## Credentials (1 lần)

```bash
cp .env.example .env
# Sửa .env: điền user/pass Oracle + PostgreSQL thật.
# .env đã được gitignore — TUYỆT ĐỐI KHÔNG commit secrets.
```

`migrate.sh` đọc creds từ `.env` và render `config/ora2pg.conf` từ
`config/ora2pg.conf.example` lúc chạy (file `config/ora2pg.conf` cũng gitignored).

## Setup (1 lần)

```bash
unzip ora2pg_linux.zip        # hoặc dùng trực tiếp tools/ora2pg trong source
cd ora2pg

docker compose pull           # Pull image (~1.5GB)
./migrate.sh --table V2_PRO_F0911 --rows 1000   # smoke test 1000 rows
```

## Full production load

```bash
./migrate.sh --table V2_PRO_F0911
```

Mất ~30-60 phút cho F0911 30M rows. Script tự:
1. Tạo bảng PG nếu thiếu (DDL pass)
2. TRUNCATE + COPY full data
3. Verify count Oracle == PG
4. Seed Node-RED `inc_sync_schedules` với cursor = max(GLUPMJ)

Sau đó vào Node-RED UI Incremental tab, table sẽ tự xuất hiện và bắt đầu sync delta mỗi 5 phút.

## Quy trình production khuyến nghị

| Tần suất | Lệnh |
|---|---|
| **Khởi tạo (1 lần)** | `./migrate.sh --table V2_PRO_F0911` |
| **Quarterly refresh** (nếu cần align lại schema/data) | Same as above |
| **Daily/Hourly delta** | Node-RED Incremental tab tự chạy |

## Bảng đã hỗ trợ TS_COL auto-detect

| JDE Table | TS Column |
|---|---|
| F0911 | GLUPMJ |
| F4111 | ILUPMJ |
| F4311 | PDUPMJ |
| F0411 | RPUPMJ |
| F0101 | ABUPMJ |
| F4801 | WAUPMJ |
| F43099 | PRUPMJ |
| F43199 | PDUPMJ |

Bảng khác: script default `GLUPMJ`, sửa `migrate.sh` case statement nếu khác.

## Troubleshooting

### ora2pg `logit` undef error
Config có inline comment hoặc CRLF. Kiểm tra:
```bash
docker exec tipa_ora2pg cat -A /config/ora2pg.conf | head -5
```
Nếu thấy `^M$` cuối dòng → strip CRLF: `sed -i 's/\r$//' config/ora2pg.conf`

### Container không reach được Oracle/PG
`network_mode: host` đã set trong docker-compose.yml — Linux thấy mọi LAN address. Nếu fail, kiểm tra firewall:
```bash
sudo iptables -L OUTPUT -n
```

### "destination table doesn't exist"
DDL pass tự chạy nếu cột=0. Force re-create (creds lấy từ .env):
```bash
source .env
psql "postgresql://$PG_USER:$PG_PWD@$PG_HOST:$PG_PORT/$PG_DBNAME" \
  -c 'DROP TABLE public."V2_PRO_F0911"'
./migrate.sh --table V2_PRO_F0911 --rows 1000
```
