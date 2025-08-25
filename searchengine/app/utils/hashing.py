"""Content hashing utilities."""

import hashlib
from typing import Optional

import xxhash


def hash_content(content: str, algorithm: str = "xxhash") -> str:
    """Hash content for deduplication.
    
    Args:
        content: Content to hash
        algorithm: Hashing algorithm (xxhash, md5, sha256)
    
    Returns:
        Hex digest of hash
    """
    if not content:
        return ""
    
    # Normalize content
    normalized = content.strip().lower()
    
    if algorithm == "xxhash":
        # Fast non-cryptographic hash
        return xxhash.xxh64(normalized.encode('utf-8')).hexdigest()
    elif algorithm == "md5":
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()
    elif algorithm == "sha256":
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    else:
        # Default to xxhash
        return xxhash.xxh64(normalized.encode('utf-8')).hexdigest()


def hash_url(url: str) -> str:
    """Hash URL for caching.
    
    Args:
        url: URL to hash
    
    Returns:
        Hex digest of hash
    """
    return xxhash.xxh64(url.encode('utf-8')).hexdigest()


def hash_query(query: str, filters: Optional[dict] = None) -> str:
    """Hash search query for caching.
    
    Args:
        query: Search query
        filters: Optional filters
    
    Returns:
        Hex digest of hash
    """
    # Combine query and filters
    cache_key = query.lower().strip()
    
    if filters:
        # Sort filters for consistent hashing
        sorted_filters = sorted(filters.items())
        filter_str = '|'.join(f"{k}:{v}" for k, v in sorted_filters if v)
        cache_key = f"{cache_key}|{filter_str}"
    
    return xxhash.xxh64(cache_key.encode('utf-8')).hexdigest()


def similarity_hash(text: str, shingle_size: int = 3) -> set:
    """Generate shingles for similarity detection.
    
    Args:
        text: Text to process
        shingle_size: Size of shingles
    
    Returns:
        Set of shingle hashes
    """
    if not text or len(text) < shingle_size:
        return set()
    
    # Normalize text
    normalized = text.strip().lower()
    
    # Generate shingles
    shingles = set()
    for i in range(len(normalized) - shingle_size + 1):
        shingle = normalized[i:i + shingle_size]
        shingle_hash = xxhash.xxh32(shingle.encode('utf-8')).intdigest()
        shingles.add(shingle_hash)
    
    return shingles


def jaccard_similarity(set1: set, set2: set) -> float:
    """Calculate Jaccard similarity between two sets.
    
    Args:
        set1: First set
        set2: Second set
    
    Returns:
        Jaccard similarity coefficient (0-1)
    """
    if not set1 or not set2:
        return 0.0
    
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    
    return intersection / union if union > 0 else 0.0