"""Application configuration."""

from typing import List, Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings from environment variables."""
    
    # Application
    APP_NAME: str = "SearchEngine"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_RETENTION_DAYS: int = 30
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 4
    RELOAD: bool = False
    
    # Database
    DATABASE_PATH: str = "./data/search.db"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_TIMEOUT: int = 30
    
    # Search
    MAX_RESULTS_PER_PAGE: int = 20
    DEFAULT_PAGE_SIZE: int = 10
    MAX_SNIPPET_LENGTH: int = 200
    EMBEDDINGS_ENABLED: bool = False
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    FAISS_INDEX_PATH: str = "./data/faiss.index"
    
    # Cache
    CACHE_ENABLED: bool = True
    CACHE_TTL_SECONDS: int = 3600
    CACHE_MAX_SIZE: int = 1000
    REDIS_URL: Optional[str] = None
    REDIS_ENABLED: bool = False
    
    # Crawler
    CRAWLER_USER_AGENT: str = "SearchEngineBot/1.0 (+https://example.com/bot)"
    CRAWLER_CONCURRENT_REQUESTS: int = 16
    CRAWLER_CONCURRENT_REQUESTS_PER_DOMAIN: int = 2
    CRAWLER_DOWNLOAD_DELAY: float = 1.0
    CRAWLER_RANDOMIZE_DOWNLOAD_DELAY: bool = True
    CRAWLER_AUTOTHROTTLE_ENABLED: bool = True
    CRAWLER_AUTOTHROTTLE_START_DELAY: float = 1.0
    CRAWLER_AUTOTHROTTLE_MAX_DELAY: float = 10.0
    CRAWLER_AUTOTHROTTLE_TARGET_CONCURRENCY: float = 2.0
    CRAWLER_MAX_DEPTH: int = 3
    CRAWLER_TIMEOUT: int = 30
    CRAWLER_RETRY_TIMES: int = 3
    
    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 60
    RATE_LIMIT_BURST_SIZE: int = 10
    
    # Compliance
    ALLOWLIST_PATH: str = "./config/allowlist.txt"
    BLOCKLIST_PATH: str = "./config/blocklist.txt"
    ROBOTS_TXT_OBEY: bool = True
    RESPECT_CRAWL_DELAY: bool = True
    MAX_CRAWL_DELAY: int = 60
    
    # Legal/GDPR
    OPERATOR_NAME: str = "Example Company"
    OPERATOR_ADDRESS: str = "Example Street 1, 12345 City"
    OPERATOR_EMAIL: str = "legal@example.com"
    PRIVACY_EMAIL: str = "privacy@example.com"
    TAKEDOWN_EMAIL: str = "takedown@example.com"
    IMPRESSUM_URL: str = "/impressum"
    DATENSCHUTZ_URL: str = "/datenschutz"
    
    # Security
    CORS_ENABLED: bool = True
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "https://example.com"]
    SECRET_KEY: str = "change-this-to-a-random-secret-key-in-production"
    IP_ANONYMIZATION_ENABLED: bool = True
    IP_ANONYMIZATION_MASK: str = "255.255.255.0"
    
    # Monitoring
    METRICS_ENABLED: bool = True
    METRICS_PATH: str = "/metrics"
    HEALTH_CHECK_PATH: str = "/status"
    
    # Export
    EXPORT_PATH: str = "./exports"
    MAX_EXPORT_SIZE_MB: int = 1000
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()