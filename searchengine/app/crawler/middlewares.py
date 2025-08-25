"""Scrapy middlewares for compliance and rate limiting."""

import asyncio
import time
from pathlib import Path
from typing import Optional, Set
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import structlog
from scrapy import Request, Spider
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.exceptions import IgnoreRequest
from scrapy.http import Response

from app.compliance.robots import RobotsChecker

logger = structlog.get_logger()


class RobotsMiddleware:
    """Middleware to respect robots.txt with proper crawl delays."""
    
    def __init__(self, obey_robots: bool = True, respect_delay: bool = True):
        """Initialize robots middleware.
        
        Args:
            obey_robots: Whether to obey robots.txt
            respect_delay: Whether to respect crawl-delay
        """
        self.obey_robots = obey_robots
        self.respect_delay = respect_delay
        self.robots_checker = RobotsChecker()
        self.last_access = {}
    
    @classmethod
    def from_crawler(cls, crawler):
        """Create middleware from crawler.
        
        Args:
            crawler: Crawler instance
        
        Returns:
            Middleware instance
        """
        return cls(
            obey_robots=crawler.settings.getbool('ROBOTSTXT_OBEY', True),
            respect_delay=crawler.settings.getbool('RESPECT_CRAWL_DELAY', True)
        )
    
    async def process_request(self, request: Request, spider: Spider) -> Optional[Response]:
        """Process request to check robots.txt.
        
        Args:
            request: Scrapy request
            spider: Spider instance
        
        Returns:
            None if allowed, Response if blocked
        
        Raises:
            IgnoreRequest: If URL is disallowed
        """
        if not self.obey_robots:
            return None
        
        url = request.url
        user_agent = spider.settings.get('USER_AGENT', '*')
        
        # Check if allowed
        allowed, delay = await self.robots_checker.can_fetch(url, user_agent)
        
        if not allowed:
            logger.info(f"Robots.txt disallows: {url}")
            raise IgnoreRequest(f"Forbidden by robots.txt: {url}")
        
        # Apply crawl delay if specified
        if self.respect_delay and delay and delay > 0:
            domain = urlparse(url).netloc
            now = time.time()
            
            if domain in self.last_access:
                elapsed = now - self.last_access[domain]
                if elapsed < delay:
                    wait_time = delay - elapsed
                    logger.debug(f"Waiting {wait_time:.1f}s for crawl-delay on {domain}")
                    await asyncio.sleep(wait_time)
            
            self.last_access[domain] = time.time()
        
        return None


class AllowlistMiddleware:
    """Middleware to filter URLs based on allowlist/blocklist."""
    
    def __init__(self, allowlist_path: str = None, blocklist_path: str = None):
        """Initialize allowlist middleware.
        
        Args:
            allowlist_path: Path to allowlist file
            blocklist_path: Path to blocklist file
        """
        self.allowed_domains: Set[str] = set()
        self.blocked_domains: Set[str] = set()
        
        if allowlist_path:
            self._load_list(allowlist_path, self.allowed_domains)
        
        if blocklist_path:
            self._load_list(blocklist_path, self.blocked_domains)
    
    @classmethod
    def from_crawler(cls, crawler):
        """Create middleware from crawler.
        
        Args:
            crawler: Crawler instance
        
        Returns:
            Middleware instance
        """
        return cls(
            allowlist_path=crawler.settings.get('ALLOWLIST_PATH'),
            blocklist_path=crawler.settings.get('BLOCKLIST_PATH')
        )
    
    def _load_list(self, filepath: str, target_set: Set[str]) -> None:
        """Load domain list from file.
        
        Args:
            filepath: Path to list file
            target_set: Set to populate
        """
        path = Path(filepath)
        if path.exists():
            try:
                with open(path, 'r') as f:
                    for line in f:
                        domain = line.strip().lower()
                        if domain and not domain.startswith('#'):
                            target_set.add(domain)
                logger.info(f"Loaded {len(target_set)} domains from {filepath}")
            except Exception as e:
                logger.error(f"Failed to load list from {filepath}: {e}")
    
    def process_request(self, request: Request, spider: Spider) -> Optional[Response]:
        """Filter requests based on domain lists.
        
        Args:
            request: Scrapy request
            spider: Spider instance
        
        Returns:
            None if allowed
        
        Raises:
            IgnoreRequest: If domain is not allowed
        """
        domain = urlparse(request.url).netloc.lower()
        
        # Check blocklist first
        if domain in self.blocked_domains:
            raise IgnoreRequest(f"Domain blocked: {domain}")
        
        # If allowlist exists and domain not in it, block
        if self.allowed_domains and domain not in self.allowed_domains:
            # Check if subdomain of allowed domain
            allowed = any(
                domain.endswith('.' + allowed) or domain == allowed
                for allowed in self.allowed_domains
            )
            if not allowed:
                raise IgnoreRequest(f"Domain not in allowlist: {domain}")
        
        return None


