from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin_demo import router as admin_demo_router
from app.api.api_keys import router as api_keys_router
from app.api.auth import router as auth_router
from app.api.connections import router as connections_router
from app.api.data_models import router as data_models_router
from app.api.data_model_templates import router as data_model_templates_router
from app.api.db_browser import router as db_browser_router
from app.api.health import router as health_router
from app.api.inbound import router as inbound_router
from app.api.jde_demo_workflow import router as jde_demo_workflow_router
from app.api.migration_jobs import router as migration_jobs_router
from app.api.migration_templates import router as migration_templates_router
from app.api.ora2pg_dashboard import router as ora2pg_dashboard_router
from app.api.outbound import router as outbound_router
from app.api.streaming import router as streaming_router
from app.api.transactions import router as transactions_router
from app.api.users import router as users_router
from app.core.config import settings
from app.db.session import SessionLocal
from app.services.source_count_refresher import SourceCountRefresher
from app.services.streaming_refresher import StreamingRefresher
from app.services.user_service import seed_default_admin


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    with SessionLocal() as db:
        seed_default_admin(db)
    refresher = SourceCountRefresher()
    try:
        refresher.start()  # no-op unless ORA2PG_SOURCE_COUNT_ENABLED
    except Exception:  # pragma: no cover - never block startup on the refresher
        pass
    app.state.source_count_refresher = refresher
    streaming = StreamingRefresher()
    try:
        streaming.start()  # no-op unless STREAMING_ENABLED
    except Exception:  # pragma: no cover - never block startup on the streaming loop
        pass
    app.state.streaming_refresher = streaming
    try:
        yield
    finally:
        await refresher.stop()
        await streaming.stop()


app = FastAPI(
    title="Manufacturing Data Platform API",
    version="0.1.0",
    docs_url="/docs",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(admin_demo_router)
app.include_router(data_models_router)
app.include_router(data_model_templates_router)
app.include_router(db_browser_router)
app.include_router(jde_demo_workflow_router)
app.include_router(api_keys_router)
app.include_router(connections_router)
app.include_router(migration_jobs_router)
app.include_router(migration_templates_router)
app.include_router(ora2pg_dashboard_router)
app.include_router(inbound_router)
app.include_router(outbound_router)
app.include_router(transactions_router)
app.include_router(streaming_router)
