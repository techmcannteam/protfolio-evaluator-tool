import hashlib
import hmac
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from .config import DISCLAIMER, Settings
from .follow_up_boss import pushToFUB
from .models import CMARequest, EvaluateRequest
from .providers.attom import Attom
from .providers.base import Transport
from .providers.rentcast import RentCast
from .repository import Repository
from .service import Evaluator


def create_app(settings=None, repository=None, providers=None):
    settings = settings or Settings()
    repository = repository or Repository(settings)
    if settings.vercel and settings.ip_salt == "local-development-only":
        raise RuntimeError("IP_HASH_SALT must be configured on Vercel.")
    transport = Transport(repository, settings)
    providers = (
        providers
        if providers is not None
        else [RentCast(transport, settings.rentcast_key)]
        + ([Attom(transport, settings.attom_key)] if settings.enable_attom else [])
    )
    evaluator = Evaluator(repository, providers, settings)

    @asynccontextmanager
    async def lifespan(app):
        repository.initialize()
        yield

    app = FastAPI(
        title="McCann Portfolio Evaluator",
        version="1.0.0",
        description=DISCLAIMER,
        lifespan=lifespan,
    )
    app.state.repository = repository
    # Same-origin by default; configure an explicit frontend allowlist when needed.
    import os

    origins = [
        x.strip() for x in os.getenv("ALLOWED_ORIGINS", "").split(",") if x.strip()
    ]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )

    @app.middleware("http")
    async def headers(request, call_next):
        try:
            size = int(request.headers.get("content-length", "0") or 0)
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length."}, 400)
        if size > 32768:
            return JSONResponse({"detail": "Request body too large."}, 413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not echo submitted contact info or arbitrary provider credentials.
        return JSONResponse(
            {
                "detail": [
                    {"loc": e["loc"], "msg": e["msg"], "type": e["type"]}
                    for e in exc.errors()
                ]
            },
            422,
        )

    def limit(request, category):
        # Only Vercel's overwritten header is trusted; arbitrary X-Forwarded-For is ignored.
        ip = (
            request.headers.get("x-vercel-forwarded-for", "").split(",")[0].strip()
            if settings.vercel
            else ""
        )
        ip = ip or (request.client.host if request.client else "unknown")
        fingerprint = hmac.new(
            settings.ip_salt.encode(), ip.encode(), hashlib.sha256
        ).hexdigest()
        now = time.time()
        if not repository.consume(
            f"ip:{category}:{fingerprint}:{int(now // 3600)}",
            settings.rate_limit if category == "evaluate" else 5,
        ):
            raise HTTPException(
                429,
                "Too many requests. Please try again later.",
                headers={"Retry-After": str(3600 - int(now % 3600))},
            )

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/docs")

    @app.get("/health")
    def health():
        repository.agents()
        return {
            "status": "ok",
            "service": "mccann-portfolio-evaluator",
            "storage": "postgres" if repository.postgres else "sqlite",
            "fub": "simulated",
        }

    @app.get("/api/agents")
    def agents():
        return {"agents": repository.agents()}

    @app.get("/api/config")
    def config():
        return {
            "assumptions": settings.defaults.model_dump(),
            "assumptions_status": "Placeholders; pending confirmation with Ben.",
            "max_addresses": 10,
            "cache_days": 30,
            "disclaimer": DISCLAIMER,
        }

    @app.post("/api/evaluate")
    def evaluate(
        body: EvaluateRequest,
        request: Request,
        agent: str | None = Query(None, pattern=r"^[a-z0-9-]{1,60}$"),
    ):
        limit(request, "evaluate")
        attribution = agent or body.agent
        if attribution and not repository.agent_exists(attribution):
            raise HTTPException(404, "Agent not found.")
        return evaluator.evaluate(body, attribution)

    @app.post("/api/cma-requests", status_code=201)
    def cma(body: CMARequest, request: Request):
        limit(request, "cma")
        if not repository.agent_exists(body.agent_slug):
            raise HTTPException(404, "Agent not found.")
        estimate = repository.estimate(body.estimate_id)
        if not estimate:
            raise HTTPException(404, "Estimate not found. Evaluate the property first.")
        if estimate["agent_slug"] and estimate["agent_slug"] != body.agent_slug:
            raise HTTPException(409, "Agent does not match the estimate link.")
        # The stored server estimate is authoritative; the client cannot submit a forged value.
        status = (
            pushToFUB(body.model_dump(mode="json"))
            if settings.enable_fub
            else {"status": "simulated", "sent": False}
        )
        identifier = repository.save_cma(body, estimate, status["status"])
        return {
            "id": identifier,
            "status": "saved",
            "fub": status,
            "disclaimer": DISCLAIMER,
        }

    return app


app = create_app()
