# Dev Rules — Araha

## Coding Style
- Python: PEP 8, type hints on all public functions
- FastAPI: async for I/O-bound endpoints, sync for CPU-bound
- SQLAlchemy: ORM queries in services, raw SQL only for migrations
- Tests: pytest, one file per module/domain

## Commit Convention
- `scope: message` (e.g., `fare: add retry logic to GoogleFlightsIngestor`)
- Imperative mood, no period

## Conventions
- Logging: use `logger = logging.getLogger("araha.<module>")`
- Env vars: all via `pydantic-settings` or `os.getenv`, documented in .env.example
- Config: pydantic BaseSettings classes in `app/core/`
- DB migrations: lightweight ALTER TABLE in `main.py` startup (no Alembic yet)

## Testing
- `python -m pytest tests -v`
- `FARE_SOURCE=mock` for dev (default)
- New features require tests in the matching `tests/test_*.py` file

## Safety Rules
- Never hardcode API keys or secrets
- Admin routes require HTTP Basic Auth in production
- Google Flights results filtered through NIGERIAN_DOMESTIC_AIRLINES allow-list
- NDPA compliance: user data deletion on UNSUBSCRIBE
