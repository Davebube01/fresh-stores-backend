from typing import Any
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_SECRET_KEYS = {
    "super-secret-key-change-in-production",
    "changeme",
    "secret",
}

# Passwords that must never guard a real admin account.
INSECURE_ADMIN_PASSWORDS = {"adminpassword123", "admin", "password", "password123", "changeme"}

class Settings(BaseSettings):
    PROJECT_NAME: str = "Goat Meat Store API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    SECRET_KEY: str = "super-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    # Access tokens are short-lived and held in memory by the frontend; a
    # longer-lived refresh token (httpOnly cookie, rotated on use) mints new
    # ones. See app/services/auth_service.py.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 30       # customer "keep me signed in"
    REFRESH_SESSION_HOURS: int = 24    # customer without it (cookie is also session-only)
    ADMIN_SESSION_HOURS: int = 12      # admin: no remember-me, fixed working-day cap
    VERIFY_EMAIL_HOURS: int = 48

    # Online-payment orders still unpaid after this long are cancelled (and
    # their stock released). Cash-on-delivery orders are never auto-cancelled.
    ORDER_PAYMENT_WINDOW_MINUTES: int = 30
    # ...counted from the last payment attempt, but never longer than this in total.
    ORDER_MAX_PAYMENT_HOLD_MINUTES: int = 120

    # Where the storefront lives — used to build links in emails.
    FRONTEND_URL: str = "http://localhost:3000"

    # Refresh-token cookie. SameSite=Lax needs the frontend and API on the
    # same *site* (e.g. www.shop.com + api.shop.com); "localhost" and
    # "127.0.0.1" count as different sites, so use one consistently in dev.
    COOKIE_SECURE: bool | None = None   # None -> True in production, else False
    COOKIE_SAMESITE: str = "lax"
    COOKIE_DOMAIN: str | None = None
    
    DATABASE_URL: str = "sqlite+aiosqlite:///./sql_app.db"
    # Explicit origins (no "*"): cookies are sent with credentials, which the
    # CORS spec forbids combining with a wildcard.
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:3001"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Any) -> list[str] | str:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        return v
    
    # First owner account, created at startup only while no admin exists.
    ADMIN_EMAIL: str | None = None
    ADMIN_PASSWORD: str | None = None
    ADMIN_NAME: str = "Store Owner"

    PAYSTACK_SECRET_KEY: str | None = None
    PAYSTACK_PUBLIC_KEY: str | None = None

    CLOUDINARY_CLOUD_NAME: str | None = None
    CLOUDINARY_API_KEY: str | None = None
    CLOUDINARY_API_SECRET: str | None = None

    ENV: str = "development"
    
    @property
    def cookie_secure(self) -> bool:
        return self.COOKIE_SECURE if self.COOKIE_SECURE is not None else self.ENV == "production"

    @property
    def async_database_url(self) -> str:
        """
        DATABASE_URL as the asyncpg driver needs it, so a provider's URL can be
        pasted as-is: Render's postgres:// scheme, and Neon/Supabase-style
        `?sslmode=require&channel_binding=require`, which asyncpg rejects
        (it takes `ssl=` instead and negotiates channel binding itself).
        """
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if not url.startswith("postgresql+asyncpg://") or "?" not in url:
            return url

        base, query = url.split("?", 1)
        params = []
        for pair in query.split("&"):
            key, _, value = pair.partition("=")
            if key == "channel_binding":
                continue
            if key == "sslmode":
                # disable/allow/prefer/require/verify-ca/verify-full all mean the same to asyncpg's ssl=.
                key = "ssl"
            params.append(f"{key}={value}" if _ else key)
        return f"{base}?{'&'.join(params)}" if params else base

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @model_validator(mode="after")
    def _validate_production_secret_key(self) -> "Settings":
        if self.ENV == "production" and (
            self.SECRET_KEY in INSECURE_DEFAULT_SECRET_KEYS or len(self.SECRET_KEY) < 32
        ):
            raise ValueError(
                "SECRET_KEY must be set to a strong, unique value (32+ characters) when ENV=production. "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        if self.ENV == "production" and self.ADMIN_PASSWORD and (
            len(self.ADMIN_PASSWORD) < 12 or self.ADMIN_PASSWORD.lower() in INSECURE_ADMIN_PASSWORDS
        ):
            raise ValueError("ADMIN_PASSWORD must be a strong password (12+ characters) when ENV=production.")
        if self.ENV == "production" and "*" in self.ALLOWED_ORIGINS:
            raise ValueError("ALLOWED_ORIGINS must list explicit origins (not '*') when ENV=production.")
        return self

settings = Settings()
