"""Database connection and management using apsw."""

import asyncio
import apsw
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import structlog

logger = structlog.get_logger()


class Database:
    """SQLite database wrapper with connection pooling and async support."""
    
    def __init__(
        self,
        database_path: str,
        pool_size: int = 10,
        timeout: float = 30.0
    ):
        """Initialize database.
        
        Args:
            database_path: Path to SQLite database file
            pool_size: Connection pool size
            timeout: Query timeout in seconds
        """
        self.database_path = Path(database_path)
        self.pool_size = pool_size
        self.timeout = timeout
        self._connections: List[apsw.Connection] = []
        self._available: asyncio.Queue = asyncio.Queue(maxsize=pool_size)
        self._lock = asyncio.Lock()
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize database and connection pool."""
        if self._initialized:
            return
        
        # Create database directory if needed
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create connection pool
        for _ in range(self.pool_size):
            conn = self._create_connection()
            self._connections.append(conn)
            await self._available.put(conn)
        
        # Initialize schema
        async with self.get_connection() as conn:
            self._configure_connection(conn)
        
        self._initialized = True
        logger.info(f"Database initialized: {self.database_path}")
    
    def _create_connection(self) -> apsw.Connection:
        """Create a new database connection.
        
        Returns:
            Database connection
        """
        conn = apsw.Connection(str(self.database_path))
        self._configure_connection(conn)
        return conn
    
    def _configure_connection(self, conn: apsw.Connection) -> None:
        """Configure database connection with optimal settings.
        
        Args:
            conn: Database connection
        """
        cursor = conn.cursor()
        
        # Performance optimizations
        cursor.execute("PRAGMA journal_mode = WAL")  # Write-Ahead Logging
        cursor.execute("PRAGMA synchronous = NORMAL")  # Faster writes
        cursor.execute("PRAGMA cache_size = -64000")  # 64MB cache
        cursor.execute("PRAGMA page_size = 4096")  # 4KB pages
        cursor.execute("PRAGMA mmap_size = 268435456")  # 256MB memory map
        cursor.execute("PRAGMA temp_store = MEMORY")  # Temp tables in memory
        cursor.execute("PRAGMA foreign_keys = ON")  # Enable foreign keys
        
        # Set busy timeout
        cursor.execute(f"PRAGMA busy_timeout = {int(self.timeout * 1000)}")
    
    @asynccontextmanager
    async def get_connection(self):
        """Get a connection from the pool.
        
        Yields:
            Database connection
        """
        conn = await self._available.get()
        try:
            yield conn
        finally:
            await self._available.put(conn)
    
    async def execute(
        self,
        sql: str,
        params: Optional[Union[tuple, dict]] = None
    ) -> apsw.Cursor:
        """Execute a SQL statement.
        
        Args:
            sql: SQL statement
            params: Query parameters
        
        Returns:
            Cursor with results
        """
        async with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Run in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            
            def _execute():
                if params:
                    return cursor.execute(sql, params)
                else:
                    return cursor.execute(sql)
            
            result = await loop.run_in_executor(None, _execute)
            return result
    
    async def executemany(
        self,
        sql: str,
        params_list: List[Union[tuple, dict]]
    ) -> None:
        """Execute a SQL statement multiple times.
        
        Args:
            sql: SQL statement
            params_list: List of parameter sets
        """
        async with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Run in thread pool
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                cursor.executemany,
                sql,
                params_list
            )
    
    async def fetchone(
        self,
        sql: str,
        params: Optional[Union[tuple, dict]] = None
    ) -> Optional[Dict[str, Any]]:
        """Fetch one row as dictionary.
        
        Args:
            sql: SQL query
            params: Query parameters
        
        Returns:
            Row as dictionary or None
        """
        async with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Set row factory for dict results
            conn.setrowtrace(self._row_factory)
            
            loop = asyncio.get_event_loop()
            
            def _fetch():
                if params:
                    cursor.execute(sql, params)
                else:
                    cursor.execute(sql)
                return cursor.fetchone()
            
            result = await loop.run_in_executor(None, _fetch)
            
            # Reset row factory
            conn.setrowtrace(None)
            
            return result
    
    async def fetchall(
        self,
        sql: str,
        params: Optional[Union[tuple, dict]] = None
    ) -> List[Dict[str, Any]]:
        """Fetch all rows as list of dictionaries.
        
        Args:
            sql: SQL query
            params: Query parameters
        
        Returns:
            List of rows as dictionaries
        """
        async with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Set row factory for dict results
            conn.setrowtrace(self._row_factory)
            
            loop = asyncio.get_event_loop()
            
            def _fetch():
                if params:
                    cursor.execute(sql, params)
                else:
                    cursor.execute(sql)
                return cursor.fetchall()
            
            results = await loop.run_in_executor(None, _fetch)
            
            # Reset row factory
            conn.setrowtrace(None)
            
            return results if results else []
    
    def _row_factory(self, cursor: apsw.Cursor, row: tuple) -> Dict[str, Any]:
        """Convert row tuple to dictionary.
        
        Args:
            cursor: Database cursor
            row: Row tuple
        
        Returns:
            Row as dictionary
        """
        return {
            description[0]: value
            for description, value in zip(cursor.getdescription(), row)
        }
    
    async def transaction(self):
        """Create a transaction context manager.
        
        Yields:
            Transaction connection
        """
        async with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN")
            try:
                yield conn
                cursor.execute("COMMIT")
            except Exception:
                cursor.execute("ROLLBACK")
                raise
    
    async def backup(self, backup_path: str) -> bool:
        """Backup database to file.
        
        Args:
            backup_path: Path for backup file
        
        Returns:
            True if successful
        """
        try:
            backup_db = apsw.Connection(backup_path)
            
            async with self.get_connection() as conn:
                with backup_db.backup("main", conn, "main") as backup:
                    while not backup.done:
                        backup.step(100)
                        await asyncio.sleep(0.01)
            
            backup_db.close()
            logger.info(f"Database backed up to {backup_path}")
            return True
        
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            return False
    
    async def vacuum(self) -> bool:
        """Vacuum database to reclaim space.
        
        Returns:
            True if successful
        """
        try:
            async with self.get_connection() as conn:
                cursor = conn.cursor()
                
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, cursor.execute, "VACUUM")
                await loop.run_in_executor(None, cursor.execute, "ANALYZE")
            
            logger.info("Database vacuumed and analyzed")
            return True
        
        except Exception as e:
            logger.error(f"Vacuum failed: {e}")
            return False
    
    async def get_size(self) -> float:
        """Get database size in MB.
        
        Returns:
            Size in megabytes
        """
        try:
            result = await self.fetchone("""
                SELECT page_count * page_size / 1024.0 / 1024.0 as size_mb
                FROM pragma_page_count(), pragma_page_size()
            """)
            return result["size_mb"] if result else 0.0
        except Exception:
            return 0.0
    
    async def close(self) -> None:
        """Close all database connections."""
        for conn in self._connections:
            try:
                conn.close()
            except Exception as e:
                logger.error(f"Error closing connection: {e}")
        
        self._connections.clear()
        self._initialized = False
        logger.info("Database connections closed")