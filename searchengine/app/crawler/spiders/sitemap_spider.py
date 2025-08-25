"""Spider for crawling sitemaps."""

from typing import Any, Dict, Iterator
from urllib.parse import urljoin, urlparse

import scrapy
from scrapy import Request
from scrapy.spiders import SitemapSpider


class SitemapCrawlSpider(SitemapSpider):
    """Spider that crawls websites using their sitemaps."""
    
    name = 'sitemap_spider'
    
    def __init__(self, *args, **kwargs):
        """Initialize sitemap spider.
        
        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments including sitemap_urls
        """
        # Get sitemap URLs from arguments or use defaults
        self.sitemap_urls = kwargs.pop('sitemap_urls', [])
        
        # If no sitemaps provided, try to discover them
        if not self.sitemap_urls and 'start_urls' in kwargs:
            self.sitemap_urls = [
                urljoin(url, '/sitemap.xml') 
                for url in kwargs['start_urls']
            ]
        
        super().__init__(*args, **kwargs)
        
        # Set allowed domains from sitemap URLs
        if not hasattr(self, 'allowed_domains'):
            self.allowed_domains = [
                urlparse(url).netloc 
                for url in self.sitemap_urls
            ]
    
    def sitemap_filter(self, entries: Iterator[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
        """Filter sitemap entries.
        
        Args:
            entries: Sitemap entries
        
        Yields:
            Filtered entries
        """
        for entry in entries:
            # Filter by date if needed
            # date_time = datetime.strptime(entry['lastmod'], '%Y-%m-%d')
            # if date_time.year >= 2020:
            #     yield entry
            
            # For now, yield all entries
            yield entry
    
    def parse(self, response: scrapy.http.Response) -> Dict[str, Any]:
        """Parse a page from the sitemap.
        
        Args:
            response: Scrapy response
        
        Yields:
            Parsed items
        """
        # Extract page data
        item = {
            'url': response.url,
            'html': response.text,
            'status': response.status,
            'headers': dict(response.headers),
            'meta': response.meta.copy()
        }
        
        # Add sitemap metadata if available
        if 'sitemap' in response.meta:
            sitemap_meta = response.meta['sitemap']
            item['sitemap_lastmod'] = sitemap_meta.get('lastmod')
            item['sitemap_changefreq'] = sitemap_meta.get('changefreq')
            item['sitemap_priority'] = sitemap_meta.get('priority')
        
        yield item
        
        # Follow links if depth allows
        if self.settings.getint('DEPTH_LIMIT', 3) > response.meta.get('depth', 0):
            # Extract links
            for href in response.css('a::attr(href)').getall():
                url = urljoin(response.url, href)
                
                # Check if URL is in allowed domains
                if any(urlparse(url).netloc.endswith(domain) for domain in self.allowed_domains):
                    yield Request(url, callback=self.parse)


class RSSSpider(scrapy.Spider):
    """Spider for crawling RSS feeds."""
    
    name = 'rss_spider'
    
    def __init__(self, *args, **kwargs):
        """Initialize RSS spider.
        
        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments including feed_urls
        """
        self.feed_urls = kwargs.pop('feed_urls', [])
        self.start_urls = self.feed_urls
        super().__init__(*args, **kwargs)
    
    def parse(self, response: scrapy.http.Response) -> Iterator[Request]:
        """Parse RSS feed.
        
        Args:
            response: Scrapy response
        
        Yields:
            Requests for feed items
        """
        # Parse RSS/Atom feed
        namespaces = {
            'atom': 'http://www.w3.org/2005/Atom',
            'rss': 'http://purl.org/rss/1.0/',
            'dc': 'http://purl.org/dc/elements/1.1/'
        }
        
        # Try RSS 2.0
        items = response.xpath('//channel/item')
        if items:
            for item in items:
                url = item.xpath('link/text()').get()
                if url:
                    meta = {
                        'feed_title': item.xpath('title/text()').get(),
                        'feed_description': item.xpath('description/text()').get(),
                        'feed_pubdate': item.xpath('pubDate/text()').get(),
                    }
                    yield Request(url, callback=self.parse_article, meta=meta)
        
        # Try Atom
        entries = response.xpath('//atom:entry', namespaces=namespaces)
        if entries:
            for entry in entries:
                url = entry.xpath('atom:link[@rel="alternate"]/@href', namespaces=namespaces).get()
                if url:
                    url = urljoin(response.url, url)
                    meta = {
                        'feed_title': entry.xpath('atom:title/text()', namespaces=namespaces).get(),
                        'feed_summary': entry.xpath('atom:summary/text()', namespaces=namespaces).get(),
                        'feed_updated': entry.xpath('atom:updated/text()', namespaces=namespaces).get(),
                    }
                    yield Request(url, callback=self.parse_article, meta=meta)
    
    def parse_article(self, response: scrapy.http.Response) -> Dict[str, Any]:
        """Parse article from feed.
        
        Args:
            response: Scrapy response
        
        Yields:
            Parsed article
        """
        item = {
            'url': response.url,
            'html': response.text,
            'status': response.status,
            'headers': dict(response.headers),
            'meta': response.meta.copy()
        }
        
        # Add feed metadata
        if 'feed_title' in response.meta:
            item['feed_title'] = response.meta['feed_title']
            item['feed_description'] = response.meta.get('feed_description')
            item['feed_pubdate'] = response.meta.get('feed_pubdate')
            item['feed_updated'] = response.meta.get('feed_updated')
        
        yield item