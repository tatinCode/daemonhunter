from fastapi import FastAPI, Request, Response
from starlette.middleware.base import RequestResponseEndpoint

from daemonhunter.routers.admin_users import router as admin_users_router
from daemonhunter.routers.admin_devices import router as admin_devices_router
from daemonhunter.routers.auth import router as auth_router
from daemonhunter.routers.devices import router as devices_router
from daemonhunter.schemas import HealthResponse
from daemonhunter.config import (
        SETUP_TOKEN,
        SETUP_TOKEN_WAS_GENERATED,
        )

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import logging


logger = logging.getLogger("daemonhunter")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if SETUP_TOKEN_WAS_GENERATED:
        logger.warning(
                "First-run setup token was: %s",
                SETUP_TOKEN,
                )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
            title="DaemonHunter",
            description="Self-Hosted homelab monitoring dashboard",
            version="0.1.0",
            lifespan=lifespan,
            )
    app.include_router(auth_router)
    app.include_router(devices_router)
    app.include_router(admin_users_router)
    app.include_router(admin_devices_router)

    @app.get(
            "/"
            )
    def read_root():
        return {"daemonhunter": "landing page"}

    @app.get(
            "/api/v1/health",
            response_model=HealthResponse,
            )
    def health():
        return HealthResponse(
                status="ok",
                service="daemonhunter",
                )

    @app.middleware("http")
    async def no_store_private_api(
            request: Request,
            call_text: RequestResponseEndpoint,
            ) -> Response:
        response = await call_text(request)

        if request.url.path.startswith(
                ("/api/v1/auth/", "/api/v1/admin/")
                ):
            response.headers["Cache-Control"] = "no-store"

        return response

    return app


app = create_app()
