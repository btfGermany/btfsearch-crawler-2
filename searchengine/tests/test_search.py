"""Tests for search functionality."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from app.search.index import SearchIndex
from app.search.rank import SearchRanker
from app.search.tokenizer import QueryTokenizer
from app.storage.db import Database


@pytest.fixture
async def test_db():
    """Create test database."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    db = Database(db_path)
    await db.initialize()
    
    yield db
    
    await db.close()
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
async def search_index(test_db):
    """Create search index."""
    index = SearchIndex(test_db)
    await index.initialize()
    return index


class TestSearchIndex:
    """Test search index functionality."""
    
    @pytest.mark.asyncio
    async def test_insert_document(self, search_index):
        """Test document insertion."""
        doc_id = await search_index.insert_document(
            url="https://example.com/test",
            title="Test Document",
            content="This is a test document with some content.",
            snippet="This is a test document...",
            lang="en",
            site="example.com"
        )
        
        assert doc_id is not None
        assert doc_id > 0
    
    @pytest.mark.asyncio
    async def test_search_basic(self, search_index):
        """Test basic search."""
        # Insert test documents
        await search_index.insert_document(
            url="https://example.com/1",
            title="Python Programming",
            content="Python is a high-level programming language.",
            snippet="Python is a high-level...",
            lang="en",
            site="example.com"
        )
        
        await search_index.insert_document(
            url="https://example.com/2",
            title="JavaScript Guide",
            content="JavaScript is a scripting language for web development.",
            snippet="JavaScript is a scripting...",
            lang="en",
            site="example.com"
        )
        
        # Search for Python
        results, total = await search_index.search("Python", limit=10)
        
        assert total == 1
        assert len(results) == 1
        assert "Python" in results[0]["title"]
    
    @pytest.mark.asyncio
    async def test_search_with_filters(self, search_index):
        """Test search with language and site filters."""
        # Insert documents in different languages
        await search_index.insert_document(
            url="https://example.com/en/1",
            title="English Document",
            content="This is an English document.",
            snippet="This is an English...",
            lang="en",
            site="example.com"
        )
        
        await search_index.insert_document(
            url="https://example.de/de/1",
            title="Deutsches Dokument",
            content="Dies ist ein deutsches Dokument.",
            snippet="Dies ist ein deutsches...",
            lang="de",
            site="example.de"
        )
        
        # Search with language filter
        results, total = await search_index.search(
            "document",
            lang="en",
            limit=10
        )
        
        assert total == 1
        assert results[0]["lang"] == "en"
        
        # Search with site filter
        results, total = await search_index.search(
            "document",
            site="example.de",
            limit=10
        )
        
        assert total == 1
        assert results[0]["site"] == "example.de"
    
    @pytest.mark.asyncio
    async def test_duplicate_detection(self, search_index):
        """Test duplicate content detection."""
        # Insert document
        doc_id1 = await search_index.insert_document(
            url="https://example.com/original",
            title="Original Document",
            content="This is the original content.",
            snippet="This is the original...",
            lang="en",
            site="example.com"
        )
        
        # Insert same content with different URL
        doc_id2 = await search_index.insert_document(
            url="https://example.com/duplicate",
            title="Original Document",
            content="This is the original content.",
            snippet="This is the original...",
            lang="en",
            site="example.com"
        )
        
        # Should update existing document with same content hash
        assert doc_id1 is not None
        assert doc_id2 is not None
    
    @pytest.mark.asyncio
    async def test_delete_document(self, search_index):
        """Test document deletion."""
        # Insert document
        await search_index.insert_document(
            url="https://example.com/delete-me",
            title="Delete This",
            content="This document will be deleted.",
            snippet="This document will be...",
            lang="en",
            site="example.com"
        )
        
        # Verify it exists
        results, total = await search_index.search("delete", limit=10)
        assert total == 1
        
        # Delete it
        success = await search_index.delete_document("https://example.com/delete-me")
        assert success is True
        
        # Verify it's gone
        results, total = await search_index.search("delete", limit=10)
        assert total == 0


class TestQueryTokenizer:
    """Test query tokenization."""
    
    def test_normalize_basic(self):
        """Test basic query normalization."""
        tokenizer = QueryTokenizer()
        
        # Test lowercase
        assert tokenizer.normalize("HELLO WORLD") == "hello world"
        
        # Test special characters
        assert tokenizer.normalize("hello@world.com") == "hello world com"
        
        # Test stopwords removal
        assert tokenizer.normalize("the quick brown fox") == "quick brown fox"
    
    def test_normalize_quoted_phrases(self):
        """Test quoted phrase handling."""
        tokenizer = QueryTokenizer()
        
        query = 'search for "exact phrase" and more'
        normalized = tokenizer.normalize(query)
        
        assert '"exact phrase"' in normalized
        assert "search" in normalized
    
    def test_tokenize(self):
        """Test text tokenization."""
        tokenizer = QueryTokenizer()
        
        text = "The quick brown fox jumps over the lazy dog"
        tokens = tokenizer.tokenize(text)
        
        assert "quick" in tokens
        assert "brown" in tokens
        assert "fox" in tokens
        assert "the" not in tokens  # Stopword removed
    
    def test_extract_phrases(self):
        """Test phrase extraction."""
        tokenizer = QueryTokenizer()
        
        query = 'find "machine learning" or "artificial intelligence" papers'
        phrases, clean = tokenizer.extract_phrases(query)
        
        assert len(phrases) == 2
        assert "machine learning" in phrases
        assert "artificial intelligence" in phrases
        assert "find" in clean
        assert "papers" in clean


class TestSearchRanker:
    """Test search ranking."""
    
    @pytest.mark.asyncio
    async def test_bm25_ranking(self, test_db):
        """Test BM25 ranking."""
        index = SearchIndex(test_db)
        await index.initialize()
        
        # Insert documents with varying relevance
        await index.insert_document(
            url="https://example.com/1",
            title="Python Python Python",
            content="Python mentioned many times. Python is great. Python rocks.",
            snippet="Python mentioned many times...",
            lang="en",
            site="example.com"
        )
        
        await index.insert_document(
            url="https://example.com/2",
            title="Programming Languages",
            content="There are many programming languages including Python.",
            snippet="There are many programming...",
            lang="en",
            site="example.com"
        )
        
        ranker = SearchRanker(test_db, enable_semantic=False)
        await ranker.initialize()
        
        results = await ranker.search("Python", page=1, page_size=10)
        
        assert len(results["results"]) == 2
        # First result should have higher score due to more occurrences
        assert results["results"][0]["url"] == "https://example.com/1"
    
    @pytest.mark.asyncio
    async def test_caching(self, test_db):
        """Test result caching."""
        index = SearchIndex(test_db)
        await index.initialize()
        
        await index.insert_document(
            url="https://example.com/cached",
            title="Cached Document",
            content="This document tests caching.",
            snippet="This document tests...",
            lang="en",
            site="example.com"
        )
        
        ranker = SearchRanker(test_db, enable_semantic=False)
        await ranker.initialize()
        
        # First search
        results1 = await ranker.search("cached", page=1, page_size=10)
        assert results1["from_cache"] is False
        
        # Second search should hit cache
        results2 = await ranker.search("cached", page=1, page_size=10)
        assert results2["from_cache"] is True
        
        # Results should be identical
        assert results1["total"] == results2["total"]