"""Tests for web crawler."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from scrapy.http import HtmlResponse, Request

from app.crawler.middlewares import AllowlistMiddleware, RobotsMiddleware
from app.crawler.pipelines import (
    ContentExtractionPipeline,
    DuplicatesPipeline,
    LanguageDetectionPipeline,
    ValidationPipeline
)


class TestValidationPipeline:
    """Test validation pipeline."""
    
    def test_valid_item(self):
        """Test valid item passes validation."""
        pipeline = ValidationPipeline()
        spider = Mock()
        
        item = {
            'url': 'https://example.com/page',
            'html': '<html><body>Content with enough text to pass validation</body></html>' * 10
        }
        
        result = pipeline.process_item(item, spider)
        assert result == item
    
    def test_missing_url(self):
        """Test item without URL is dropped."""
        pipeline = ValidationPipeline()
        spider = Mock()
        
        item = {'html': '<html><body>Content</body></html>'}
        
        from scrapy.exceptions import DropItem
        with pytest.raises(DropItem, match="Missing URL"):
            pipeline.process_item(item, spider)
    
    def test_missing_html(self):
        """Test item without HTML is dropped."""
        pipeline = ValidationPipeline()
        spider = Mock()
        
        item = {'url': 'https://example.com/page'}
        
        from scrapy.exceptions import DropItem
        with pytest.raises(DropItem, match="Missing HTML"):
            pipeline.process_item(item, spider)
    
    def test_content_too_small(self):
        """Test small content is dropped."""
        pipeline = ValidationPipeline()
        spider = Mock()
        
        item = {
            'url': 'https://example.com/page',
            'html': '<html>Hi</html>'
        }
        
        from scrapy.exceptions import DropItem
        with pytest.raises(DropItem, match="Content too small"):
            pipeline.process_item(item, spider)


class TestDuplicatesPipeline:
    """Test duplicates pipeline."""
    
    def test_unique_content(self):
        """Test unique content passes through."""
        pipeline = DuplicatesPipeline()
        spider = Mock()
        
        item1 = {
            'url': 'https://example.com/page1',
            'html': '<html><body>Unique content 1</body></html>'
        }
        
        item2 = {
            'url': 'https://example.com/page2',
            'html': '<html><body>Unique content 2</body></html>'
        }
        
        result1 = pipeline.process_item(item1, spider)
        assert 'normalized_url' in result1
        assert 'content_hash' in result1
        
        result2 = pipeline.process_item(item2, spider)
        assert 'normalized_url' in result2
        assert 'content_hash' in result2
    
    def test_duplicate_url(self):
        """Test duplicate URL is dropped."""
        pipeline = DuplicatesPipeline()
        spider = Mock()
        
        item1 = {
            'url': 'https://example.com/page',
            'html': '<html><body>Content 1</body></html>'
        }
        
        item2 = {
            'url': 'https://example.com/page',  # Same URL
            'html': '<html><body>Content 2</body></html>'
        }
        
        pipeline.process_item(item1, spider)
        
        from scrapy.exceptions import DropItem
        with pytest.raises(DropItem, match="Duplicate URL"):
            pipeline.process_item(item2, spider)
    
    def test_duplicate_content(self):
        """Test duplicate content is dropped."""
        pipeline = DuplicatesPipeline()
        spider = Mock()
        
        content = '<html><body>Same content</body></html>'
        
        item1 = {
            'url': 'https://example.com/page1',
            'html': content
        }
        
        item2 = {
            'url': 'https://example.com/page2',
            'html': content  # Same content
        }
        
        pipeline.process_item(item1, spider)
        
        from scrapy.exceptions import DropItem
        with pytest.raises(DropItem, match="Duplicate content hash"):
            pipeline.process_item(item2, spider)


class TestContentExtractionPipeline:
    """Test content extraction pipeline."""
    
    def test_extract_from_html(self):
        """Test content extraction from HTML."""
        pipeline = ContentExtractionPipeline()
        spider = Mock()
        
        html = """
        <html>
        <head><title>Test Page Title</title></head>
        <body>
            <h1>Main Heading</h1>
            <p>This is the main content of the page with enough text to be meaningful.</p>
            <p>Another paragraph with more content to extract.</p>
        </body>
        </html>
        """
        
        item = {
            'url': 'https://example.com/page',
            'html': html
        }
        
        result = pipeline.process_item(item, spider)
        
        assert 'title' in result
        assert 'content' in result
        assert 'snippet' in result
        assert 'Test Page Title' in result['title']
        assert 'main content' in result['content'].lower()
    
    def test_extract_with_script_removal(self):
        """Test script tags are removed during extraction."""
        pipeline = ContentExtractionPipeline()
        spider = Mock()
        
        html = """
        <html>
        <head><title>Page with Scripts</title></head>
        <body>
            <script>alert('This should be removed');</script>
            <p>This content should remain.</p>
            <style>body { color: red; }</style>
        </body>
        </html>
        """
        
        item = {
            'url': 'https://example.com/page',
            'html': html
        }
        
        result = pipeline.process_item(item, spider)
        
        assert 'alert' not in result['content']
        assert 'should remain' in result['content']
        assert 'color: red' not in result['content']


class TestLanguageDetectionPipeline:
    """Test language detection pipeline."""
    
    def test_detect_english(self):
        """Test English language detection."""
        pipeline = LanguageDetectionPipeline()
        spider = Mock()
        
        item = {
            'title': 'English Title',
            'content': 'This is a long English text with enough content for reliable language detection. ' * 10
        }
        
        result = pipeline.process_item(item, spider)
        assert result['language'] == 'en'
    
    def test_detect_german(self):
        """Test German language detection."""
        pipeline = LanguageDetectionPipeline()
        spider = Mock()
        
        item = {
            'title': 'Deutscher Titel',
            'content': 'Dies ist ein längerer deutscher Text mit genügend Inhalt für eine zuverlässige Spracherkennung. ' * 10
        }
        
        result = pipeline.process_item(item, spider)
        assert result['language'] == 'de'
    
    def test_no_content(self):
        """Test handling of missing content."""
        pipeline = LanguageDetectionPipeline()
        spider = Mock()
        
        item = {
            'title': '',
            'content': ''
        }
        
        result = pipeline.process_item(item, spider)
        assert result['language'] is None


class TestAllowlistMiddleware:
    """Test allowlist middleware."""
    
    def test_allowed_domain(self):
        """Test allowed domain passes through."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("example.com\n")
            f.write("test.org\n")
            allowlist_path = f.name
        
        try:
            middleware = AllowlistMiddleware(allowlist_path=allowlist_path)
            
            request = Mock(url='https://example.com/page')
            spider = Mock()
            
            result = middleware.process_request(request, spider)
            assert result is None  # None means request is allowed
        finally:
            Path(allowlist_path).unlink()
    
    def test_blocked_domain(self):
        """Test blocked domain is rejected."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("blocked.com\n")
            blocklist_path = f.name
        
        try:
            middleware = AllowlistMiddleware(blocklist_path=blocklist_path)
            
            request = Mock(url='https://blocked.com/page')
            spider = Mock()
            
            from scrapy.exceptions import IgnoreRequest
            with pytest.raises(IgnoreRequest, match="Domain blocked"):
                middleware.process_request(request, spider)
        finally:
            Path(blocklist_path).unlink()
    
    def test_subdomain_handling(self):
        """Test subdomain of allowed domain is allowed."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("example.com\n")
            allowlist_path = f.name
        
        try:
            middleware = AllowlistMiddleware(allowlist_path=allowlist_path)
            
            request = Mock(url='https://sub.example.com/page')
            spider = Mock()
            
            result = middleware.process_request(request, spider)
            assert result is None  # Subdomain should be allowed
        finally:
            Path(allowlist_path).unlink()