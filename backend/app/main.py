from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import build_api_router
from app.core.errors import install_error_handlers
from app.core.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="LocalETL API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.localetl_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(build_api_router())
    return app


app = create_app()
