"""Structured logging configuration."""

import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import structlog
from structlog.processors import CallsiteParameter, CallsiteParameterAdder


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    json_logs: bool = True
) -> structlog.BoundLogger:
    """Setup structured logging.
    
    Args:
        log_level: Logging level
        log_file: Optional log file path
        json_logs: Whether to output JSON logs
    
    Returns:
        Configured logger
    """
    # Configure Python logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper())
    )
    
    # Processors for structlog
    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        CallsiteParameterAdder(
            parameters=[
                CallsiteParameter.FILENAME,
                CallsiteParameter.LINENO,
                CallsiteParameter.FUNC_NAME,
            ]
        ),
    ]
    
    if json_logs:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    
    # Configure structlog
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Setup file logging if specified
    if log_file:
        setup_file_logging(log_file, log_level)
    
    return structlog.get_logger()


def setup_file_logging(
    log_file: str,
    log_level: str = "INFO",
    max_bytes: int = 10485760,  # 10MB
    backup_count: int = 5
) -> None:
    """Setup file logging with rotation.
    
    Args:
        log_file: Path to log file
        log_level: Logging level
        max_bytes: Maximum file size
        backup_count: Number of backup files
    """
    from logging.handlers import RotatingFileHandler
    
    # Create log directory if needed
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create rotating file handler
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count
    )
    
    file_handler.setLevel(getattr(logging, log_level.upper()))
    
    # JSON formatter for file logs
    formatter = logging.Formatter(
        '{"time": "%(asctime)s", "level": "%(levelname)s", '
        '"logger": "%(name)s", "message": "%(message)s"}'
    )
    file_handler.setFormatter(formatter)
    
    # Add handler to root logger
    logging.getLogger().addHandler(file_handler)


class RequestIDMiddleware:
    """Middleware to add request ID to logs."""
    
    def __init__(self, app):
        """Initialize middleware.
        
        Args:
            app: ASGI application
        """
        self.app = app
    
    async def __call__(self, scope, receive, send):
        """Add request ID to context.
        
        Args:
            scope: ASGI scope
            receive: Receive channel
            send: Send channel
        """
        if scope["type"] == "http":
            request_id = str(uuid.uuid4())
            
            # Add to structlog context
            structlog.contextvars.bind_contextvars(
                request_id=request_id
            )
            
            # Add to response headers
            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append((b"x-request-id", request_id.encode()))
                    message["headers"] = headers
                await send(message)
            
            await self.app(scope, receive, send_wrapper)
            
            # Clear context
            structlog.contextvars.clear_contextvars()
        else:
            await self.app(scope, receive, send)


class LogRotator:
    """Manage log rotation and cleanup."""
    
    def __init__(
        self,
        log_dir: str,
        retention_days: int = 30,
        max_size_mb: int = 1000
    ):
        """Initialize log rotator.
        
        Args:
            log_dir: Log directory
            retention_days: Days to keep logs
            max_size_mb: Maximum total size
        """
        self.log_dir = Path(log_dir)
        self.retention_days = retention_days
        self.max_size_mb = max_size_mb
    
    async def cleanup(self) -> Dict[str, Any]:
        """Clean up old log files.
        
        Returns:
            Cleanup statistics
        """
        if not self.log_dir.exists():
            return {"deleted": 0, "size_freed": 0}
        
        deleted = 0
        size_freed = 0
        current_time = datetime.now()
        
        for log_file in self.log_dir.glob("*.log*"):
            # Check age
            file_age = current_time - datetime.fromtimestamp(log_file.stat().st_mtime)
            
            if file_age.days > self.retention_days:
                size_freed += log_file.stat().st_size
                log_file.unlink()
                deleted += 1
        
        return {
            "deleted": deleted,
            "size_freed_mb": size_freed / 1024 / 1024
        }
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get log directory statistics.
        
        Returns:
            Log statistics
        """
        if not self.log_dir.exists():
            return {"total_files": 0, "total_size_mb": 0}
        
        total_files = 0
        total_size = 0
        
        for log_file in self.log_dir.glob("*.log*"):
            total_files += 1
            total_size += log_file.stat().st_size
        
        return {
            "total_files": total_files,
            "total_size_mb": total_size / 1024 / 1024,
            "retention_days": self.retention_days
        }