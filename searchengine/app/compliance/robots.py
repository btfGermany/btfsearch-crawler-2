"""Robots.txt compliance checker."""

import asyncio
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

import httpx
import structlog
from reppy.robots import Robots

logger = structlog.get_logger()


class RobotsChecker:
    """Check robots.txt compliance for URLs."""
    
    def __init__(self, cache_size: int = 1000):
        """Initialize robots checker.
        
        Args:
            cache_size: Maximum cache size
        """
        self.cache: Dict[str, Robots] = {}
        self.cache_size = cache_size
        self.client = httpx.AsyncClient(timeout=10.0)
    
    async def can_fetch(
        self,
        url: str,
        user_agent: str = "*"
    ) -> Tuple[bool, Optional[float]]:
        """Check if URL can be fetched according to robots.txt.
        
        Args:
            url: URL to check
            user_agent: User agent string
        
        Returns:
            Tuple of (allowed, crawl_delay)
        """
        try:
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            
            # Get robots.txt
            robots = await self._get_robots(robots_url)
            
            if not robots:
                # No robots.txt means allowed
                return True, None
            
            # Check if allowed
            allowed = robots.allowed(url, user_agent)
            
            # Get crawl delay
            agent = robots.agent(user_agent)
            crawl_delay = agent.delay if agent else None
            
            return allowed, crawl_delay
        
        except Exception as e:
            logger.error(f"Error checking robots.txt for {url}: {e}")
            # On error, be conservative and allow
            return True, None
    
    async def _get_robots(self, robots_url: str) -> Optional[Robots]:
        """Get and parse robots.txt.
        
        Args:
            robots_url: URL to robots.txt
        
        Returns:
            Parsed robots.txt or None
        """
        # Check cache
        if robots_url in self.cache:
            return self.cache[robots_url]
        
        try:
            # Fetch robots.txt
            response = await self.client.get(robots_url)
            
            if response.status_code == 200:
                # Parse robots.txt
                robots = Robots.parse(robots_url, response.text)
                
                # Update cache
                self._update_cache(robots_url, robots)
                
                return robots
            elif response.status_code == 404:
                # No robots.txt
                self._update_cache(robots_url, None)
                return None
            else:
                logger.warning(f"Unexpected status {response.status_code} for {robots_url}")
                return None
        
        except httpx.TimeoutException:
            logger.warning(f"Timeout fetching {robots_url}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {robots_url}: {e}")
            return None
    
    def _update_cache(self, url: str, robots: Optional[Robots]) -> None:
        """Update robots cache with LRU eviction.
        
        Args:
            url: Robots.txt URL
            robots: Parsed robots or None
        """
        if len(self.cache) >= self.cache_size:
            # Remove oldest entry
            oldest = next(iter(self.cache))
            del self.cache[oldest]
        
        self.cache[url] = robots
    
    async def get_sitemap_urls(self, domain: str) -> List[str]:
        """Get sitemap URLs from robots.txt.
        
        Args:
            domain: Domain to check
        
        Returns:
            List of sitemap URLs
        """
        try:
            robots_url = f"https://{domain}/robots.txt"
            robots = await self._get_robots(robots_url)
            
            if robots and robots.sitemaps:
                return list(robots.sitemaps)
            
            return []
        
        except Exception as e:
            logger.error(f"Error getting sitemaps for {domain}: {e}")
            return []
    
    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()


from typing import List