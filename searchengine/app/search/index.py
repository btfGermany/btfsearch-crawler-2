"""SQLite FTS5 search index implementation."""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import structlog
from app.storage.db import Database
from app.utils.hashing import hash_content

logger = structlog.get_logger()


class SearchIndex:
    """FTS5-based search index with BM25 ranking."""
    
    def __init__(self, db: Database):
        """Initialize search index.
        
        Args:
            db: Database instance
        """
        self.db = db
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize FTS5 tables and indexes."""
        if self._initialized:
            return
        
        await self._create_tables()
        await self._create_indexes()
        self._initialized = True
        logger.info("Search index initialized")
    
    async def _create_tables(self) -> None:
        """Create FTS5 virtual table and metadata tables."""
        # Main documents table
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                title TEXT,
                content TEXT,
                snippet TEXT,
                lang TEXT,
                license TEXT,
                site TEXT,
                fetch_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hash TEXT,
                meta_json TEXT
            )
        """)
        
        # FTS5 virtual table for full-text search
        await self.db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                doc_id UNINDEXED,
                title,
                content,
                site UNINDEXED,
                lang UNINDEXED,
                tokenize = 'porter unicode61',
                content_rowid = 'doc_id'
            )
        """)
        
        # Trigger to keep FTS in sync with main table
        await self.db.execute("""
            CREATE TRIGGER IF NOT EXISTS documents_ai 
            AFTER INSERT ON documents BEGIN
                INSERT INTO documents_fts(doc_id, title, content, site, lang)
                VALUES (new.doc_id, new.title, new.content, new.site, new.lang);
            END
        """)
        
        await self.db.execute("""
            CREATE TRIGGER IF NOT EXISTS documents_ad 
            AFTER DELETE ON documents BEGIN
                DELETE FROM documents_fts WHERE doc_id = old.doc_id;
            END
        """)
        
        await self.db.execute("""
            CREATE TRIGGER IF NOT EXISTS documents_au 
            AFTER UPDATE ON documents BEGIN
                UPDATE documents_fts 
                SET title = new.title, content = new.content, 
                    site = new.site, lang = new.lang
                WHERE doc_id = new.doc_id;
            END
        """)
    
    async def _create_indexes(self) -> None:
        """Create database indexes for performance."""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_documents_url ON documents(url)",
            "CREATE INDEX IF NOT EXISTS idx_documents_site ON documents(site)",
            "CREATE INDEX IF NOT EXISTS idx_documents_lang ON documents(lang)",
            "CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(hash)",
            "CREATE INDEX IF NOT EXISTS idx_documents_fetch_ts ON documents(fetch_ts)"
        ]
        
        for index_sql in indexes:
            await self.db.execute(index_sql)
    
    async def insert_document(
        self,
        url: str,
        title: str,
        content: str,
        snippet: str,
        lang: Optional[str] = None,
        license: Optional[str] = None,
        site: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None
    ) -> Optional[int]:
        """Insert or update a document in the index.
        
        Args:
            url: Document URL
            title: Document title
            content: Document content (for indexing)
            snippet: Display snippet
            lang: Language code
            license: Content license
            site: Site domain
            meta: Additional metadata
        
        Returns:
            Document ID if successful, None otherwise
        """
        try:
            # Generate content hash
            content_hash = hash_content(content)
            
            # Check if document exists
            existing = await self.db.fetchone(
                "SELECT doc_id, hash FROM documents WHERE url = ?",
                (url,)
            )
            
            if existing and existing["hash"] == content_hash:
                # Content unchanged
                return existing["doc_id"]
            
            meta_json = json.dumps(meta) if meta else None
            
            if existing:
                # Update existing document
                await self.db.execute("""
                    UPDATE documents 
                    SET title = ?, content = ?, snippet = ?, lang = ?, 
                        license = ?, site = ?, hash = ?, meta_json = ?,
                        fetch_ts = CURRENT_TIMESTAMP
                    WHERE url = ?
                """, (title, content, snippet, lang, license, site, 
                      content_hash, meta_json, url))
                return existing["doc_id"]
            else:
                # Insert new document
                result = await self.db.execute("""
                    INSERT INTO documents 
                    (url, title, content, snippet, lang, license, site, hash, meta_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (url, title, content, snippet, lang, license, site, 
                      content_hash, meta_json))
                
                return result.lastrowid if result else None
        
        except Exception as e:
            logger.error("Failed to insert document", url=url, error=str(e))
            return None
    
    async def search(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0,
        lang: Optional[str] = None,
        site: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Search documents using FTS5 with BM25 ranking.
        
        Args:
            query: Search query
            limit: Maximum results
            offset: Result offset
            lang: Filter by language
            site: Filter by site
        
        Returns:
            Tuple of (results, total_count)
        """
        try:
            # Build WHERE clause
            where_clauses = ["documents_fts MATCH ?"]
            params = [query]
            
            if lang:
                where_clauses.append("documents_fts.lang = ?")
                params.append(lang)
            
            if site:
                where_clauses.append("documents_fts.site = ?")
                params.append(site)
            
            where_sql = " AND ".join(where_clauses)
            
            # Count total results
            count_sql = f"""
                SELECT COUNT(*) as total
                FROM documents_fts
                WHERE {where_sql}
            """
            count_result = await self.db.fetchone(count_sql, params)
            total = count_result["total"] if count_result else 0
            
            # Search with BM25 ranking and field boosting
            search_sql = f"""
                SELECT 
                    d.doc_id,
                    d.url,
                    d.title,
                    d.snippet,
                    d.lang,
                    d.site,
                    d.fetch_ts,
                    d.license,
                    -- BM25 with field boosting (title 2x weight)
                    (
                        bm25(documents_fts, 0, 2.0, 1.0) * -1
                    ) as score,
                    highlight(documents_fts, 2, '<mark>', '</mark>') as highlighted_snippet
                FROM documents_fts
                JOIN documents d ON documents_fts.doc_id = d.doc_id
                WHERE {where_sql}
                ORDER BY score DESC
                LIMIT ? OFFSET ?
            """
            
            params.extend([limit, offset])
            results = await self.db.fetchall(search_sql, params)
            
            # Format results
            formatted_results = []
            for row in results:
                formatted_results.append({
                    "doc_id": row["doc_id"],
                    "url": row["url"],
                    "title": row["title"],
                    "snippet": row["highlighted_snippet"] or row["snippet"],
                    "lang": row["lang"],
                    "site": row["site"],
                    "fetch_date": row["fetch_ts"],
                    "license": row["license"],
                    "score": abs(row["score"])  # Convert negative BM25 to positive
                })
            
            return formatted_results, total
        
        except Exception as e:
            logger.error("Search failed", query=query, error=str(e))
            return [], 0
    
    async def delete_document(self, url: str) -> bool:
        """Delete a document by URL.
        
        Args:
            url: Document URL
        
        Returns:
            True if deleted, False otherwise
        """
        try:
            result = await self.db.execute(
                "DELETE FROM documents WHERE url = ?",
                (url,)
            )
            return result.rowcount > 0 if result else False
        except Exception as e:
            logger.error("Failed to delete document", url=url, error=str(e))
            return False
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get index statistics.
        
        Returns:
            Dictionary with index stats
        """
        try:
            # Total documents
            total_result = await self.db.fetchone(
                "SELECT COUNT(*) as total FROM documents"
            )
            total_documents = total_result["total"] if total_result else 0
            
            # Documents by language
            lang_result = await self.db.fetchall("""
                SELECT lang, COUNT(*) as count 
                FROM documents 
                WHERE lang IS NOT NULL 
                GROUP BY lang
            """)
            
            # Documents by site
            site_result = await self.db.fetchall("""
                SELECT site, COUNT(*) as count 
                FROM documents 
                WHERE site IS NOT NULL 
                GROUP BY site 
                ORDER BY count DESC 
                LIMIT 10
            """)
            
            # Database size
            size_result = await self.db.fetchone("""
                SELECT page_count * page_size / 1024.0 / 1024.0 as size_mb 
                FROM pragma_page_count(), pragma_page_size()
            """)
            
            # Last update
            last_update_result = await self.db.fetchone(
                "SELECT MAX(fetch_ts) as last_update FROM documents"
            )
            
            return {
                "total_documents": total_documents,
                "languages": {row["lang"]: row["count"] for row in lang_result} if lang_result else {},
                "top_sites": {row["site"]: row["count"] for row in site_result} if site_result else {},
                "size_mb": round(size_result["size_mb"], 2) if size_result else 0,
                "last_updated": last_update_result["last_update"] if last_update_result else None
            }
        
        except Exception as e:
            logger.error("Failed to get stats", error=str(e))
            return {}
    
    async def vacuum(self) -> bool:
        """Vacuum the database to reclaim space.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            await self.db.execute("VACUUM")
            await self.db.execute("ANALYZE")
            logger.info("Database vacuumed and analyzed")
            return True
        except Exception as e:
            logger.error("Vacuum failed", error=str(e))
            return False
    
    async def rebuild_fts(self) -> bool:
        """Rebuild the FTS index.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            await self.db.execute("INSERT INTO documents_fts(documents_fts) VALUES('rebuild')")
            logger.info("FTS index rebuilt")
            return True
        except Exception as e:
            logger.error("FTS rebuild failed", error=str(e))
            return False