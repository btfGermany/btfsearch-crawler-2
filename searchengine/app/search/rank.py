"""Search ranking with optional semantic reranking."""

import asyncio
import time
from functools import lru_cache
from typing import Any, Dict, List, Optional

import numpy as np
import structlog
from sentence_transformers import SentenceTransformer

from app.search.index import SearchIndex
from app.search.tokenizer import QueryTokenizer
from app.storage.db import Database

logger = structlog.get_logger()


class SearchRanker:
    """Search ranker with BM25 and optional semantic reranking."""
    
    def __init__(
        self,
        db: Database,
        enable_semantic: bool = False,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    ):
        """Initialize search ranker.
        
        Args:
            db: Database instance
            enable_semantic: Enable semantic search
            model_name: Sentence transformer model name
        """
        self.db = db
        self.index = SearchIndex(db)
        self.tokenizer = QueryTokenizer()
        self.enable_semantic = enable_semantic
        self.model_name = model_name
        self.model: Optional[SentenceTransformer] = None
        self._cache = {}
        self._cache_size = 1000
    
    async def initialize(self) -> None:
        """Initialize the ranker."""
        await self.index.initialize()
        
        if self.enable_semantic:
            try:
                # Load model in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                self.model = await loop.run_in_executor(
                    None, 
                    SentenceTransformer, 
                    self.model_name
                )
                logger.info("Semantic search model loaded", model=self.model_name)
            except Exception as e:
                logger.error("Failed to load semantic model", error=str(e))
                self.enable_semantic = False
    
    async def search(
        self,
        query: str,
        page: int = 1,
        page_size: int = 10,
        lang: Optional[str] = None,
        site: Optional[str] = None,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """Search with BM25 and optional semantic reranking.
        
        Args:
            query: Search query
            page: Page number (1-indexed)
            page_size: Results per page
            lang: Language filter
            site: Site filter
            use_cache: Use result cache
        
        Returns:
            Search results dictionary
        """
        start_time = time.time()
        
        # Normalize query
        normalized_query = self.tokenizer.normalize(query)
        
        # Check cache
        cache_key = f"{normalized_query}:{page}:{page_size}:{lang}:{site}"
        if use_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            cached["from_cache"] = True
            return cached
        
        # Calculate offset
        offset = (page - 1) * page_size
        
        # Get more results if semantic reranking is enabled
        fetch_limit = page_size * 3 if self.enable_semantic else page_size
        
        # Perform BM25 search
        results, total = await self.index.search(
            query=normalized_query,
            limit=fetch_limit,
            offset=offset if not self.enable_semantic else 0,
            lang=lang,
            site=site
        )
        
        # Semantic reranking if enabled
        if self.enable_semantic and self.model and results:
            results = await self._semantic_rerank(query, results)
            
            # Apply pagination after reranking
            start_idx = offset
            end_idx = offset + page_size
            results = results[start_idx:end_idx]
        
        # Format results
        formatted_results = []
        for result in results:
            formatted_results.append({
                "url": result["url"],
                "title": result["title"],
                "snippet": result["snippet"],
                "site": result["site"],
                "lang": result["lang"],
                "score": result["score"],
                "fetch_date": result["fetch_date"]
            })
        
        # Prepare response
        response = {
            "query": query,
            "results": formatted_results,
            "total": total,
            "page": page,
            "page_size": page_size,
            "took_ms": int((time.time() - start_time) * 1000),
            "from_cache": False
        }
        
        # Update cache
        if use_cache:
            self._update_cache(cache_key, response)
        
        return response
    
    async def _semantic_rerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Rerank results using semantic similarity.
        
        Args:
            query: Original query
            results: BM25 results
            top_k: Number of top results to return
        
        Returns:
            Reranked results
        """
        if not self.model or not results:
            return results
        
        try:
            loop = asyncio.get_event_loop()
            
            # Encode query
            query_embedding = await loop.run_in_executor(
                None,
                self.model.encode,
                query,
                True  # normalize_embeddings
            )
            
            # Prepare texts for encoding
            texts = []
            for result in results:
                # Combine title and snippet for better representation
                text = f"{result['title']} {result.get('snippet', '')[:200]}"
                texts.append(text)
            
            # Encode documents
            doc_embeddings = await loop.run_in_executor(
                None,
                self.model.encode,
                texts,
                True  # normalize_embeddings
            )
            
            # Calculate cosine similarities
            similarities = np.dot(doc_embeddings, query_embedding)
            
            # Combine BM25 and semantic scores
            for i, result in enumerate(results):
                bm25_score = result["score"]
                semantic_score = float(similarities[i])
                
                # Weighted combination (70% BM25, 30% semantic)
                combined_score = 0.7 * bm25_score + 0.3 * semantic_score
                result["score"] = combined_score
                result["semantic_score"] = semantic_score
            
            # Sort by combined score
            results.sort(key=lambda x: x["score"], reverse=True)
            
            if top_k:
                results = results[:top_k]
            
            return results
        
        except Exception as e:
            logger.error("Semantic reranking failed", error=str(e))
            return results
    
    def _update_cache(self, key: str, value: Dict[str, Any]) -> None:
        """Update the result cache with LRU eviction.
        
        Args:
            key: Cache key
            value: Cache value
        """
        if len(self._cache) >= self._cache_size:
            # Remove oldest entry (simple FIFO for now)
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
        
        self._cache[key] = value
    
    async def get_similar(
        self,
        doc_id: int,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Find similar documents using semantic similarity.
        
        Args:
            doc_id: Document ID
            limit: Maximum results
        
        Returns:
            List of similar documents
        """
        if not self.enable_semantic or not self.model:
            return []
        
        try:
            # Get document
            doc = await self.db.fetchone(
                "SELECT title, content FROM documents WHERE doc_id = ?",
                (doc_id,)
            )
            
            if not doc:
                return []
            
            # Create query from document
            query = f"{doc['title']} {doc['content'][:500]}"
            
            # Search for similar
            results = await self.search(
                query=query,
                page=1,
                page_size=limit,
                use_cache=False
            )
            
            # Filter out the original document
            similar = [
                r for r in results["results"]
                if r.get("doc_id") != doc_id
            ]
            
            return similar[:limit]
        
        except Exception as e:
            logger.error("Similar search failed", error=str(e))
            return []