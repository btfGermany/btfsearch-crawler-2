#!/usr/bin/env python
"""Build autocomplete trie from query logs and titles."""

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.search.autocomplete import AutocompleteIndex
from app.storage.db import Database
from app.config import settings
from app.utils.logging import setup_logging

logger = setup_logging()


async def build_from_queries(db: Database, min_frequency: int = 2) -> AutocompleteIndex:
    """Build autocomplete from query logs.
    
    Args:
        db: Database instance
        min_frequency: Minimum query frequency
    
    Returns:
        Autocomplete index
    """
    # In a real system, you'd have a query_logs table
    # For now, we'll simulate with common patterns from titles
    
    titles = await db.fetchall("""
        SELECT title FROM documents 
        WHERE title IS NOT NULL AND title != ''
        LIMIT 10000
    """)
    
    # Extract common terms
    term_freq = Counter()
    
    for row in titles:
        title = row['title'].lower()
        
        # Add full title
        term_freq[title] += 1
        
        # Add individual words
        words = title.split()
        for word in words:
            if len(word) > 2:
                term_freq[word] += 2  # Give words higher weight
        
        # Add bigrams
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            term_freq[bigram] += 1
    
    # Filter by frequency
    queries = [
        {"query": term, "count": count}
        for term, count in term_freq.items()
        if count >= min_frequency
    ]
    
    # Sort by frequency
    queries.sort(key=lambda x: x['count'], reverse=True)
    
    # Build index
    index = AutocompleteIndex()
    await index.build_from_queries(queries[:5000])  # Limit to top 5000
    
    return index


async def build_from_titles(db: Database) -> AutocompleteIndex:
    """Build autocomplete from document titles.
    
    Args:
        db: Database instance
    
    Returns:
        Autocomplete index
    """
    titles = await db.fetchall("""
        SELECT DISTINCT title FROM documents 
        WHERE title IS NOT NULL AND title != ''
    """)
    
    index = AutocompleteIndex()
    await index.build_from_titles([row['title'] for row in titles])
    
    return index


async def main():
    """Main function."""
    logger.info("Building autocomplete index...")
    
    # Initialize database
    db = Database(settings.DATABASE_PATH)
    await db.initialize()
    
    try:
        # Build from queries (simulated)
        query_index = await build_from_queries(db)
        
        # Build from titles
        title_index = await build_from_titles(db)
        
        # Merge indices (use query index as primary)
        # In production, you'd have a more sophisticated merging strategy
        
        # Save indices
        output_dir = Path(settings.DATABASE_PATH).parent
        
        query_index_path = output_dir / "autocomplete_queries.json"
        await query_index.save(str(query_index_path))
        logger.info(f"Query autocomplete saved to {query_index_path}")
        
        title_index_path = output_dir / "autocomplete_titles.json"
        await title_index.save(str(title_index_path))
        logger.info(f"Title autocomplete saved to {title_index_path}")
        
        # Save primary index
        primary_path = output_dir / "autocomplete.json"
        await query_index.save(str(primary_path))
        logger.info(f"Primary autocomplete saved to {primary_path}")
        
        # Test the index
        test_queries = ["search", "web", "python", "data"]
        logger.info("\nTesting autocomplete:")
        
        for query in test_queries:
            suggestions = await query_index.suggest(query, limit=5)
            logger.info(f"  '{query}' -> {suggestions}")
    
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())