#!/usr/bin/env python
"""Command-line interface for search engine management."""

import asyncio
import sys
from pathlib import Path
from typing import Optional

import click
import structlog
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.search.autocomplete import AutocompleteIndex
from app.search.index import SearchIndex
from app.storage.db import Database
from app.storage.export import DataExporter
from app.utils.logging import setup_logging

logger = setup_logging()


@click.group()
def cli():
    """Search Engine Management CLI."""
    pass


@cli.command()
@click.option('--db-path', default=settings.DATABASE_PATH, help='Database path')
def init_db(db_path: str):
    """Initialize the database."""
    async def _init():
        db = Database(db_path)
        await db.initialize()
        
        index = SearchIndex(db)
        await index.initialize()
        
        logger.info(f"Database initialized at {db_path}")
        await db.close()
    
    asyncio.run(_init())


@cli.command()
@click.option('--seeds', default='seeds.txt', help='Seeds file path')
@click.option('--spider', default='seed_spider', help='Spider to use')
@click.option('--continuous', is_flag=True, help='Run continuously')
def crawl(seeds: str, spider: str, continuous: bool):
    """Start web crawler."""
    logger.info(f"Starting crawler with spider: {spider}")
    
    # Configure Scrapy settings
    crawler_settings = get_project_settings()
    crawler_settings.update({
        'DATABASE_PATH': settings.DATABASE_PATH,
        'ALLOWLIST_PATH': settings.ALLOWLIST_PATH,
        'BLOCKLIST_PATH': settings.BLOCKLIST_PATH,
        'USER_AGENT': settings.CRAWLER_USER_AGENT,
        'ROBOTSTXT_OBEY': settings.ROBOTS_TXT_OBEY,
        'CONCURRENT_REQUESTS': settings.CRAWLER_CONCURRENT_REQUESTS,
        'DOWNLOAD_DELAY': settings.CRAWLER_DOWNLOAD_DELAY,
    })
    
    process = CrawlerProcess(crawler_settings)
    
    if spider == 'seed_spider':
        from app.crawler.spiders.seed_spider import SeedSpider
        process.crawl(SeedSpider, seeds_file=seeds)
    elif spider == 'sitemap_spider':
        from app.crawler.spiders.sitemap_spider import SitemapCrawlSpider
        # Load sitemap URLs from seeds file
        sitemap_urls = []
        seeds_path = Path(seeds)
        if seeds_path.exists():
            with open(seeds_path) as f:
                sitemap_urls = [line.strip() for line in f if line.strip()]
        process.crawl(SitemapCrawlSpider, sitemap_urls=sitemap_urls)
    else:
        logger.error(f"Unknown spider: {spider}")
        return
    
    if continuous:
        while True:
            process.start(stop_after_crawl=True)
            logger.info("Crawler cycle completed, restarting...")
            asyncio.sleep(3600)  # Wait 1 hour between cycles
    else:
        process.start()


@cli.command()
@click.option('--rebuild', is_flag=True, help='Rebuild FTS index')
def index(rebuild: bool):
    """Build or rebuild search index."""
    async def _index():
        db = Database(settings.DATABASE_PATH)
        await db.initialize()
        
        index = SearchIndex(db)
        await index.initialize()
        
        if rebuild:
            logger.info("Rebuilding FTS index...")
            await index.rebuild_fts()
        
        stats = await index.get_stats()
        logger.info(f"Index stats: {stats}")
        
        await db.close()
    
    asyncio.run(_index())


@cli.command()
def reindex():
    """Reindex all documents."""
    async def _reindex():
        db = Database(settings.DATABASE_PATH)
        await db.initialize()
        
        index = SearchIndex(db)
        await index.initialize()
        
        logger.info("Reindexing all documents...")
        await index.rebuild_fts()
        
        stats = await index.get_stats()
        logger.info(f"Reindex complete. Stats: {stats}")
        
        await db.close()
    
    asyncio.run(_reindex())


@cli.command()
@click.option('--format', type=click.Choice(['sqlite', 'jsonl', 'json']), default='jsonl')
@click.option('--output', required=True, help='Output file path')
@click.option('--table', default='documents', help='Table to export')
@click.option('--limit', type=int, help='Maximum records to export')
def export(format: str, output: str, table: str, limit: Optional[int]):
    """Export database content."""
    async def _export():
        db = Database(settings.DATABASE_PATH)
        await db.initialize()
        
        exporter = DataExporter(db)
        
        if format == 'sqlite':
            success = await exporter.export_sqlite(output)
        elif format == 'jsonl':
            success = await exporter.export_jsonl(output, table, limit)
        elif format == 'json':
            success = await exporter.export_json(output, table, limit)
        else:
            logger.error(f"Unknown format: {format}")
            success = False
        
        if success:
            logger.info(f"Export completed: {output}")
        else:
            logger.error("Export failed")
        
        await db.close()
    
    asyncio.run(_export())


