from fastapi import FastAPI

from daemonhunter.schemas import HealthResponse
from daemonhunter.routers.admin_devices import router as admin_devices_router


def create_app() -> FastAPI:
    app = FastAPI(
            title="DaemonHunter",
            description="Self-Hosted homelab monitoring dashboard",
            version="0.1.0"
            )
    app.include_router(admin_devices_router)

    @app.get("/")
    def read_root():
        return {"daemonhunter": "landing page"}

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health():
        return HealthResponse(
                status="ok",
                service="daemonhunter",
                )

    return app


app = create_app()
