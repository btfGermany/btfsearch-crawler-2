"""Main FastAPI application."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from prometheus_client import Counter, Histogram, generate_latest
from pydantic import BaseModel

from app.api import SearchRequest, SearchResponse, AutocompleteResponse, ReportRequest
from app.config import settings
from app.compliance.takedown import TakedownQueue
from app.search.autocomplete import AutocompleteIndex
from app.search.index import SearchIndex
from app.search.rank import SearchRanker
from app.storage.db import Database
from app.utils.logging import setup_logging

# Setup logging
logger = setup_logging()

# Metrics
search_requests = Counter("search_requests_total", "Total search requests")
search_duration = Histogram("search_duration_seconds", "Search request duration")
autocomplete_requests = Counter("autocomplete_requests_total", "Total autocomplete requests")

# Global instances
db: Optional[Database] = None
search_index: Optional[SearchIndex] = None
search_ranker: Optional[SearchRanker] = None
autocomplete_index: Optional[AutocompleteIndex] = None
takedown_queue: Optional[TakedownQueue] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global db, search_index, search_ranker, autocomplete_index, takedown_queue
    
    logger.info("Starting application", version=settings.APP_VERSION)
    
    # Initialize database
    db = Database(settings.DATABASE_PATH)
    await db.initialize()
    
    # Initialize search components
    search_index = SearchIndex(db)
    await search_index.initialize()
    
    search_ranker = SearchRanker(
        db=db,
        enable_semantic=settings.EMBEDDINGS_ENABLED,
        model_name=settings.EMBEDDING_MODEL
    )
    await search_ranker.initialize()
    
    # Initialize autocomplete
    autocomplete_index = AutocompleteIndex()
    autocomplete_path = Path(settings.DATABASE_PATH).parent / "autocomplete.json"
    if autocomplete_path.exists():
        await autocomplete_index.load(str(autocomplete_path))
    
    # Initialize takedown queue
    takedown_queue = TakedownQueue(db)
    await takedown_queue.initialize()
    
    yield
    
    # Cleanup
    logger.info("Shutting down application")
    if db:
        await db.close()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# CORS middleware
if settings.CORS_ENABLED:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# Rate limiting middleware
class RateLimitMiddleware:
    """Simple rate limiting middleware."""
    
    def __init__(self, app, requests_per_minute: int = 60):
        self.app = app
        self.requests_per_minute = requests_per_minute
        self.requests = {}
        self.lock = asyncio.Lock()
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            client_ip = self._get_client_ip(scope)
            
            async with self.lock:
                current_time = asyncio.get_event_loop().time()
                if client_ip not in self.requests:
                    self.requests[client_ip] = []
                
                # Clean old requests
                self.requests[client_ip] = [
                    t for t in self.requests[client_ip] 
                    if current_time - t < 60
                ]
                
                if len(self.requests[client_ip]) >= self.requests_per_minute:
                    response = Response(
                        content="Rate limit exceeded",
                        status_code=429
                    )
                    await response(scope, receive, send)
                    return
                
                self.requests[client_ip].append(current_time)
        
        await self.app(scope, receive, send)
    
    def _get_client_ip(self, scope) -> str:
        """Extract client IP with anonymization."""
        headers = dict(scope.get("headers", []))
        
        # Check X-Forwarded-For
        if b"x-forwarded-for" in headers:
            ip = headers[b"x-forwarded-for"].decode().split(",")[0].strip()
        else:
            ip = scope.get("client", ["0.0.0.0"])[0]
        
        # Anonymize if enabled
        if settings.IP_ANONYMIZATION_ENABLED:
            parts = ip.split(".")
            if len(parts) == 4:
                parts[3] = "0"
                ip = ".".join(parts)
        
        return ip


if settings.RATE_LIMIT_ENABLED:
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=settings.RATE_LIMIT_REQUESTS_PER_MINUTE
    )


@app.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, max_length=500),
    page: int = Query(1, ge=1),
    lang: Optional[str] = None,
    site: Optional[str] = None
):
    """Search for documents."""
    search_requests.inc()
    
    with search_duration.time():
        if not search_index or not search_ranker:
            raise HTTPException(status_code=503, detail="Search service unavailable")
        
        try:
            results = await search_ranker.search(
                query=q,
                page=page,
                page_size=settings.DEFAULT_PAGE_SIZE,
                lang=lang,
                site=site
            )
            
            return SearchResponse(
                query=q,
                results=results["results"],
                total=results["total"],
                page=page,
                page_size=settings.DEFAULT_PAGE_SIZE,
                took_ms=results.get("took_ms", 0)
            )
        except Exception as e:
            logger.error("Search error", error=str(e), query=q)
            raise HTTPException(status_code=500, detail="Search error")


@app.get("/autocomplete", response_model=AutocompleteResponse)
async def autocomplete(
    q: str = Query(..., min_length=1, max_length=100)
):
    """Get autocomplete suggestions."""
    autocomplete_requests.inc()
    
    if not autocomplete_index:
        return AutocompleteResponse(query=q, suggestions=[])
    
    try:
        suggestions = await autocomplete_index.suggest(q, limit=10)
        return AutocompleteResponse(query=q, suggestions=suggestions)
    except Exception as e:
        logger.error("Autocomplete error", error=str(e), query=q)
        return AutocompleteResponse(query=q, suggestions=[])


@app.post("/report")
async def report_content(request: ReportRequest):
    """Submit a takedown request."""
    if not takedown_queue:
        raise HTTPException(status_code=503, detail="Report service unavailable")
    
    try:
        request_id = await takedown_queue.submit(
            url=request.url,
            email=request.email,
            reason=request.reason
        )
        
        return {
            "status": "submitted",
            "request_id": request_id,
            "message": "Your report has been submitted and will be reviewed."
        }
    except Exception as e:
        logger.error("Report submission error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to submit report")


@app.get("/status")
async def status():
    """Get service status and statistics."""
    if not db or not search_index:
        return {"status": "initializing"}
    
    try:
        stats = await search_index.get_stats()
        return {
            "status": "healthy",
            "version": settings.APP_VERSION,
            "index": {
                "documents": stats.get("total_documents", 0),
                "size_mb": stats.get("size_mb", 0),
                "last_updated": stats.get("last_updated")
            },
            "cache": {
                "enabled": settings.CACHE_ENABLED,
                "redis_enabled": settings.REDIS_ENABLED
            },
            "embeddings": {
                "enabled": settings.EMBEDDINGS_ENABLED,
                "model": settings.EMBEDDING_MODEL if settings.EMBEDDINGS_ENABLED else None
            }
        }
    except Exception as e:
        logger.error("Status check error", error=str(e))
        return {"status": "error", "message": str(e)}


@app.get("/impressum", response_class=HTMLResponse)
async def impressum():
    """Legal notice (Impressum)."""
    impressum_path = Path(__file__).parent / "legal" / "impressum.html"
    if impressum_path.exists():
        content = impressum_path.read_text()
        # Replace placeholders
        content = content.replace("{{OPERATOR_NAME}}", settings.OPERATOR_NAME)
        content = content.replace("{{OPERATOR_ADDRESS}}", settings.OPERATOR_ADDRESS)
        content = content.replace("{{OPERATOR_EMAIL}}", settings.OPERATOR_EMAIL)
        return HTMLResponse(content=content)
    
    return HTMLResponse(content="<h1>Impressum</h1><p>Coming soon</p>")


@app.get("/datenschutz", response_class=HTMLResponse)
async def datenschutz():
    """Privacy policy (Datenschutzerklärung)."""
    datenschutz_path = Path(__file__).parent / "legal" / "datenschutz.html"
    if datenschutz_path.exists():
        content = datenschutz_path.read_text()
        # Replace placeholders
        content = content.replace("{{OPERATOR_NAME}}", settings.OPERATOR_NAME)
        content = content.replace("{{PRIVACY_EMAIL}}", settings.PRIVACY_EMAIL)
        content = content.replace("{{LOG_RETENTION_DAYS}}", str(settings.LOG_RETENTION_DAYS))
        return HTMLResponse(content=content)
    
    return HTMLResponse(content="<h1>Datenschutzerklärung</h1><p>Coming soon</p>")


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    """Robots.txt for this search engine."""
    content = f"""User-agent: *
Disallow: /api/
Disallow: /admin/
Disallow: /report
Allow: /search
Allow: /impressum
Allow: /datenschutz
Crawl-delay: 1

User-agent: {settings.CRAWLER_USER_AGENT.split('/')[0]}
Disallow:

Sitemap: https://example.com/sitemap.xml
"""
    return PlainTextResponse(content=content)


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus metrics endpoint."""
    if not settings.METRICS_ENABLED:
        raise HTTPException(status_code=404, detail="Metrics not enabled")
    
    return PlainTextResponse(generate_latest())


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "endpoints": {
            "search": "/search",
            "autocomplete": "/autocomplete",
            "status": "/status",
            "impressum": "/impressum",
            "datenschutz": "/datenschutz",
            "robots": "/robots.txt"
        }
    }