# NaijaFly — Nigeria Flight Fare Tracker + Crowdsourced Boarding Status

WhatsApp-first fare alerts and passenger-reported flight status for **Nigerian domestic routes**.
The full loop is real end-to-end: **a message in triggers a reply, a status escalation
triggers a push, a fare drop triggers a push.**

## Scope

NaijaFly tracks **Nigeria-domestic flights only** — all routes are between Nigerian
airports (LOS, ABV, PHC, ENU, BNI, KAN, CBQ, ILR, QOW, AKR). All fares are in NGN.

**Why not West Africa-wide?** Cross-border routes (Accra, Dakar, Abidjan, Freetown)
were removed to focus on the market where NaijaFly has the strongest carrier coverage
and the highest demand. Cross-border routes also required multi-currency handling
(GHS, XOF, SLL) that added complexity without proportional value.

**Why is Dana Air removed?** Dana Air (IATA: 9J) was suspended by the Nigerian NCAA
in April 2024 following a runway incident and has ceased operations. Its route
obligations were transferred to NG Eagle, a newer carrier now tracked instead.
Dana Air is kept in `WEST_AFRICAN_AIRLINES` as a historical reference only.

**Why is Amadeus secondary?** Amadeus GDS does not cover any Nigerian domestic carrier
directly (Air Peace, Arik Air, Ibom Air, etc. are not on GDS). Google Flights is the
meaningful real-data path for this scope. Amadeus code is retained for potential
future international route expansion.

## Architecture

```
docker-compose / Railway
├── db       Postgres 15 (fares, subscriptions, reports, scores, alert history)
├── app      FastAPI: /webhook/whatsapp (Twilio inbound), /admin, /health
└── worker   APScheduler: FX refresh + fare ingestion + price-drop pushes
```

Fare ingestion and boarding status stay **decoupled**: different services
(`fare_service` vs `status_service`), different trust models, no shared logic.

## Running it

```bash
# Docker
docker-compose up --build

# Local development
python -m uvicorn app.main:app --reload
python -m app.workers.fare_worker

# Production (Railway via start.sh)
sh start.sh  # runs both web + worker in one process
```

Copy `.env.example` to `.env` and fill in real values to go live. Without Twilio
credentials, pushes go to the container log in CONSOLE mode instead of WhatsApp —
nothing else changes.

## Bot commands

| Message | Effect |
|---|---|
| `SUBSCRIBE LOS ABV` | Fare-drop alerts, rolling 30-day window |
| `SUBSCRIBE LOS ABV 80000` | Same, with target price |
| `SUBSCRIBE LOS ABV 2026-08-15` | Fare-drop alerts for that specific date only |
| `SUBSCRIBE LOS ABV 2026-08-15 80000` | Specific date + target price |
| `FARE LOS ABV` | Cheapest fare in next 30 days |
| `FARE LOS ABV 2026-08-15` | Cheapest fare for that specific date |
| `TRACK P47123 2026-07-20` | Live boarding/gate/delay pushes for that flight |
| `boarding now gate 12` (while tracking) | Files a status report |
| `HELP` | Command list |

### Date-aware fares

- **Rolling window** (default): searches fares across the next 30 days. The worker
  samples dates every `FARE_WINDOW_SAMPLE_DAYS` (default 5) within the window to
  avoid multiplying API calls.
- **Specific date**: pass a YYYY-MM-DD date to search only that date.
- `get_cheapest_fare()` is always scoped — it never compares a cheap Tuesday fare
  against an expensive Christmas fare on the same route.

## Fare data sources

Toggle with the `FARE_SOURCE` env var — `mock` (default), `google`, `amadeus`, or
`hybrid`. No redeploy needed.

| Source | What it provides | API key needed? | Nigeria-domestic relevance |
|---|---|---|---|
| `MockFareIngestor` | Deterministic test data, realistic price jitter | No | Dev/test only |
| `GoogleFlightsIngestor` | **Google Flights fares — covers Air Peace, Arik, Ibom, etc.** | No | **PRIMARY** |
| `AmadeusFareIngestor` | GDS fares (international carriers) | Yes (free tier) | Secondary (no NG domestic coverage) |
| `HybridIngestor` | Google Flights + Amadeus combined | Amadeus key only | Secondary |

### Tracked routes (Nigeria domestic only)

