# MVP Architecture

This milestone establishes a clean, Dockerized project foundation for Avenue Manufacturing Data Platform (Avenue MDP). It is designed to run locally on a personal laptop with Docker Compose before later deployment to a cloud server.

## Services

### Frontend

The frontend is a Next.js App Router application. It runs on port `3000` and provides login plus a consolidated Admin UI with a sidebar, dashboard metrics, data model management, Type B mapping, DB browsing, outbound data browsing, transaction viewing, API key management, connection management, demo data controls, and user viewing.

### Backend

The backend is a Python FastAPI service. It runs on port `8000`, exposes OpenAPI documentation at `/docs`, configures local-development CORS, and includes a SQLAlchemy database connection foundation.

The backend also provides JWT authentication, API key authentication for external systems, and basic user management. Passwords are hashed with bcrypt and stored in the `users` table. API keys are hashed before storage and the plain key is returned only once when created.

Data model management stores business object metadata in the `data_models` table. Type A models also create generated PostgreSQL storage tables in the `mdp_data` schema. Type B models remain metadata-only in this milestone.

Dynamic inbound REST APIs accept authenticated flat JSON payloads for active Type A models and write transaction logs for both successful and failed processing.

Dynamic outbound REST APIs expose integrated Type A data through model-based endpoints without exposing raw tables or accepting user SQL.

Inbound and outbound APIs accept either a valid user JWT or a scoped API key. API keys can be limited by direction and data model.

The Connection Manager stores external system connection metadata for PostgreSQL, Oracle, SQL Server, REST API, and MQTT endpoints. Passwords are encrypted before storage and are never returned by API responses. These records are intended for later source browsing, sync jobs, mapping, migration tracking, and Type B linked model features.

The `mdp_staging` PostgreSQL schema contains mock JDE procurement staging tables for MVP demos. These tables represent data already migrated by an external ETL or bulk migration tool and support Type B linked data models.

The DB Browser provides JWT-protected, read-only metadata and preview access to verified PostgreSQL schemas and tables. It is intended to help administrators inspect staging data before defining Type B Linked Data Models.

The Data Browser provides a UI over governed outbound APIs. Administrators select a saved Type A or Type B model, apply equality filters using model attribute names, optionally look up a primary key value, and view the API response without directly querying source tables.

Type B Linked Data Model backend support validates mappings from model attributes to existing PostgreSQL staging columns, previews mapped rows without creating physical tables, and exposes saved linked models through governed outbound APIs.

### Database

PostgreSQL 16 is the primary application database. It uses the default MVP database settings:

- Database: `mdp`
- User: `mdp_user`
- Password: `mdp_password`

Data is persisted in the Docker named volume `postgres_data`.

### Migration Layer

Alembic manages platform metadata tables, including users, data models, API keys, connections, transactions, and migration registry tables. Generated Type A storage tables are created by the application service at model creation time.

Large JDE/Oracle initial loads are intentionally external to FastAPI. Avenue MDP does not replace ora2pg for 30M+ row tables and does not run long row-by-row migrations inside request handlers. Instead, the Migration Job Registry records external ora2pg/manual run metadata, tracks run status and row counts from logs, and validates the PostgreSQL staging target after data lands in `mdp_staging`.

Target validation checks that the configured staging schema/table exists, counts rows, verifies configured primary key columns, reports primary key nulls or duplicates, and returns a small sample preview. Future phases may add a worker container to invoke ora2pg safely outside the web API.

### pgAdmin

pgAdmin is included as an optional local database administration tool on port `5050`.

## Current Scope

Implemented:

- Docker Compose orchestration
- FastAPI app shell
- Health check endpoint
- JWT authentication
- Basic user management APIs
- Default admin user seeding
- Data model metadata CRUD APIs
- Type A generated PostgreSQL table creation
- Dynamic inbound REST API for Type A models
- Dynamic outbound REST API for Type A models
- Transaction logging and transaction read APIs
- API key management and scoped API key authentication
- Connection metadata CRUD and basic connection testing
- Migration job and run tracking for external ora2pg/bulk-loader migrations
- PostgreSQL staging target validation for migration runs
- Mock JDE procurement staging tables and seed data
- DB Table Browser for schemas, tables, columns, and preview rows
- Type B mapping validation and mapped preview backend APIs
- SQLAlchemy database connection setup
- Alembic migration setup
- Next.js dashboard shell
- Frontend login, protected dashboard, and data model page
- Local documentation

Explicitly deferred:

- Fine-grained role-based authorization
- Generated table schema evolution
- Generated table archival/drop policy
- API key rotation workflows
- External API key self-service
- Long-running ora2pg execution from FastAPI
- Connection-driven sync jobs
- Native large-table Python/ORM migration
- External table browsing
- ERP and SQL Server integration
- Time-series databases, TimescaleDB, IIoT, sensor data, and realtime telemetry

## Runtime Flow

1. Docker Compose starts PostgreSQL.
2. The backend waits for PostgreSQL health before starting.
3. The frontend starts after the backend service is created.
4. Browser users open `http://localhost:3000`.
5. The dashboard calls `http://localhost:8000/health`.
6. FastAPI returns the backend service status.
