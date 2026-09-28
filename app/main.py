from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.limiter import limiter
from app.api.api import api_router

os.makedirs("uploads", exist_ok=True)

async def _expire_unpaid_orders_forever():
    """Every few minutes, cancel unpaid online orders past the payment window and release their stock."""
    from app.core.database import AsyncSessionLocal
    from app.crud.order import expire_stale_unpaid_orders

    while True:
        try:
            async with AsyncSessionLocal() as session:
                await expire_stale_unpaid_orders(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger("orders").exception("Unpaid-order expiry sweep failed")
        await asyncio.sleep(300)


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
        # Seed/load delivery zones for checkout's fee lookup.
        from app.core.delivery_zones import load_delivery_zones
        await load_delivery_zones(session)

    sweeper = asyncio.create_task(_expire_unpaid_orders_forever())
    yield
    sweeper.cancel()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

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

