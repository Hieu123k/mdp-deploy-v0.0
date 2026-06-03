# Connection Manager

The Connection Manager stores metadata for external systems that will be used by later sync, migration, data mapping, and Type B linked model milestones.

## Supported Types

- `postgresql`
- `oracle`
- `sqlserver`
- `rest_api`
- `mqtt`

## Credential Storage

Passwords are encrypted with Fernet before they are stored in PostgreSQL. The encryption key is derived from:

```text
CONNECTION_SECRET_KEY
```

API responses never return `password` or `encrypted_password`.

## Required Fields

Database connections (`postgresql`, `sqlserver`) require:

- `host`
- `port`
- `database_name`
- `username`

Oracle connections support service-name, SID, and direct DSN modes. In normal JDE usage, provide:

- `host`
- `port`, usually `1521`
- `database_name`, used as the service name by default
- `username`
- `password`

If `config.oracle_connect_mode` is `dsn`, provide `config.dsn` instead of host/port/database_name.

REST API connections require:

- `base_url`

MQTT connections require:

- `host`
- `port`

## Example PostgreSQL Connection

```json
{
  "name": "plant_postgres",
  "type": "postgresql",
  "host": "postgres",
  "port": 5432,
  "database_name": "mdp",
  "username": "mdp_user",
  "password": "mdp_password",
  "description": "Plant staging PostgreSQL database"
}
```

## Example Oracle JDE Connection

Service-name mode is the default. The backend uses `python-oracledb` thin mode, so Oracle Instant Client is not required for this MVP connection test.

```json
{
  "name": "jde_production",
  "type": "oracle",
  "host": "jde-db.company.local",
  "port": 1521,
  "database_name": "JDEPROD",
  "username": "jde_readonly",
  "password": "<password>",
  "config": {
    "oracle_connect_mode": "service_name",
    "service_name": "JDEPROD",
    "schema": "PRODDTA"
  },
  "description": "Oracle database used by JDE ERP"
}
```

SID mode:

```json
{
  "name": "jde_sid",
  "type": "oracle",
  "host": "jde-db.company.local",
  "port": 1521,
  "database_name": "JDEPRD",
  "username": "jde_readonly",
  "password": "<password>",
  "config": {
    "oracle_connect_mode": "sid",
    "sid": "JDEPRD",
    "schema": "PRODDTA"
  }
}
```

Direct DSN mode:

```json
{
  "name": "jde_dsn",
  "type": "oracle",
  "username": "jde_readonly",
  "password": "<password>",
  "config": {
    "oracle_connect_mode": "dsn",
    "dsn": "jde-db.company.local:1521/JDEPROD",
    "schema": "PRODDTA"
  }
}
```

## Connection Testing

- PostgreSQL tests open a connection and run `SELECT 1`.
- REST API tests send a `GET` request to `base_url` with a timeout.
- Oracle tests use `python-oracledb` thin mode, build the DSN from service-name/SID/direct DSN config, open a connection, and run `SELECT 1 FROM DUAL`.
- Oracle test failures return clearer messages for missing config, missing password, unavailable driver, authentication failure, unavailable listener, unknown service name, or unknown SID.
- SQL Server tests return a clear unavailable-driver message if `pyodbc` or an ODBC driver is missing.
- MQTT tests validate metadata only and do not open a runtime MQTT connection yet.

## Current Limitations

- No sync jobs.
- No external table browsing.
- No migration workflows.
- No Oracle source browser yet.
- No Oracle migration jobs yet.
- No MQTT runtime connection test.

The next Oracle-related milestones are Oracle Source Browser and Migration Jobs.
