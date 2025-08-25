"""Tests for compliance components."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.compliance.licenses import ContentLicense, LicenseManager
from app.compliance.robots import RobotsChecker
from app.compliance.takedown import TakedownQueue, TakedownStatus
from app.storage.db import Database


class TestLicenseManager:
    """Test license management."""
    
    def test_domain_allowed(self):
        """Test domain allowlist checking."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("example.com\n")
            f.write("test.org cc_by\n")
            allowlist_path = f.name
        
        try:
            manager = LicenseManager(allowlist_path=allowlist_path)
            
            assert manager.is_domain_allowed("example.com") is True
            assert manager.is_domain_allowed("test.org") is True
            assert manager.is_domain_allowed("other.com") is False
            
            # Test subdomain
            assert manager.is_domain_allowed("sub.example.com") is True
        finally:
            Path(allowlist_path).unlink()
    
    def test_domain_blocked(self):
        """Test domain blocklist checking."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("blocked.com\n")
            f.write("spam.org\n")
            blocklist_path = f.name
        
        try:
            manager = LicenseManager(blocklist_path=blocklist_path)
            
            assert manager.is_domain_allowed("blocked.com") is False
            assert manager.is_domain_allowed("spam.org") is False
            assert manager.is_domain_allowed("example.com") is True
            
            # Test subdomain
            assert manager.is_domain_allowed("sub.blocked.com") is False
        finally:
            Path(blocklist_path).unlink()
    
    def test_detect_license_from_text(self):
        """Test license detection from text."""
        manager = LicenseManager()
        
        # Test CC0
        text = "This work is licensed under CC0 1.0 Universal"
        assert manager.detect_license_from_text(text) == ContentLicense.CC0.value
        
        # Test CC BY
        text = "Licensed under Creative Commons Attribution 4.0"
        assert manager.detect_license_from_text(text) == ContentLicense.CC_BY.value
        
        # Test CC BY-SA
        text = "This content is available under CC BY-SA 4.0"
        assert manager.detect_license_from_text(text) == ContentLicense.CC_BY_SA.value
        
        # Test public domain
        text = "This work is in the public domain"
        assert manager.detect_license_from_text(text) == ContentLicense.PUBLIC_DOMAIN.value
        
        # Test all rights reserved
        text = "© 2024 Company. All rights reserved."
        assert manager.detect_license_from_text(text) == ContentLicense.ALL_RIGHTS_RESERVED.value
        
        # Test unknown
        text = "Some random text without license info"
        assert manager.detect_license_from_text(text) == ContentLicense.UNKNOWN.value
    
    def test_license_compatibility(self):
        """Test license compatibility checking."""
        manager = LicenseManager()
        
        assert manager.is_license_compatible(ContentLicense.CC0.value) is True
        assert manager.is_license_compatible(ContentLicense.CC_BY.value) is True
        assert manager.is_license_compatible(ContentLicense.PUBLIC_DOMAIN.value) is True
        assert manager.is_license_compatible(ContentLicense.ALL_RIGHTS_RESERVED.value) is False
    
    def test_add_allowed_domain(self):
        """Test adding domain to allowlist."""
        manager = LicenseManager()
        
        manager.add_allowed_domain("newsite.com", "cc_by")
        
        assert manager.is_domain_allowed("newsite.com") is True
        assert manager.get_domain_license("newsite.com") == "cc_by"
    
    def test_add_blocked_domain(self):
        """Test adding domain to blocklist."""
        manager = LicenseManager()
        manager.add_allowed_domain("example.com")
        
        manager.add_blocked_domain("example.com")
        
        assert manager.is_domain_allowed("example.com") is False
        assert "example.com" not in manager.allowed_domains


class TestRobotsChecker:
    """Test robots.txt compliance."""
    
    @pytest.mark.asyncio
    async def test_can_fetch_allowed(self):
        """Test allowed URL checking."""
        checker = RobotsChecker()
        
        # Mock HTTP client
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = """
User-agent: *
Disallow: /admin/
Disallow: /private/
Allow: /public/
Crawl-delay: 1

