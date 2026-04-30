from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from contextlib import asynccontextmanager

from app.core.config import settings
from app.api.api import api_router

os.makedirs("uploads", exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create all DB tables on startup (dev convenience, use Alembic in production)
    from app.core.database import engine, Base
    import app.models  # noqa: ensure all models are registered
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Seed default categories
    from app.core.database import AsyncSessionLocal
    from app.crud.category import seed_default_categories
    from app.crud.user import seed_admin_user
    async with AsyncSessionLocal() as session:
        await seed_default_categories(session)
        await seed_admin_user(session)
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# Set all CORS enabled origins
# NOTE: allow_credentials=True requires explicit origins — wildcards are forbidden by the CORS spec
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.admin.api import admin_router

app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(admin_router, prefix="/admin")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

@app.get("/health")
async def health_check():
    return {"status": "ok", "version": settings.VERSION}

