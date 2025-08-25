"""Scrapy crawler settings."""

import os
from pathlib import Path

from app.config import settings

# Scrapy settings
BOT_NAME = 'searchengine'

SPIDER_MODULES = ['app.crawler.spiders']
NEWSPIDER_MODULE = 'app.crawler.spiders'

# User agent
USER_AGENT = settings.CRAWLER_USER_AGENT

# Obey robots.txt rules
ROBOTSTXT_OBEY = settings.ROBOTS_TXT_OBEY

# Configure maximum concurrent requests
CONCURRENT_REQUESTS = settings.CRAWLER_CONCURRENT_REQUESTS
CONCURRENT_REQUESTS_PER_DOMAIN = settings.CRAWLER_CONCURRENT_REQUESTS_PER_DOMAIN

# Configure delays
DOWNLOAD_DELAY = settings.CRAWLER_DOWNLOAD_DELAY
RANDOMIZE_DOWNLOAD_DELAY = settings.CRAWLER_RANDOMIZE_DOWNLOAD_DELAY

# AutoThrottle extension
AUTOTHROTTLE_ENABLED = settings.CRAWLER_AUTOTHROTTLE_ENABLED
AUTOTHROTTLE_START_DELAY = settings.CRAWLER_AUTOTHROTTLE_START_DELAY
AUTOTHROTTLE_MAX_DELAY = settings.CRAWLER_AUTOTHROTTLE_MAX_DELAY
AUTOTHROTTLE_TARGET_CONCURRENCY = settings.CRAWLER_AUTOTHROTTLE_TARGET_CONCURRENCY
AUTOTHROTTLE_DEBUG = False

# Configure timeouts
DOWNLOAD_TIMEOUT = settings.CRAWLER_TIMEOUT

# Retry configuration
RETRY_ENABLED = True
RETRY_TIMES = settings.CRAWLER_RETRY_TIMES
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

# Depth limit
DEPTH_LIMIT = settings.CRAWLER_MAX_DEPTH

# Configure pipelines
ITEM_PIPELINES = {
    'app.crawler.pipelines.ValidationPipeline': 100,
    'app.crawler.pipelines.DuplicatesPipeline': 200,
    'app.crawler.pipelines.ContentExtractionPipeline': 300,
    'app.crawler.pipelines.LanguageDetectionPipeline': 400,
    'app.crawler.pipelines.DatabasePipeline': 500,
}

# Configure middlewares
DOWNLOADER_MIDDLEWARES = {
    'app.crawler.middlewares.RobotsMiddleware': 100,
    'app.crawler.middlewares.AllowlistMiddleware': 200,
    'app.crawler.middlewares.RateLimitMiddleware': 300,
    'app.crawler.middlewares.UserAgentMiddleware': 400,
    'scrapy.downloadermiddlewares.retry.RetryMiddleware': 500,
}

# Configure extensions
EXTENSIONS = {
    'scrapy.extensions.telnet.TelnetConsole': None,
}

# Memory usage
MEMUSAGE_ENABLED = True
MEMUSAGE_LIMIT_MB = 512
MEMUSAGE_WARNING_MB = 256

# DNS
DNSCACHE_ENABLED = True
DNSCACHE_SIZE = 10000
DNS_TIMEOUT = 60

# HTTP Cache
HTTPCACHE_ENABLED = False
HTTPCACHE_EXPIRATION_SECS = 3600
HTTPCACHE_DIR = 'httpcache'

# Cookies
COOKIES_ENABLED = False

# Telnet Console
TELNETCONSOLE_ENABLED = False

# Default headers
DEFAULT_REQUEST_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en,de;q=0.9,fr;q=0.8,es;q=0.7',
}

# Stats
STATS_CLASS = 'scrapy.statscollectors.MemoryStatsCollector'

# Log settings
LOG_ENABLED = True
LOG_ENCODING = 'utf-8'
LOG_LEVEL = settings.LOG_LEVEL
LOG_FORMAT = '%(levelname)s %(asctime)s [%(name)s] %(message)s'

# Feed exports
FEED_EXPORT_ENCODING = 'utf-8'

# Redirect settings
REDIRECT_ENABLED = True
REDIRECT_MAX_TIMES = 5

# Referer
REFERER_ENABLED = True

# URL length limit
URLLENGTH_LIMIT = 2083

# Response size limit (10MB)
DOWNLOAD_MAXSIZE = 10485760

# Compression
COMPRESSION_ENABLED = True

# Duplicate filter
DUPEFILTER_CLASS = 'scrapy.dupefilters.RFPDupeFilter'
DUPEFILTER_DEBUG = False

# Scheduler
SCHEDULER_PRIORITY_QUEUE = 'scrapy.pqueues.ScrapyPriorityQueue'

# Custom settings
ALLOWLIST_PATH = settings.ALLOWLIST_PATH
BLOCKLIST_PATH = settings.BLOCKLIST_PATH
DATABASE_PATH = settings.DATABASE_PATH
RESPECT_CRAWL_DELAY = settings.RESPECT_CRAWL_DELAY
MAX_CRAWL_DELAY = settings.MAX_CRAWL_DELAY