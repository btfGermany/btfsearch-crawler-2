"""API models and schemas."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, HttpUrl


class SearchResult(BaseModel):
    """Single search result."""
    
    url: HttpUrl
    title: str
    snippet: str
    site: str
    lang: Optional[str] = None
    score: float = Field(ge=0.0)
    fetch_date: datetime


class SearchRequest(BaseModel):
    """Search request model."""
    
    query: str = Field(..., min_length=1, max_length=500)
    page: int = Field(1, ge=1)
    page_size: int = Field(10, ge=1, le=100)
    lang: Optional[str] = None
    site: Optional[str] = None


class SearchResponse(BaseModel):
    """Search response model."""
    
    query: str
    results: List[SearchResult]
    total: int
    page: int
    page_size: int
    took_ms: int


class AutocompleteResponse(BaseModel):
    """Autocomplete response model."""
    
    query: str
    suggestions: List[str]


class ReportRequest(BaseModel):
    """Takedown report request."""
    
    url: HttpUrl
    email: EmailStr
    reason: str = Field(..., min_length=10, max_length=1000)


class StatusResponse(BaseModel):
    """Service status response."""
    
    status: str
    version: str
    index: dict
    cache: dict
    embeddings: dict