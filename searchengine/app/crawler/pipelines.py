"""Scrapy item pipelines for processing crawled content."""

import asyncio
import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import structlog
from itemadapter import ItemAdapter
from langdetect import detect, LangDetectException
from scrapy import Spider
from scrapy.exceptions import DropItem
from trafilatura import extract
from w3lib.url import canonicalize_url

from app.search.index import SearchIndex
from app.storage.db import Database
from app.utils.hashing import hash_content

logger = structlog.get_logger()


class ValidationPipeline:
    """Validate crawled items."""
    
    def process_item(self, item: Dict[str, Any], spider: Spider) -> Dict[str, Any]:
        """Validate required fields.
        
        Args:
            item: Scraped item
            spider: Spider instance
        
        Returns:
            Validated item
        
        Raises:
            DropItem: If validation fails
        """
        adapter = ItemAdapter(item)
        
        # Check required fields
        if not adapter.get('url'):
            raise DropItem("Missing URL")
        
        if not adapter.get('html'):
            raise DropItem("Missing HTML content")
        
        # Validate URL
        try:
            parsed = urlparse(adapter['url'])
            if not parsed.scheme or not parsed.netloc:
                raise DropItem(f"Invalid URL: {adapter['url']}")
        except Exception:
            raise DropItem(f"Invalid URL: {adapter['url']}")
        
        # Check content size
        html_size = len(adapter['html'])
        if html_size < 100:
            raise DropItem(f"Content too small: {html_size} bytes")
        
        if html_size > 10 * 1024 * 1024:  # 10MB
            raise DropItem(f"Content too large: {html_size} bytes")
        
        return item


class DuplicatesPipeline:
    """Filter duplicate content using URL normalization and content hashing."""
    
    def __init__(self):
        self.seen_urls = set()
        self.seen_hashes = set()
    
    def process_item(self, item: Dict[str, Any], spider: Spider) -> Dict[str, Any]:
        """Check for duplicate content.
        
        Args:
            item: Scraped item
            spider: Spider instance
        
        Returns:
            Item if not duplicate
        
        Raises:
            DropItem: If duplicate detected
        """
        adapter = ItemAdapter(item)
        
        # Normalize URL
        normalized_url = canonicalize_url(adapter['url'])
        
        # Check URL duplicate
        if normalized_url in self.seen_urls:
            raise DropItem(f"Duplicate URL: {normalized_url}")
        
        # Calculate content hash
        content_hash = hash_content(adapter['html'])
        
        # Check content duplicate
        if content_hash in self.seen_hashes:
            raise DropItem(f"Duplicate content hash: {content_hash}")
        
        # Mark as seen
        self.seen_urls.add(normalized_url)
        self.seen_hashes.add(content_hash)
        
        # Add to item
        adapter['normalized_url'] = normalized_url
        adapter['content_hash'] = content_hash
        
        return item


class ContentExtractionPipeline:
    """Extract main content from HTML using trafilatura."""
    
    def process_item(self, item: Dict[str, Any], spider: Spider) -> Dict[str, Any]:
        """Extract content from HTML.
        
        Args:
            item: Scraped item with HTML
            spider: Spider instance
        
        Returns:
            Item with extracted content
        
        Raises:
            DropItem: If extraction fails
        """
        adapter = ItemAdapter(item)
        html = adapter['html']
        url = adapter['url']
        
        try:
            # Extract main content with trafilatura
            extracted = extract(
                html,
                url=url,
                include_comments=False,
                include_tables=True,
                include_images=False,
                include_links=False,
                output_format='dict',
                target_language=None,
                deduplicate=True
            )
            
            if not extracted:
                # Fallback to BeautifulSoup
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, 'lxml')
                
                # Remove script and style elements
                for script in soup(["script", "style"]):
                    script.decompose()
                
                # Get text
                text = soup.get_text(separator=' ', strip=True)
                title = soup.find('title')
                title_text = title.get_text(strip=True) if title else ''
                
                if not text or len(text) < 50:
                    raise DropItem(f"No content extracted from {url}")
                
                extracted = {
                    'title': title_text,
                    'text': text[:10000],  # Limit text size
                    'author': None,
                    'date': None,
                    'sitename': urlparse(url).netloc,
                    'description': None,
                    'license': None
                }
            
            # Add extracted content to item
            adapter['title'] = extracted.get('title', '')[:500]
            adapter['content'] = extracted.get('text', '')[:10000]
            adapter['author'] = extracted.get('author')
            adapter['publish_date'] = extracted.get('date')
            adapter['site_name'] = extracted.get('sitename', urlparse(url).netloc)
            adapter['description'] = extracted.get('description', '')[:500]
            adapter['license'] = extracted.get('license')
            
            # Create snippet
            content_preview = adapter['content'][:500]
            adapter['snippet'] = adapter.get('description') or content_preview[:200]
            
            return item
        
        except Exception as e:
            logger.error("Content extraction failed", url=url, error=str(e))
            raise DropItem(f"Extraction failed for {url}: {e}")