| Route | Description | Expected carriers |
|---|---|---|
| LOS-ABV / ABV-LOS | Lagos - Abuja | Air Peace, Arik, Ibom, United Nigeria |
| LOS-PHC / PHC-LOS | Lagos - Port Harcourt | Air Peace, Arik |
| LOS-ENU / ENU-LOS | Lagos - Enugu | Air Peace, Enugu Air, Ibom |
| LOS-BNI / BNI-LOS | Lagos - Benin City | Air Peace, Arik |
| LOS-KAN / KAN-LOS | Lagos - Kano | Air Peace, Max Air |
| LOS-CBQ / CBQ-LOS | Lagos - Calabar | Ibom Air, Air Peace |
| LOS-ILR / ILR-LOS | Lagos - Ilorin | Air Peace, Overland |
| LOS-QOW / QOW-LOS | Lagos - Owerri | Air Peace, United Nigeria |
| ABV-PHC / PHC-ABV | Abuja - Port Harcourt | Air Peace, Arik |
| ABV-ENU / ENU-ABV | Abuja - Enugu | Air Peace, Enugu Air |
| ABV-BNI / BNI-ABV | Abuja - Benin City | Air Peace |
| ABV-KAN / KAN-ABV | Abuja - Kano | Air Peace, Max Air |
| ABV-CBQ / CBQ-ABV | Abuja - Calabar | Ibom Air |
| PHC-ENU / ENU-PHC | Port Harcourt - Enugu | Air Peace |

### Nigerian domestic carriers

| Airline | IATA | Google Flights? | Amadeus GDS? |
|---|---|---|---|
| Air Peace | P4 | **Yes** | No |
| Arik Air | W3 | **Yes** | No |
| Ibom Air | QI | Likely | No |
| United Nigeria Airlines | UN | Possible | No |
| Green Africa Airways | NK | Possible | No |
| ValueJet | VK | Possible | No |
| Overland Airways | OF | Limited | No |
| NG Eagle | NE | Possible (new carrier) | No |
| Max Air | MX | Primarily Kano hub | No |
| Umza Air | UM | Limited | No |
| Enugu Air | Q9 | Limited | No |
| ~~Dana Air~~ | ~~9J~~ | ~~Defunct (NCAA suspended April 2024)~~ | No |

### Tuning knobs

| Env var | Default | Description |
|---|---|---|
| `FARE_POLL_MINUTES` | 5 | Worker poll interval |
| `FARE_WINDOW_DAYS` | 30 | Rolling window length |
| `FARE_WINDOW_SAMPLE_DAYS` | 5 | Sample every N days within window |
| `FARE_SOURCE` | mock | Active ingestor: mock/google/amadeus/hybrid |
| `GOOGLE_FLIGHTS_CURRENCY` | NGN | Currency for Google Flights queries |

## Notification emoji scheme (centralized in notify_templates.py)

| Message type | Emoji |
|---|---|
| Subscribe / Track confirmation | ✅ |
| Fare found (FARE query) | 💰 |
| No fare/route data yet | 🔎 |
| Status report logged (pending) | 📝 |
| Rate-limited ("too fast") | ⏳ |
| Unparsed/unclear report | ❓ |
| Fare-drop alert (push) | 📉 |
| Boarding confirmed (push) | 🛫 |
| Gate change confirmed (push) | 🚪 |
| Delay confirmed (push) | ⏰ |
| Not-boarding confirmed (push) | 🕓 |
| Other/generic status (push) | 🔔 |
| HELP text | *(none)* |

## Boarding-status trust model (`app/services/status_service.py`)

- 1 report → **pending** (never pushed)
- 2+ **distinct** reporters, same state, within 30 min → **confirmed** → pushed
  once (deduped via `push_log`) to everyone subscribed to that flight
- Conflicting states → **disputed**, surfaced in admin, never silently overwritten
- Exception: a bucket with ≥2 reporters AND ≥2× the rival bucket wins
  (majority-wins); minority reports are marked disputed

### Anti-abuse
- Rate limit: 1 report / reporter / flight / 5 min
- Reporter scoring: contradiction rate > 50% over ≥3 reports → **flagged**
- Reward hook: `reporter_scores.credits` + `trust_level` columns for future use

## Tests

```bash
cd naijafly && python -m pytest tests -v
```

**40+ passing** — covers: fare ingestion (mock + Amadeus), FX conversion, price-alert
triggering (date-aware), status parsing, confirmation/dispute/majority-wins, emoji
templates, FARE_SOURCE toggle, Dana Air removal, rolling-window sampling, specific-date
subscriptions, date-scoped queries, and command parsing with dates.

## What's REAL vs MOCKED

| Component | Status |
|---|---|
| WhatsApp inbound webhook (Twilio → TwiML reply) | **REAL** |
| WhatsApp outbound pushes (Twilio SDK) | **REAL**; console fallback |
| Price-drop alert worker (APScheduler, date-aware) | **REAL** |
| Boarding-status confirm → push loop | **REAL** |
| FX rates (open.er-api.com, keyless, NGN only) | **REAL** with cached fallback |
| Admin view (`/admin`) | **REAL** (no auth — add basic auth for pilot) |
| Fare data (mock) | **REAL** code, fake prices — default for dev |
| Fare data (Google Flights) | **REAL** via fli library — **primary for production** |
| Fare data (Amadeus) | **REAL** code, secondary — no NG domestic carrier coverage |

## STILL not done

1. **Production WhatsApp Business API approval** — sandbox only.
2. Admin auth (one line of basic-auth middleware before pilot).
3. **Google Flights rate-limit hardening** — at very high poll frequencies.
4. **fli legal review** — reverse-engineered API; review Google ToS before
   commercial deployment at scale.
