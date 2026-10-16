from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.contracts import router as contracts_router
from app.api.routes.firms import router as firms_router
from app.api.routes.health import router as health_router
from app.api.routes.monitoring import router as monitoring_router
from app.api.routes.prevention import router as prevention_router
from app.api.routes.priorities import router as priorities_router
from app.api.routes.rainfall import router as rainfall_router
from app.api.routes.tasks import router as tasks_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "API for historical groundwater observations, NASA FIRMS thermal anomalies, "
            "traceable heuristic assessments, and field verification workflows."
        ),
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    application.add_middleware(GZipMiddleware, minimum_size=1000)
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(firms_router)
    application.include_router(monitoring_router)
    application.include_router(priorities_router)
    application.include_router(prevention_router)
    application.include_router(rainfall_router)
    application.include_router(tasks_router)
    application.include_router(contracts_router)
    return application


app = create_app()

