"""Database export and import functionality."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from app.storage.db import Database

logger = structlog.get_logger()


class DataExporter:
    """Export and import database content."""
    
    def __init__(self, db: Database):
        """Initialize exporter.
        
        Args:
            db: Database instance
        """
        self.db = db
    
    async def export_sqlite(self, output_path: str) -> bool:
        """Export full SQLite database.
        
        Args:
            output_path: Path for output file
        
        Returns:
            True if successful
        """
        try:
            # Use database backup functionality
            success = await self.db.backup(output_path)
            
            if success:
                logger.info(f"Database exported to {output_path}")
            
            return success
        
        except Exception as e:
            logger.error(f"SQLite export failed: {e}")
            return False
    
    async def export_jsonl(
        self,
        output_path: str,
        table: str = "documents",
        limit: Optional[int] = None
    ) -> bool:
        """Export data as JSONL (JSON Lines).
        
        Args:
            output_path: Path for output file
            table: Table to export
            limit: Maximum records to export
        
        Returns:
            True if successful
        """
        try:
            # Build query
            query = f"SELECT * FROM {table}"
            if limit:
                query += f" LIMIT {limit}"
            
            # Fetch data
            rows = await self.db.fetchall(query)
            
            # Write JSONL
            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output, 'w', encoding='utf-8') as f:
                for row in rows:
                    # Convert row to JSON
                    json_line = json.dumps(row, ensure_ascii=False, default=str)
                    f.write(json_line + '\n')
            
            logger.info(f"Exported {len(rows)} records to {output_path}")
            return True
        
        except Exception as e:
            logger.error(f"JSONL export failed: {e}")
            return False
    
    async def export_json(
        self,
        output_path: str,
        table: str = "documents",
        limit: Optional[int] = None
    ) -> bool:
        """Export data as JSON.
        
        Args:
            output_path: Path for output file
            table: Table to export
            limit: Maximum records to export
        
        Returns:
            True if successful
        """
        try:
            # Build query
            query = f"SELECT * FROM {table}"
            if limit:
                query += f" LIMIT {limit}"
            
            # Fetch data
            rows = await self.db.fetchall(query)
            
            # Get metadata
            metadata = {
                "table": table,
                "count": len(rows),
                "export_date": str(datetime.now()),
                "database_size_mb": await self.db.get_size()
            }
            
            # Prepare export data
            export_data = {
                "metadata": metadata,
                "data": rows
            }
            
            # Write JSON
            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2, default=str)
            
            logger.info(f"Exported {len(rows)} records to {output_path}")
            return True
        
        except Exception as e:
            logger.error(f"JSON export failed: {e}")
            return False
    
    async def import_jsonl(
        self,
        input_path: str,
        table: str = "documents",
        batch_size: int = 100
    ) -> int:
        """Import data from JSONL file.
        
        Args:
            input_path: Path to input file
            table: Target table
            batch_size: Batch size for inserts
        
        Returns:
            Number of imported records
        """
        try:
            input_file = Path(input_path)
            if not input_file.exists():
                logger.error(f"Input file not found: {input_path}")
                return 0
            
            imported = 0
            batch = []
            
            with open(input_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    
                    try:
                        record = json.loads(line)
                        batch.append(record)
                        
                        if len(batch) >= batch_size:
                            await self._import_batch(table, batch)
                            imported += len(batch)
                            batch = []
                    
                    except json.JSONDecodeError as e:
                        logger.warning(f"Skipping invalid JSON line: {e}")
            
            # Import remaining batch
            if batch:
                await self._import_batch(table, batch)
                imported += len(batch)
            
            logger.info(f"Imported {imported} records from {input_path}")
            return imported
        
        except Exception as e:
            logger.error(f"JSONL import failed: {e}")
            return 0
    
    async def _import_batch(self, table: str, records: List[Dict[str, Any]]) -> None:
        """Import a batch of records.
        
        Args:
            table: Target table
            records: Records to import
        """
        if not records:
            return
        
        # Get columns from first record
        columns = list(records[0].keys())
        placeholders = ','.join(['?' for _ in columns])
        columns_str = ','.join(columns)
        
        # Prepare insert query
        insert_sql = f"""
            INSERT OR REPLACE INTO {table} ({columns_str})
            VALUES ({placeholders})
        """
        
        # Prepare data
        data = []
        for record in records:
            values = [record.get(col) for col in columns]
            data.append(values)
        
        # Execute batch insert
        await self.db.executemany(insert_sql, data)
    
    async def deindex_url(self, url: str) -> bool:
        """Remove a URL from the index.
        
        Args:
            url: URL to remove
        
        Returns:
            True if removed
        """
        try:
            result = await self.db.execute(
                "DELETE FROM documents WHERE url = ?",
                (url,)
            )
            
            if result and result.rowcount > 0:
                logger.info(f"Deindexed URL: {url}")
                return True
            else:
                logger.warning(f"URL not found in index: {url}")
                return False
        
        except Exception as e:
            logger.error(f"Failed to deindex URL: {e}")
            return False
    
    async def deindex_by_hash(self, content_hash: str) -> int:
        """Remove documents by content hash.
        
        Args:
            content_hash: Content hash
        
        Returns:
            Number of removed documents
        """
        try:
            result = await self.db.execute(
                "DELETE FROM documents WHERE hash = ?",
                (content_hash,)
            )
            
            count = result.rowcount if result else 0
            
            if count > 0:
                logger.info(f"Deindexed {count} documents with hash: {content_hash}")
            
            return count
        
        except Exception as e:
            logger.error(f"Failed to deindex by hash: {e}")
            return 0
    
    async def deindex_site(self, site: str) -> int:
        """Remove all documents from a site.
        
        Args:
            site: Site domain
        
        Returns:
            Number of removed documents
        """
        try:
            result = await self.db.execute(
                "DELETE FROM documents WHERE site = ?",
                (site,)
            )
            
            count = result.rowcount if result else 0
            
            if count > 0:
                logger.info(f"Deindexed {count} documents from site: {site}")
            
            return count
        
        except Exception as e:
            logger.error(f"Failed to deindex site: {e}")
            return 0


from datetime import datetime