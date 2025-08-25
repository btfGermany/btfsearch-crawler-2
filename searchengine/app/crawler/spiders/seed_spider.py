"""Spider for crawling from seed URLs."""

from pathlib import Path
from typing import Any, Dict, Iterator, List
from urllib.parse import urljoin, urlparse

import scrapy
from scrapy import Request
from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule


class SeedSpider(CrawlSpider):
    """Spider that crawls from seed URLs with link following."""
    
    name = 'seed_spider'
    
    # Link extraction rules
    rules = (
        Rule(
            LinkExtractor(
                allow=(),
                deny=(
                    r'/login',
                    r'/register',
                    r'/admin',
                    r'/wp-admin',
                    r'\.pdf$',
                    r'\.zip$',
                    r'\.exe$',
                    r'\.dmg$',
                    r'\.iso$',
                ),
                deny_extensions=['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'],
                unique=True,
            ),
            callback='parse_item',
            follow=True
        ),
    )
    
    def __init__(self, *args, **kwargs):
        """Initialize seed spider.
        
        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments including seeds_file
        """
        # Get seeds from file or arguments
        seeds_file = kwargs.pop('seeds_file', 'seeds.txt')
        seed_urls = kwargs.pop('seed_urls', [])
        
        # Load seeds from file
        if seeds_file:
            seed_urls.extend(self._load_seeds(seeds_file))
        
        # Set start URLs
        self.start_urls = seed_urls if seed_urls else []
        
        # Extract allowed domains from seed URLs
        if not hasattr(self, 'allowed_domains'):
            self.allowed_domains = list(set(
                urlparse(url).netloc 
                for url in self.start_urls
                if urlparse(url).netloc
            ))
        
        super().__init__(*args, **kwargs)
        
        self.logger.info(f"Starting with {len(self.start_urls)} seed URLs")
        self.logger.info(f"Allowed domains: {self.allowed_domains}")
    
    def _load_seeds(self, filepath: str) -> List[str]:
        """Load seed URLs from file.
        
        Args:
            filepath: Path to seeds file
        
        Returns:
            List of seed URLs
        """
        seeds = []
        path = Path(filepath)
        
        if path.exists():
            try:
                with open(path, 'r') as f:
                    for line in f:
                        url = line.strip()
                        if url and not url.startswith('#'):
                            # Ensure URL has scheme
                            if not url.startswith(('http://', 'https://')):
                                url = f'https://{url}'
                            seeds.append(url)
                
                self.logger.info(f"Loaded {len(seeds)} seeds from {filepath}")
            except Exception as e:
                self.logger.error(f"Failed to load seeds from {filepath}: {e}")
        else:
            self.logger.warning(f"Seeds file not found: {filepath}")
        
        return seeds
    
    def start_requests(self) -> Iterator[Request]:
        """Generate initial requests from seed URLs.
        
        Yields:
            Initial requests
        """
        for url in self.start_urls:
            # Add metadata to track seed URLs
            yield Request(
                url,
                meta={
                    'is_seed': True,
                    'seed_url': url,
                    'depth': 0
                },
                dont_filter=True  # Always crawl seed URLs
            )
    
    def parse_start_url(self, response: scrapy.http.Response) -> Dict[str, Any]:
        """Parse seed URL response.
        
        Args:
            response: Scrapy response
        
        Returns:
            Parsed item
        """
        return self.parse_item(response)
    
    def parse_item(self, response: scrapy.http.Response) -> Dict[str, Any]:
        """Parse a crawled page.
        
        Args:
            response: Scrapy response
        
        Yields:
            Parsed item
        """
        # Skip non-HTML responses
        if not response.css('html'):
            self.logger.debug(f"Skipping non-HTML response: {response.url}")
            return
        
        # Extract item data
        item = {
            'url': response.url,
            'html': response.text,
            'status': response.status,
            'headers': dict(response.headers),
            'meta': {
                'is_seed': response.meta.get('is_seed', False),
                'seed_url': response.meta.get('seed_url'),
                'depth': response.meta.get('depth', 0),
                'referer': response.request.headers.get('Referer', b'').decode('utf-8', errors='ignore')
            }
        }
        
        # Extract metadata from HTML
        item['page_title'] = response.css('title::text').get()
        item['meta_description'] = response.css('meta[name="description"]::attr(content)').get()
        item['meta_keywords'] = response.css('meta[name="keywords"]::attr(content)').get()
        item['meta_author'] = response.css('meta[name="author"]::attr(content)').get()
        item['meta_robots'] = response.css('meta[name="robots"]::attr(content)').get()
        
        # Check robots meta tag
        if item['meta_robots']:
            robots_content = item['meta_robots'].lower()
            if 'noindex' in robots_content:
                self.logger.debug(f"Skipping noindex page: {response.url}")
                return
        
        # Extract canonical URL
        canonical = response.css('link[rel="canonical"]::attr(href)').get()
        if canonical:
            item['canonical_url'] = urljoin(response.url, canonical)
        
        # Extract language
        item['html_lang'] = response.css('html::attr(lang)').get()
        
        # Extract OpenGraph data
        item['og_title'] = response.css('meta[property="og:title"]::attr(content)').get()
        item['og_description'] = response.css('meta[property="og:description"]::attr(content)').get()
        item['og_image'] = response.css('meta[property="og:image"]::attr(content)').get()
        item['og_type'] = response.css('meta[property="og:type"]::attr(content)').get()
        
        # Extract structured data (JSON-LD)
        json_ld = response.css('script[type="application/ld+json"]::text').getall()
        if json_ld:
            item['structured_data'] = json_ld
        
        yield item
    
    def _requests_to_follow(self, response: scrapy.http.Response) -> Iterator[Request]:
        """Override to add depth tracking.
        
        Args:
            response: Scrapy response
        
        Yields:
            Requests to follow
        """
        if not isinstance(response, scrapy.http.HtmlResponse):
            return
        
        seen = set()
        current_depth = response.meta.get('depth', 0)
        max_depth = self.settings.getint('DEPTH_LIMIT', 3)
        
        # Don't follow links if at max depth
        if current_depth >= max_depth:
            return
        
        for rule_index, rule in enumerate(self._rules):
            links = [
                lnk for lnk in rule.link_extractor.extract_links(response)
                if lnk not in seen
            ]
            
            for link in links:
                seen.add(link)
                request = self._build_request(rule_index, link)
                
                # Add depth tracking
                request.meta['depth'] = current_depth + 1
                request.meta['seed_url'] = response.meta.get('seed_url')
                
                yield rule.process_request(request, response) if rule.process_request else request