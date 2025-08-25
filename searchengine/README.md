# Lightweight Web Search Engine

A fast, legally compliant web search engine built with Python, capable of indexing 100,000-500,000 pages.

## Features

- **Legal Compliance**: Strict robots.txt respect, GDPR compliant, takedown mechanism
- **Fast Search**: SQLite FTS5 with BM25 ranking, optional semantic search
- **Scalable Crawler**: Scrapy-based with rate limiting and duplicate detection
- **Export/Import**: Full database export capability
- **EU/DE Compliant**: Impressum, Datenschutzerklärung, proper logging

## Setup

### Using Docker (Recommended)

```bash
docker-compose up -d
```

### Manual Setup

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python scripts/cli.py init-db
```

## Configuration

Copy `.env.example` to `.env` and adjust settings:

```bash
cp .env.example .env
```

Key settings:
- `EMBEDDINGS_ENABLED`: Enable/disable semantic search
- `REDIS_URL`: Optional Redis cache
- `RATE_LIMIT_*`: Crawler rate limits
- `ALLOWLIST_PATH`: Path to domain allowlist

## Crawling Workflow

1. Add seed URLs to `seeds.txt`
2. Run crawler:
```bash
python scripts/cli.py crawl --seeds seeds.txt
```

3. Build search index:
```bash
python scripts/cli.py index
```

4. Build autocomplete:
```bash
python scripts/cli.py build-autocomplete
```

## API Endpoints

- `GET /search?q=query&page=1` - Search with pagination
- `GET /autocomplete?q=prefix` - Query suggestions
- `GET /status` - Health check and stats
- `POST /report` - Takedown requests
- `GET /impressum` - Legal notice
- `GET /datenschutz` - Privacy policy
- `GET /robots.txt` - Crawler rules

## Compliance

### Crawler Behavior
- Respects robots.txt strictly
- Uses custom User-Agent
- Implements exponential backoff
- Domain-based rate limiting

### Data Protection
- IP anonymization in logs
- Configurable log retention
- GDPR-compliant data handling
- Takedown mechanism

### Content Licensing
- Only indexes publicly accessible content
- Stores only snippets, not full text
- Tracks content licenses
- Allowlist/blocklist mechanism

## Export/Import

Export full database:
```bash
python scripts/cli.py export --format sqlite --output backup.db
```

Export as JSONL:
```bash
python scripts/cli.py export --format jsonl --output data.jsonl
```

Import data:
```bash
python scripts/cli.py import --input data.jsonl
```

## Deployment

### Production with HTTPS

1. Deploy with docker-compose
2. Configure nginx reverse proxy:

```nginx
server {
    listen 443 ssl http2;
    server_name search.example.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Operations

### Monitoring
- Prometheus metrics at `/metrics`
- Structured JSON logs
- Health endpoint at `/status`

### Maintenance
```bash
# Vacuum database
python scripts/cli.py vacuum

# Deindex URL
python scripts/cli.py deindex --url https://example.com/page

# Reindex all
python scripts/cli.py reindex
```

## Testing

```bash
pytest tests/
mypy app/
ruff check app/
```

## License

MIT License - See LICENSE file for details