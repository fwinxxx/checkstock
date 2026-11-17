from hashlib import sha256
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db import SessionLocal
from app.queries import snapshot
from app.schemas import AnyCommand
from app.service import DomainError, execute

STATIC = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    # Change asset URLs with their content, so cached files cannot mix UI releases.
    index_html = (STATIC / "index.html").read_text(encoding="utf-8")
    for name in ("styles.css", "app.js"):
        version = sha256((STATIC / name).read_bytes()).hexdigest()[:12]
        index_html = index_html.replace(f"/static/{name}", f"/static/{name}?v={version}")
    app = FastAPI(
        title="CheckStock", version="1.0.0", description="Остатки, резервы и движения товара"
    )

    @app.exception_handler(DomainError)
    async def domain_error(_request, exc):
        return JSONResponse({"error": exc.error}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, exc):
        return JSONResponse(
            {
                "error": {
                    "code": "validation_error",
                    "message": (
                        "Проверьте поля: количество — целое число от 1 до 1 000 000, "
                        "названия не пустые."
                    ),
                    "fields": [".".join(map(str, e["loc"])) for e in exc.errors()],
                }
            },
            status_code=422,
        )

    @app.exception_handler(OperationalError)
    async def database_unavailable(_request, _exc):
        return JSONResponse(
            {
                "error": {
                    "code": "database_unavailable",
                    "message": (
                        "База данных временно недоступна. Повторите запрос с тем же request_id."
                    ),
                }
            },
            status_code=503,
        )

    @app.get("/health", tags=["System"])
    def health():
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get("/api/state", tags=["Inventory"])
    def read_state():
        with SessionLocal.begin() as session:
            return snapshot(session)

    @app.post("/api/commands", tags=["Inventory"])
    def run_command(command: AnyCommand):
        with SessionLocal.begin() as session:
            response, replayed = execute(session, command)
        return JSONResponse(response, headers={"Idempotency-Replayed": str(replayed).lower()})

    @app.get("/", include_in_schema=False)
    def index():
        return HTMLResponse(index_html, headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
