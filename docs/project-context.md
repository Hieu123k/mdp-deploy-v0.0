# Project Context Snapshot

## 1. Product Name

Full product name: **Avenue Manufacturing Data Platform**

Short name: **Avenue MDP**

## 2. Product Vision

Avenue Manufacturing Data Platform is a configurable manufacturing data platform that standardizes business and operational data into governed data models. It exposes controlled data services and APIs for applications, BI tools, integrations, and future AI agents.

The platform is intended to become a foundation for canonical manufacturing data, enterprise integration, semantic search, governed AI access, and future IIoT/UNS integration without forcing consumers to understand raw ERP or source database schemas.

## 3. Core Problem

Applications, BI tools, integrations, and future AI agents should not query ERP, JDE, SQL Server, Oracle, or other source databases directly.

Direct source access creates several risks:

- Performance impact on operational systems
- Security exposure and uncontrolled credentials
- Reliability problems when source systems are unavailable or slow
- Complex ERP schemas that are difficult for downstream users to understand
- Weak governance, lineage, and auditability
- Tight coupling between consumers and source database structures

## 4. Core Solution

Avenue MDP provides a governed abstraction layer over manufacturing and enterprise data:

- Source and staging data is copied or linked into PostgreSQL.
- Data Models define governed business objects.
- Type A models ingest data and generate storage tables.
- Type B models link to existing staging tables or views.
- External bulk loaders such as ora2pg perform high-volume JDE/Oracle initial loads into PostgreSQL staging.
- Migration Jobs track external migration metadata, run history, and target validation results.
- Outbound APIs expose model data through controlled endpoints.
- API keys allow external systems to access approved models and directions.
- Transaction logs provide traceability for inbound and outbound activity.

This creates a controlled data service layer between source systems and consuming applications.

## 5. Current Technology Stack

- Backend: Python FastAPI
- Frontend: Next.js App Router
- Database: PostgreSQL 16
- ORM: SQLAlchemy
- Migration: Alembic
- Auth: JWT
- Password hashing: passlib/bcrypt
- API key auth: `X-API-Key`
- Connection password encryption: Fernet
- Containerization: Docker Compose
- DB admin local: pgAdmin

## 6. Current Repository Structure

- `backend/`: FastAPI application, SQLAlchemy models, Alembic migrations, API routes, services, schemas, tests.
- `frontend/`: Next.js App Router Admin UI for users, data models, browsers, transactions, API keys, connections, and demo data.
- `docs/`: Architecture, API, data model, deployment, connection manager, and project context documentation.
- `docker-compose.yml`: Local development stack for PostgreSQL, backend, frontend, and pgAdmin.
- `.env.example`: Environment variable template for local configuration and secrets.

## 7. Current Completed Capabilities

- Project foundation
- Auth and user management
- API key authentication
- Connection Manager
- Data Model CRUD
- Type A generated tables
- Type A dynamic inbound API
- Type A dynamic outbound API
- Mock JDE procurement staging data
- DB Browser
- Type B Linked Data Model backend
- Type B Mapping UI
- Type B outbound API
- Migration Job Registry
- External ora2pg migration tracking
- Migration run history
- PostgreSQL target staging validation
- Migration scope, row-limit, time-window, and watermark metadata foundation
- JDE Procurement Migration Templates
- JDE Type B Data Model Templates
- Guided JDE Procurement Demo Flow
- Data Browser
- Transaction Monitor
- Admin UI consolidation
- User Management UI
- Data Model classification and namespace metadata

## 8. Data Model Concepts

### Type A: Ingested Model

Type A models represent data received by Avenue MDP.

- Creates a generated PostgreSQL table in `mdp_data`
- Receives data through `POST /inbound/{model_name}`
- Returns data through `GET /outbound/{model_name}`
- Stores raw inbound JSON in `raw_payload`

Example generated table:

```text
mdp_data.dm_invoice
```

### Type B: Linked Model

Type B models represent governed views over existing PostgreSQL staging tables or views.

- Does not create a new physical table
- Maps attributes to `source_schema`, `source_table`, and `source_column`
- Uses staging tables/views such as `mdp_staging.stg_jde_supplier`
- Uses governed outbound APIs
- Supports one source table or view per model in the MVP
- Multi-table data should be represented through a PostgreSQL view, not a multi-table join engine

## 9. PostgreSQL Schemas

- `mdp_data`: generated Type A data tables.
- `mdp_staging`: mock migrated ERP/JDE staging tables and curated views.
- Metadata/system tables: `users`, `data_models`, `api_keys`, `connections`, `transactions`, and related platform tables.
- Migration registry tables: `migration_jobs`, `migration_runs`, and `migration_validations`.

## 10. Mock JDE Procurement Data

The MVP includes mock procurement staging data that simulates migrated Oracle JDE data already copied into PostgreSQL by an external ETL or migration tool.

- `mdp_staging.stg_jde_supplier`: simulates JDE `F0101/F0401`
- `mdp_staging.stg_jde_po_header`: simulates JDE `F4301`
- `mdp_staging.stg_jde_po_line`: simulates JDE `F4311`
- `mdp_staging.stg_jde_po_receipt`: simulates JDE `F43121`
- `mdp_staging.stg_jde_ap_invoice`: simulates JDE `F0411`
- `mdp_staging.vw_jde_purchase_order_summary`: curated view for Type B purchase order summary mapping

## 11. Important Demo Models

### supplier

- Type: Type B
- Source: `mdp_staging.stg_jde_supplier`
- Primary key: `supplier_code`

### purchase_order_summary

