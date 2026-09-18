from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from .database import Base, engine, SessionLocal
from .config import settings
from . import auth_models
from .routers import auth, orders, master, dashboard, modules, revisions, po_intake
from .services.seed import seed


@asynccontextmanager
async def lifespan(app):
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        if settings.app_env == "production":
            cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
            expected = ScriptDirectory.from_config(cfg).get_current_head()
            actual = MigrationContext.configure(connection).get_current_revision()
            if actual != expected:
                raise RuntimeError("Database schema is not current. Run alembic upgrade head before startup.")
        else:
            Base.metadata.create_all(bind=connection)
            connection.commit()
    with SessionLocal() as db:
        if settings.seed_demo:
            seed(db)
        if settings.app_env == "production":
            from .models import User
            from .auth import verify_password
            if any(verify_password("demo123", u.password_hash) for u in db.query(User).filter(User.is_active.is_(True)).all()):
                raise RuntimeError("An active account still uses the legacy demo password. Reset it using python -m app.bootstrap reset-password.")
    yield


_is_prod = settings.app_env == "production"
app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan,
              docs_url=None if _is_prod else "/docs",
              redoc_url=None if _is_prod else "/redoc",
              # docs_url=None only hides the UI; the schema route stays mounted and
              # would still publish every endpoint. Disable it explicitly in prod.
              openapi_url=None if _is_prod else "/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


for router in (auth.router, orders.router, master.router, dashboard.router, modules.router, revisions.router, po_intake.router):
    app.include_router(router, prefix="/api")


@app.get("/api/health")
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}


# --- Serve frontend (single-container build) ---
# If a built SPA is present at frontend_dist/, serve it with SPA fallback.
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

_frontend_dist = Path(__file__).resolve().parents[1] / "frontend_dist"
if _frontend_dist.is_dir():
    _assets = _frontend_dist / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

    # Paths the SPA must never shadow: API namespace plus the OpenAPI schema and
    # docs UIs, which FastAPI disables in production. Without this guard the
    # catch-all below would answer them with index.html (or leak the schema).
    _RESERVED = {"openapi.json", "docs", "redoc", "docs/oauth2-redirect"}

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        from fastapi import HTTPException
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404)
        if settings.app_env == "production" and full_path in _RESERVED:
            raise HTTPException(status_code=404)
        candidate = (_frontend_dist / full_path).resolve()
        if full_path and candidate.is_file() and _frontend_dist in candidate.parents:
            return FileResponse(str(candidate))
        return FileResponse(str(_frontend_dist / "index.html"))
