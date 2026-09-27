"""DOGFOOD Hackathon Platform API."""

from contextlib import asynccontextmanager

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.middleware import RequestGuardMiddleware
from app.schemas.api import HealthOut


_PUBLIC_DEFAULT_SECRETS = {"your-secret-key-change-in-production", "your-super-secret-key-change-in-production", "test-secret-key"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    if settings.JWT_SECRET_KEY in _PUBLIC_DEFAULT_SECRETS:
        logging.getLogger("uvicorn.error").warning(
            "JWT_SECRET_KEY is a value published in this repository: anyone can mint valid tokens (including the "
            "long-lived checker tokens). Fine for a local demo; set your own secret before exposing this anywhere real."
        )
    await init_db()
    if settings.SEED_ON_STARTUP:
        from scripts.seed import seed_data
        await seed_data()
    stop, worker = asyncio.Event(), None
    if settings.WEBHOOK_WORKER_ENABLED:
        from app.services.webhook_service import worker_loop

        worker = asyncio.create_task(worker_loop(stop))
    yield
    stop.set()
    if worker is not None:
        await worker


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Backend API for DOGFOOD Hackathon Submission & Judging Platform",
    lifespan=lifespan,
    # readable, stable operationIds (e.g. `cast_vote`) instead of `vote_for_submission_submissions__id__vote_post`
    generate_unique_id_function=lambda route: route.name,
    # /docs is served below from vendored assets: the default page loads Swagger UI from a CDN and would
    # be blank on a laptop with the network off. (/redoc also needs a CDN + web fonts, so it is disabled.)
    docs_url=None,
    redoc_url=None,
)

# Request guard (NUL bytes, body size caps): see app/middleware.py
app.add_middleware(RequestGuardMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/docs", include_in_schema=False)
async def swagger_ui():
    """Interactive API docs (Swagger UI, self-hosted so it works offline)."""
    # relative URLs so the page also works behind the web proxy at /api/docs
    return get_swagger_ui_html(
        openapi_url="openapi.json",
        title=f"{settings.APP_NAME}: docs",
        swagger_js_url="static/swagger/swagger-ui-bundle.js",
        swagger_css_url="static/swagger/swagger-ui.css",
        swagger_favicon_url="static/swagger/favicon.png",
        swagger_ui_parameters={"persistAuthorization": True, "tryItOutEnabled": True, "docExpansion": "list"},
    )


@app.middleware("http")
async def open_cors_for_embed(request, call_next):
    """The embed endpoints are public and read-only, so they answer any origin (no credentials).

    Registered after CORSMiddleware => outermost, so it also answers preflights that the
    origin-restricted global CORS policy would otherwise reject with 400.
    """
    if not request.url.path.startswith("/embed"):
        return await call_next(request)
    headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS"}
    if request.method == "OPTIONS":
        return Response(status_code=204, headers={**headers, "Access-Control-Allow-Headers": "*", "Access-Control-Max-Age": "86400"})
    response = await call_next(request)
    for k, v in headers.items():
        response.headers[k] = v
    if "access-control-allow-credentials" in response.headers:
        del response.headers["access-control-allow-credentials"]
    return response


@app.get("/health", tags=["system"], response_model=HealthOut)
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": settings.APP_VERSION}


from app.api import auth, events, teams, submissions, judging, voting, admin, embed, dump, certificates, webhooks

app.include_router(auth.router)
app.include_router(events.router)
app.include_router(teams.router)
app.include_router(submissions.router)
app.include_router(judging.router)
app.include_router(voting.router)
app.include_router(admin.router)
app.include_router(embed.router)
app.include_router(dump.router)
app.include_router(certificates.router)
app.include_router(webhooks.router)

from app.openapi_meta import build_openapi  # noqa: E402

app.openapi = lambda: build_openapi(app)  # documented, complete schema (see openapi_meta.py)
