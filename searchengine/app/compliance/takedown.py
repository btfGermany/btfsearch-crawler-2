"""Takedown request handling."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

import structlog

from app.storage.db import Database

logger = structlog.get_logger()


class TakedownStatus(Enum):
    """Takedown request status."""
    
    PENDING = "pending"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class TakedownQueue:
    """Manage takedown requests."""
    
    def __init__(self, db: Database):
        """Initialize takedown queue.
        
        Args:
            db: Database instance
        """
        self.db = db
    
    async def initialize(self) -> None:
        """Initialize takedown tables."""
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS takedown_requests (
                request_id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                email TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP,
                completed_at TIMESTAMP,
                reviewer_notes TEXT
            )
        """)
        
        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_takedown_status 
            ON takedown_requests(status)
        """)
        
        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_takedown_created 
            ON takedown_requests(created_at)
        """)
    
    async def submit(
        self,
        url: str,
        email: str,
        reason: str
    ) -> str:
        """Submit a takedown request.
        
        Args:
            url: URL to take down
            email: Requester email
            reason: Reason for takedown
        
        Returns:
            Request ID
        """
        request_id = str(uuid.uuid4())
        
        await self.db.execute("""
            INSERT INTO takedown_requests 
            (request_id, url, email, reason, status)
            VALUES (?, ?, ?, ?, ?)
        """, (request_id, url, email, reason, TakedownStatus.PENDING.value))
        
        logger.info(f"Takedown request submitted: {request_id} for {url}")
        
        return request_id
    
    async def get_pending(self, limit: int = 100) -> List[Dict]:
        """Get pending takedown requests.
        
        Args:
            limit: Maximum requests to return
        
        Returns:
            List of pending requests
        """
        return await self.db.fetchall("""
            SELECT * FROM takedown_requests
            WHERE status = ?
            ORDER BY created_at ASC
            LIMIT ?
        """, (TakedownStatus.PENDING.value, limit))
    
    async def get_request(self, request_id: str) -> Optional[Dict]:
        """Get a specific takedown request.
        
        Args:
            request_id: Request ID
        
        Returns:
            Request details or None
        """
        return await self.db.fetchone("""
            SELECT * FROM takedown_requests
            WHERE request_id = ?
        """, (request_id,))
    
    async def update_status(
        self,
        request_id: str,
        status: TakedownStatus,
        notes: Optional[str] = None
    ) -> bool:
        """Update takedown request status.
        
        Args:
            request_id: Request ID
            status: New status
            notes: Reviewer notes
        
        Returns:
            True if updated
        """
        try:
            timestamp_field = None
            timestamp_value = None
            
            if status == TakedownStatus.REVIEWING:
                timestamp_field = "reviewed_at"
                timestamp_value = datetime.now()
            elif status in [TakedownStatus.COMPLETED, TakedownStatus.REJECTED]:
                timestamp_field = "completed_at"
                timestamp_value = datetime.now()
            
            if timestamp_field:
                await self.db.execute(f"""
                    UPDATE takedown_requests
                    SET status = ?, {timestamp_field} = ?, reviewer_notes = ?
                    WHERE request_id = ?
                """, (status.value, timestamp_value, notes, request_id))
            else:
                await self.db.execute("""
                    UPDATE takedown_requests
                    SET status = ?, reviewer_notes = ?
                    WHERE request_id = ?
                """, (status.value, notes, request_id))
            
            logger.info(f"Updated takedown request {request_id} to {status.value}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to update takedown status: {e}")
            return False
    
    async def process_approved(self, request_id: str) -> bool:
        """Process an approved takedown request.
        
        Args:
            request_id: Request ID
        
        Returns:
            True if processed
        """
        try:
            # Get request details
            request = await self.get_request(request_id)
            if not request:
                return False
            
            # Delete from index
            await self.db.execute("""
                DELETE FROM documents
                WHERE url = ?
            """, (request['url'],))
            
            # Update status
            await self.update_status(
                request_id,
                TakedownStatus.COMPLETED,
                "Content removed from index"
            )
            
            logger.info(f"Processed takedown for {request['url']}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to process takedown: {e}")
            return False
    
    async def get_statistics(self) -> Dict:
        """Get takedown statistics.
        
        Returns:
            Statistics dictionary
        """
        stats = await self.db.fetchone("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'reviewing' THEN 1 ELSE 0 END) as reviewing,
                SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved,
                SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed
            FROM takedown_requests
        """)
        
        return stats if stats else {}
    
    async def cleanup_old_requests(self, days: int = 90) -> int:
        """Clean up old completed requests.
        
        Args:
            days: Days to keep completed requests
        
        Returns:
            Number of deleted requests
        """
        try:
            result = await self.db.execute("""
                DELETE FROM takedown_requests
                WHERE status IN ('completed', 'rejected')
                AND completed_at < datetime('now', '-' || ? || ' days')
            """, (days,))
            
            count = result.rowcount if result else 0
            
            if count > 0:
                logger.info(f"Cleaned up {count} old takedown requests")
            
            return count
        
        except Exception as e:
            logger.error(f"Failed to cleanup old requests: {e}")
            return 0