User-agent: SearchEngineBot
Allow: /
Crawl-delay: 0.5
"""
        
        with patch.object(checker.client, 'get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            
            # Test general user agent
            allowed, delay = await checker.can_fetch(
                "https://example.com/public/page",
                "*"
            )
            assert allowed is True
            assert delay == 1.0
            
            # Test disallowed path
            allowed, delay = await checker.can_fetch(
                "https://example.com/admin/secret",
                "*"
            )
            assert allowed is False
            
            # Test specific user agent
            allowed, delay = await checker.can_fetch(
                "https://example.com/admin/page",
                "SearchEngineBot"
            )
            assert allowed is True
            assert delay == 0.5
        
        await checker.close()
    
    @pytest.mark.asyncio
    async def test_no_robots_txt(self):
        """Test handling of missing robots.txt."""
        checker = RobotsChecker()
        
        mock_response = Mock()
        mock_response.status_code = 404
        
        with patch.object(checker.client, 'get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            
            allowed, delay = await checker.can_fetch(
                "https://example.com/page",
                "TestBot"
            )
            
            assert allowed is True  # No robots.txt means everything is allowed
            assert delay is None
        
        await checker.close()
    
    @pytest.mark.asyncio
    async def test_get_sitemap_urls(self):
        """Test sitemap URL extraction."""
        checker = RobotsChecker()
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = """
User-agent: *
Disallow: /admin/

Sitemap: https://example.com/sitemap.xml
Sitemap: https://example.com/sitemap-news.xml
"""
        
        with patch.object(checker.client, 'get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            
            sitemaps = await checker.get_sitemap_urls("example.com")
            
            assert len(sitemaps) == 2
            assert "https://example.com/sitemap.xml" in sitemaps
            assert "https://example.com/sitemap-news.xml" in sitemaps
        
        await checker.close()


class TestTakedownQueue:
    """Test takedown request handling."""
    
    @pytest.fixture
    async def takedown_queue(self):
        """Create test takedown queue."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        db = Database(db_path)
        await db.initialize()
        
        queue = TakedownQueue(db)
        await queue.initialize()
        
        yield queue
        
        await db.close()
        Path(db_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_submit_request(self, takedown_queue):
        """Test submitting takedown request."""
        request_id = await takedown_queue.submit(
            url="https://example.com/remove",
            email="user@example.com",
            reason="Copyright infringement"
        )
        
        assert request_id is not None
        assert len(request_id) == 36  # UUID format
    
    @pytest.mark.asyncio
    async def test_get_pending_requests(self, takedown_queue):
        """Test retrieving pending requests."""
        # Submit multiple requests
        await takedown_queue.submit(
            url="https://example.com/1",
            email="user1@example.com",
            reason="Reason 1"
        )
        
        await takedown_queue.submit(
            url="https://example.com/2",
            email="user2@example.com",
            reason="Reason 2"
        )
        
        # Get pending requests
        pending = await takedown_queue.get_pending(limit=10)
        
        assert len(pending) == 2
        assert pending[0]['status'] == TakedownStatus.PENDING.value
        assert pending[1]['status'] == TakedownStatus.PENDING.value
    
    @pytest.mark.asyncio
    async def test_update_status(self, takedown_queue):
        """Test updating request status."""
        request_id = await takedown_queue.submit(
            url="https://example.com/test",
            email="user@example.com",
            reason="Test reason"
        )
        
        # Update to reviewing
        success = await takedown_queue.update_status(
            request_id,
            TakedownStatus.REVIEWING,
            "Under review"
        )
        assert success is True
        
        # Check updated status
        request = await takedown_queue.get_request(request_id)
        assert request['status'] == TakedownStatus.REVIEWING.value
        assert request['reviewer_notes'] == "Under review"
    
    @pytest.mark.asyncio
    async def test_get_statistics(self, takedown_queue):
        """Test statistics retrieval."""
        # Submit requests with different statuses
        request_id1 = await takedown_queue.submit(
            url="https://example.com/1",
            email="user@example.com",
            reason="Reason 1"
        )
        
        request_id2 = await takedown_queue.submit(
            url="https://example.com/2",
            email="user@example.com",
            reason="Reason 2"
        )
        
        # Update one to approved
        await takedown_queue.update_status(
            request_id1,
            TakedownStatus.APPROVED,
            "Approved"
        )
        
        # Get statistics
        stats = await takedown_queue.get_statistics()
        
        assert stats['total'] == 2
        assert stats['pending'] == 1
        assert stats['approved'] == 1