@cli.command()
@click.option('--input', required=True, help='Input file path')
@click.option('--table', default='documents', help='Target table')
def import_data(input: str, table: str):
    """Import data from file."""
    async def _import():
        db = Database(settings.DATABASE_PATH)
        await db.initialize()
        
        exporter = DataExporter(db)
        
        if input.endswith('.jsonl'):
            count = await exporter.import_jsonl(input, table)
            logger.info(f"Imported {count} records")
        else:
            logger.error("Only JSONL format is supported for import")
        
        await db.close()
    
    asyncio.run(_import())


@cli.command()
@click.option('--url', help='URL to deindex')
@click.option('--site', help='Site to deindex')
@click.option('--hash', help='Content hash to deindex')
def deindex(url: Optional[str], site: Optional[str], hash: Optional[str]):
    """Remove documents from index."""
    async def _deindex():
        db = Database(settings.DATABASE_PATH)
        await db.initialize()
        
        exporter = DataExporter(db)
        
        if url:
            success = await exporter.deindex_url(url)
            if success:
                logger.info(f"Deindexed URL: {url}")
        elif site:
            count = await exporter.deindex_site(site)
            logger.info(f"Deindexed {count} documents from {site}")
        elif hash:
            count = await exporter.deindex_by_hash(hash)
            logger.info(f"Deindexed {count} documents with hash {hash}")
        else:
            logger.error("Specify --url, --site, or --hash")
        
        await db.close()
    
    asyncio.run(_deindex())


@cli.command()
def vacuum():
    """Vacuum database to reclaim space."""
    async def _vacuum():
        db = Database(settings.DATABASE_PATH)
        await db.initialize()
        
        size_before = await db.get_size()
        logger.info(f"Database size before: {size_before:.2f} MB")
        
        success = await db.vacuum()
        
        if success:
            size_after = await db.get_size()
            saved = size_before - size_after
            logger.info(f"Database size after: {size_after:.2f} MB")
            logger.info(f"Space saved: {saved:.2f} MB")
        else:
            logger.error("Vacuum failed")
        
        await db.close()
    
    asyncio.run(_vacuum())


@cli.command()
@click.option('--output', default='./data/autocomplete.json', help='Output file')
def build_autocomplete(output: str):
    """Build autocomplete index from titles."""
    async def _build():
        db = Database(settings.DATABASE_PATH)
        await db.initialize()
        
        # Get all titles
        titles = await db.fetchall("SELECT DISTINCT title FROM documents WHERE title IS NOT NULL")
        
        if not titles:
            logger.warning("No titles found in database")
            await db.close()
            return
        
        # Build autocomplete index
        autocomplete = AutocompleteIndex()
        await autocomplete.build_from_titles([t['title'] for t in titles])
        
        # Save to file
        await autocomplete.save(output)
        logger.info(f"Autocomplete index saved to {output}")
        
        await db.close()
    
    asyncio.run(_build())


@cli.command()
def stats():
    """Show database and index statistics."""
    async def _stats():
        db = Database(settings.DATABASE_PATH)
        await db.initialize()
        
        index = SearchIndex(db)
        await index.initialize()
        
        stats = await index.get_stats()
        
        click.echo("\n=== Search Engine Statistics ===\n")
        click.echo(f"Total Documents: {stats.get('total_documents', 0):,}")
        click.echo(f"Database Size: {stats.get('size_mb', 0):.2f} MB")
        click.echo(f"Last Updated: {stats.get('last_updated', 'Never')}")
        
        click.echo("\n=== Languages ===")
        for lang, count in stats.get('languages', {}).items():
            click.echo(f"  {lang}: {count:,}")
        
        click.echo("\n=== Top Sites ===")
        for site, count in stats.get('top_sites', {}).items():
            click.echo(f"  {site}: {count:,}")
        
        await db.close()
    
    asyncio.run(_stats())


def main():
    """Main entry point."""
    cli()


if __name__ == '__main__':
    main()