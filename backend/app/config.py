"""Application configuration via pydantic-settings."""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    APP_NAME: str = "DOGFOOD API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/dogfood"
    DATABASE_ECHO: bool = False

    # Auth
    JWT_SECRET_KEY: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    # Rate Limiting
    REDIS_URL: Optional[str] = None  # None = use in-memory fallback
    RATE_LIMIT_VOTES_PER_MINUTE: int = 10
    RATE_LIMIT_COMMENTS_PER_MINUTE: int = 10
    RATE_LIMIT_ENABLED: bool = True
    # Brute-force / account-flood protection. Only *failed* sign-ins count, so legitimate users are never throttled.
    LOGIN_MAX_FAILURES: int = 10            # per IP + email, per 5 minutes
    LOGIN_MAX_FAILURES_PER_IP: int = 50     # per IP (many different emails), per 5 minutes
    RATE_LIMIT_SIGNUPS_PER_MINUTE: int = 100  # per IP; generous because a hackathon venue shares one NAT address
    # Behind the Next.js proxy every request shares the proxy's IP; trust X-Forwarded-For's first hop.
    TRUST_PROXY_HEADERS: bool = True
    # Max votes from one network per event, as a multiple of votes_per_voter (NAT / campus tolerance)
    VOTES_PER_IP_MULTIPLIER: int = 10

    # Ed25519 key for certificates is derived from this secret (falls back to JWT_SECRET_KEY). Rotate = new key id.
    CERT_SIGNING_KEY: Optional[str] = None

    # Webhooks (T4)
    WEBHOOK_WORKER_ENABLED: bool = True
    # Deliveries to loopback / private-network addresses are refused unless this is on (SSRF protection).
    # Link-local and cloud-metadata addresses are ALWAYS refused. `docker compose` turns it on for local demos.
    WEBHOOK_ALLOW_PRIVATE_TARGETS: bool = False
    WEBHOOK_TIMEOUT_SECONDS: float = 5.0
    WEBHOOK_MAX_ATTEMPTS: int = 6
    WEBHOOK_BACKOFF_SECONDS: str = "5,30,120,600,3600"  # wait before attempt 2, 3, ...
    WEBHOOK_DISABLE_AFTER_DEAD: int = 10  # consecutive dead deliveries before an endpoint is switched off
    WEBHOOK_MAX_PER_OWNER: int = 20

    # Public URLs used in embed links / snippets (override in production)
    PUBLIC_WEB_URL: str = "http://localhost:3000"
    PUBLIC_API_URL: str = "http://localhost:8000"

    # Seed
    SEED_ON_STARTUP: bool = True
    # DOGFOOD fixtures.json loaded at boot (skipped if the file does not exist)
    FIXTURES_PATH: str = "/data/fixtures.json"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