- Type: Type B
- Source: `mdp_staging.vw_jde_purchase_order_summary`
- Primary key: `po_no`

## 12. Key API Endpoints

- `POST /auth/login`
- `GET /auth/me`
- `/users`
- `/api-keys`
- `/data-models`
- `POST /data-models/type-b/validate-mapping`
- `POST /data-models/type-b/preview`
- `GET /data-models/{id}/mapped-preview`
- `POST /inbound/{model_name}`
- `GET /outbound/{model_name}`
- `GET /outbound/{model_name}/{key}`
- `/db-browser`
- `/transactions`
- `/migration-jobs`
- `/migration-runs`
- `/migration-templates`
- `/data-model-templates`
- `GET /demo/jde-procurement/workflow-status`
- `/admin/demo/seed-procurement-staging`

## 13. Security Design

- Human users use JWT authentication.
- External systems use API keys through the `X-API-Key` header.
- Plain API keys are shown once at creation time and stored only as hashes.
- API keys are scoped by `allowed_directions` and `allowed_models`.
- Connection passwords are encrypted using Fernet.
- Dynamic SQL must use strict identifier validation and bound values.
- Raw source database access is not exposed directly to AI tools, apps, or external consumers.
- Production deployments must not use default secrets.

## 14. Important Architecture Decisions

- Use Type B models with staging tables/views instead of querying ERP directly.
- Large JDE Oracle initial full-load migrations should use ora2pg or external bulk loaders.
- MDP does not run 30M+ row migrations inside FastAPI request handlers.
- MDP tracks external migration jobs/runs and validates `mdp_staging` targets.
- After validation, Type B models expose migrated staging data through governed outbound APIs.
- Migration jobs store the last successful watermark to support future incremental updates.
- Data integrity validation starts with target-side checks and can be expanded to source-target reconciliation later.
- JDE Procurement Migration Templates provide consistent starting points for common JDE procurement staging jobs.
- JDE Type B Data Model Templates create governed models from validated JDE staging tables/views.
- The guided JDE Demo Flow demonstrates the MVP path from staging data through migration tracking, validation, Type B model creation, outbound API query, and transaction logging.
- Use PostgreSQL views for multi-table curated objects such as `purchase_order_summary`.
- Do not implement a multi-table Type B join engine in the MVP.
- Keep IIoT and time-series storage out of this Manufacturing Data Platform MVP.
- Future IIoT data should be integrated through identifiers such as `asset_id`, `site_id`, and `tag_id`, and should use a time-series database when needed.
- Data model hierarchy and namespace metadata should support future canonical models, UNS, semantic layer, and AI search.
- Do not let AI agents query raw ERP or source databases directly. Future agents should use approved APIs and tools.

## 15. Data Model Classification / Namespace Direction

Recommended metadata fields:

- `namespace`
- `domain`
- `entity_type`
- `business_process`
- `source_layer`
- `canonical_status`
- `site_scope`

Direction:

- `domain` should be required or strongly encouraged.
- `namespace` can be auto-generated.
- `source_layer` can be inferred.
- `canonical_status` can default to `experimental`.
- `site_scope` can default to `enterprise`.

## 16. UI/UX Direction

- Product name: Avenue Manufacturing Data Platform
- Short name: Avenue MDP
- Enterprise admin UI
- Frontend is a Next.js App Router application migrated from the `Hieu123k/MDP-ver1.0` variant repository
- Local frontend builds use `NEXT_PUBLIC_API_URL=http://localhost:8000`
- Production frontend builds leave `NEXT_PUBLIC_API_URL` empty and call same-origin `/api/*` through Caddy
- Frontend code should pass canonical backend paths such as `/data-models` into `frontend/src/lib/api.ts`; the helper adds `/api` only for the public proxy route
- Dark sidebar with light content area
- Avenue red accent color
- Use Inter or IBM Plex Sans
- Use dropdowns/selectors for controlled values
- Data Models list should be compact
- Create/View/Edit flows should use drawers or modals
- DB Browser should be simple and table-focused
- DB Browser should not show `raw_payload` by default
- Long table cells should be truncated with ellipsis

## 17. Current Recommended Next Steps

1. Harden Migration and Data Model templates for customer-specific JDE schemas if needed.
2. Run UAT with real ora2pg migrated JDE staging data.
3. Create Type B models from real JDE staging.
4. Cloud deployment.
5. Later: incremental sync, scheduler, migration worker, WSO2 integration adapter.

## 18. Deferred Future Phases

- Oracle JDE source browser
- ora2pg worker container or external migration runner orchestration
- Sync job scheduler
- SQL Server connector production flow
- MQTT/IIoT ingestion
- Time-series DB
- Asset hierarchy / UNS
- Data lineage
- Data quality rules
- Relationship registry
- Data catalog / business glossary
- Knowledge Graph
- Semantic Query API
- AI Agent Tool Registry
- Natural language query

## 19. Standard Working Method

- Work in small steps.
- Use Codex for implementation.
- Test locally with Docker Compose.
- Commit only after each step passes.
- Prefer one clean commit per step.
- Use ChatGPT for architecture review, test planning, and Codex prompts.
- Store important project knowledge in docs instead of relying on long chat history.

## 20. New Chat Continuation Instruction

When starting a new ChatGPT session, provide this repository URL and ask ChatGPT to read docs/project-context.md first before continuing.

Example:

```text
Repo: https://github.com/hieudovn/manufacturing-data-platform
Please read docs/project-context.md to understand the current project context, architecture, completed steps, design decisions, and roadmap before helping me continue development.
```