class LanguageDetectionPipeline:
    """Detect content language."""
    
    def process_item(self, item: Dict[str, Any], spider: Spider) -> Dict[str, Any]:
        """Detect language of content.
        
        Args:
            item: Item with extracted content
            spider: Spider instance
        
        Returns:
            Item with language code
        """
        adapter = ItemAdapter(item)
        
        try:
            # Combine title and content for detection
            text = f"{adapter.get('title', '')} {adapter.get('content', '')}"
            
            if text:
                # Detect language
                lang = detect(text[:1000])  # Use first 1000 chars
                adapter['language'] = lang
            else:
                adapter['language'] = None
        
        except LangDetectException:
            adapter['language'] = None
        except Exception as e:
            logger.warning("Language detection failed", error=str(e))
            adapter['language'] = None
        
        return item


class DatabasePipeline:
    """Store items in the database."""
    
    def __init__(self, database_path: str):
        """Initialize database pipeline.
        
        Args:
            database_path: Path to database file
        """
        self.database_path = database_path
        self.db: Optional[Database] = None
        self.index: Optional[SearchIndex] = None
    
    @classmethod
    def from_crawler(cls, crawler):
        """Create pipeline from crawler.
        
        Args:
            crawler: Crawler instance
        
        Returns:
            Pipeline instance
        """
        return cls(
            database_path=crawler.settings.get('DATABASE_PATH')
        )
    
    async def open_spider(self, spider: Spider) -> None:
        """Initialize database connection.
        
        Args:
            spider: Spider instance
        """
        self.db = Database(self.database_path)
        await self.db.initialize()
        self.index = SearchIndex(self.db)
        await self.index.initialize()
        logger.info("Database pipeline opened")
    
    async def close_spider(self, spider: Spider) -> None:
        """Close database connection.
        
        Args:
            spider: Spider instance
        """
        if self.db:
            await self.db.close()
        logger.info("Database pipeline closed")
    
    async def process_item(self, item: Dict[str, Any], spider: Spider) -> Dict[str, Any]:
        """Store item in database.
        
        Args:
            item: Item to store
            spider: Spider instance
        
        Returns:
            Processed item
        """
        if not self.index:
            return item
        
        adapter = ItemAdapter(item)
        
        try:
            # Prepare data for storage
            doc_id = await self.index.insert_document(
                url=adapter['url'],
                title=adapter.get('title', ''),
                content=adapter.get('content', ''),
                snippet=adapter.get('snippet', ''),
                lang=adapter.get('language'),
                license=adapter.get('license'),
                site=adapter.get('site_name'),
                meta={
                    'author': adapter.get('author'),
                    'publish_date': adapter.get('publish_date'),
                    'description': adapter.get('description'),
                    'content_hash': adapter.get('content_hash')
                }
            )
            
            if doc_id:
                adapter['doc_id'] = doc_id
                spider.logger.info(f"Stored document {doc_id}: {adapter['url']}")
            else:
                spider.logger.warning(f"Failed to store: {adapter['url']}")
        
        except Exception as e:
            spider.logger.error(f"Database error: {e}")
        
        return item