class RateLimitMiddleware:
    """Middleware for domain-based rate limiting."""
    
    def __init__(self, default_delay: float = 1.0, max_delay: float = 60.0):
        """Initialize rate limit middleware.
        
        Args:
            default_delay: Default delay between requests
            max_delay: Maximum allowed delay
        """
        self.default_delay = default_delay
        self.max_delay = max_delay
        self.domain_delays = {}
        self.last_request_time = {}
    
    @classmethod
    def from_crawler(cls, crawler):
        """Create middleware from crawler.
        
        Args:
            crawler: Crawler instance
        
        Returns:
            Middleware instance
        """
        return cls(
            default_delay=crawler.settings.getfloat('DOWNLOAD_DELAY', 1.0),
            max_delay=crawler.settings.getfloat('MAX_CRAWL_DELAY', 60.0)
        )
    
    async def process_request(self, request: Request, spider: Spider) -> Optional[Response]:
        """Apply rate limiting to requests.
        
        Args:
            request: Scrapy request
            spider: Spider instance
        
        Returns:
            None to continue processing
        """
        domain = urlparse(request.url).netloc
        now = time.time()
        
        # Get delay for domain
        delay = self.domain_delays.get(domain, self.default_delay)
        delay = min(delay, self.max_delay)
        
        # Check last request time
        if domain in self.last_request_time:
            elapsed = now - self.last_request_time[domain]
            if elapsed < delay:
                wait_time = delay - elapsed
                logger.debug(f"Rate limiting: waiting {wait_time:.2f}s for {domain}")
                await asyncio.sleep(wait_time)
        
        self.last_request_time[domain] = time.time()
        return None
    
    def process_response(self, request: Request, response: Response, spider: Spider) -> Response:
        """Adjust rate limits based on response.
        
        Args:
            request: Scrapy request
            response: Scrapy response
            spider: Spider instance
        
        Returns:
            Response object
        """
        domain = urlparse(request.url).netloc
        
        # Increase delay for rate limit responses
        if response.status == 429:
            current_delay = self.domain_delays.get(domain, self.default_delay)
            new_delay = min(current_delay * 2, self.max_delay)
            self.domain_delays[domain] = new_delay
            logger.warning(f"Rate limited on {domain}, increasing delay to {new_delay}s")
        
        # Decrease delay for successful responses
        elif response.status == 200:
            if domain in self.domain_delays:
                current_delay = self.domain_delays[domain]
                new_delay = max(current_delay * 0.9, self.default_delay)
                self.domain_delays[domain] = new_delay
        
        return response


class UserAgentMiddleware:
    """Middleware to set custom user agent."""
    
    def __init__(self, user_agent: str):
        """Initialize user agent middleware.
        
        Args:
            user_agent: User agent string
        """
        self.user_agent = user_agent
    
    @classmethod
    def from_crawler(cls, crawler):
        """Create middleware from crawler.
        
        Args:
            crawler: Crawler instance
        
        Returns:
            Middleware instance
        """
        return cls(
            user_agent=crawler.settings.get('USER_AGENT', 'SearchEngineBot/1.0')
        )
    
    def process_request(self, request: Request, spider: Spider) -> None:
        """Set user agent header.
        
        Args:
            request: Scrapy request
            spider: Spider instance
        """
        request.headers['User-Agent'] = self.user_agent
        return None


class ExponentialBackoffRetryMiddleware(RetryMiddleware):
    """Retry middleware with exponential backoff."""
    
    def __init__(self, settings):
        """Initialize retry middleware.
        
        Args:
            settings: Scrapy settings
        """
        super().__init__(settings)
        self.retry_delays = {}
    
    async def process_response(self, request: Request, response: Response, spider: Spider) -> Response:
        """Process response with exponential backoff for retries.
        
        Args:
            request: Scrapy request
            response: Scrapy response
            spider: Spider instance
        
        Returns:
            Response or retry request
        """
        if response.status in self.retry_http_codes:
            reason = f"HTTP {response.status}"
            retry_request = self._retry(request, reason, spider)
            
            if retry_request:
                # Apply exponential backoff
                retry_times = request.meta.get('retry_times', 0)
                delay = min(2 ** retry_times, 60)  # Max 60 seconds
                
                retry_request.meta['download_delay'] = delay
                logger.info(f"Retrying {request.url} after {delay}s (attempt {retry_times + 1})")
                
                await asyncio.sleep(delay)
                return retry_request
        
        return response