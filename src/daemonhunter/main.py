from fastapi import FastAPI

from daemonhunter.routers.admin_users import router as admin_users_router
from daemonhunter.routers.admin_devices import router as admin_devices_router
from daemonhunter.routers.auth import router as auth_router
from daemonhunter.routers.devices import  router as devices_router
from daemonhunter.schemas import HealthResponse


def create_app() -> FastAPI:
    app = FastAPI(
            title="DaemonHunter",
            description="Self-Hosted homelab monitoring dashboard",
            version="0.1.0"
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
    return app


app = create_app()
