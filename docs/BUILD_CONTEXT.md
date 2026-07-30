# Araha — Build Context

## Project Identity
- Name: Araha
- Domain: Nigeria domestic flight fare tracking + crowdsourced boarding status
- Interface: WhatsApp-first (Twilio), with admin web dashboard
- Stack: FastAPI + SQLAlchemy + Postgres + APScheduler + Docker/Railway

## Architecture Overview
```
docker-compose / Railway
├── db       Postgres 15 (fares, subscriptions, reports, scores, alert history)
├── app      FastAPI: /webhook/whatsapp (Twilio inbound), /admin, /health
└── worker   APScheduler: FX refresh + fare ingestion + price-drop pushes
```

## Key Design Decisions
- Fare ingestion and boarding status are **decoupled** — different services (`fare_service` vs `status_service`), different trust models, no shared logic
- Google Flights is the PRIMARY fare source (via `fli` library); Amadeus is secondary (no NG domestic carrier coverage)
- Mock ingestor is the default for dev (`FARE_SOURCE=mock`)
- Boarding status trust: 1 report = pending, 2+ distinct reporters same state = confirmed, conflicts = disputed
- Date-aware fares: rolling 30-day window with sampling, or specific-date queries
- NDPA-compliant: UNSUBSCRIBE deletes/anonymizes personal data

## What's REAL vs MOCKED
| Component | Status |
|---|---|
| WhatsApp inbound webhook | **REAL** |
| WhatsApp outbound pushes | **REAL**; console fallback |
| Price-drop alert worker | **REAL** |
| Boarding-status confirm → push | **REAL** |
| FX rates (open.er-api.com) | **REAL** with cached fallback |
| Admin view (/admin) | **REAL** (HTTP Basic Auth) |
| Fare data (mock) | **REAL** code, fake prices |
| Fare data (Google Flights) | **REAL** via fli library |
| Fare data (Amadeus) | **REAL** code, secondary |

## Active Phase
Phase 3 — Production Readiness & Hardening

## Repo Structure
```
app/
  main.py           — FastAPI app, endpoints, startup
  core/database.py  — SQLAlchemy engine, session
  models/models.py  — DB models (subscriptions, reports, etc.)
  services/
    bot_router.py   — Command parsing & routing
    fare_ingestor.py  — Fare data sources (mock, google, amadeus, hybrid)
    fare_service.py   — Fare comparison & alert logic
    notifier.py       — WhatsApp push + console fallback
    status_service.py — Boarding status trust model
  workers/
    fare_worker.py  — APScheduler: fare polling, FX, price-drop alerts
  admin/views.py    — Admin dashboard rendering
  utils/            — Helpers (data_deletion, etc.)
tests/              — 226 passing tests
docs/               — Project OS files
```

## Environment Variables
See `.env.example` for full list. Key ones: FARE_SOURCE, ADMIN_USER, ADMIN_PASSWORD, TWILIO_*, DATABASE_URL.

## Running
- `docker-compose up --build`
- `python -m uvicorn app.main:app --reload`
- `python -m app.workers.fare_worker`
- Tests: `python -m pytest tests -v`
