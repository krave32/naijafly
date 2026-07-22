# NaijaFly — West Africa Flight Fare Tracker + Crowdsourced Boarding Status

WhatsApp-first fare alerts and passenger-reported flight status for West African routes.
The full loop is real end-to-end: **a message in triggers a reply, a status escalation
triggers a push, a fare drop triggers a push.**

> **Note on this README:** an earlier version of this file (and this repo's test suite)
> was stale — it described the WhatsApp webhook as "not implemented" when the code had
> already moved past that. This version reflects the actual current state of the code,
> verified by running the test suite below, not by re-describing an old build.

## Architecture

```
docker-compose
├── db       Postgres 15 (fares, subscriptions, reports, scores, alert history)
├── app      FastAPI: /webhook/whatsapp (Twilio inbound), /admin, /health
└── worker   APScheduler: FX refresh + fare ingestion + price-drop pushes
```

Fare ingestion and boarding status stay **decoupled**: different services
(`fare_service` vs `status_service`), different trust models, no shared logic.

## Running it

```bash
docker-compose up --build
# API:    http://localhost:8000
# Admin:  http://localhost:8000/admin
# Health: http://localhost:8000/health   (shows notifier mode: twilio|console)
```

Copy `.env.example` to `.env` and fill in real values to go live. Without Twilio
credentials, pushes go to the container log in CONSOLE mode instead of WhatsApp —
nothing else changes.

## Bot commands

| Message | Effect |
|---|---|
| `SUBSCRIBE LOS ACC 80000` | Fare-drop alerts for route (target price optional) |
| `FARE LOS ACC` | Current cheapest fare, local currency + USD |
| `TRACK P47123 2026-07-20` | Live boarding/gate/delay pushes for that flight |
| `boarding now gate 12` (while tracking) | Files a status report |
| `HELP` | Command list |

## Fare data sources

Toggle with the `FARE_SOURCE` env var — `mock` (default), `amadeus`, `google`, or
`hybrid`. No redeploy needed, no code change either way; see
`app/services/fare_ingestor.py`.

| Source | What it provides | API key needed? |
|---|---|---|
| `MockFareIngestor` | Deterministic test data, realistic price jitter | No |
| `AmadeusFareIngestor` | GDS fares for international/regional carriers | Yes (free tier) |
| `GoogleFlightsIngestor` | **Google Flights fares — covers Air Peace, Arik, Ibom, etc.** | No |
| `HybridIngestor` | Google Flights + Amadeus combined for maximum coverage | Amadeus key only |

### Google Flights integration (recommended for West African carriers)

The `GoogleFlightsIngestor` uses the [fli](https://github.com/punitarani/fli) library
(`pip install flights`) which reverse-engineers Google Flights' internal API. This is
the **single best source** for Nigerian and West African domestic carrier fares because
Google aggregates from airline websites and OTAs — covering carriers that are NOT on
any GDS.

**Confirmed airline coverage via Google Flights:**

| Airline | IATA | Google Flights? | Amadeus GDS? |
|---|---|---|---|
| Air Peace | P4 | **Yes** (confirmed live) | No |
| Arik Air | W3 | **Yes** | No |
| Ibom Air | QI | Likely (limited routes) | No |
| Dana Air | 9J | Possible (intermittent ops) | No |
| Africa World Airlines | AW | Possible (Ghana routes) | No |
| United Nigeria Airlines | UN | Possible | No |
| Enugu Air | Q9 | Possible (limited) | No |
| Ethiopian Airlines | ET | **Yes** | **Yes** |
| Kenya Airways | KQ | **Yes** | **Yes** |
| Royal Air Maroc | AT | **Yes** | **Yes** |

**Tracked routes (Nigeria + West Africa):**

| Route | Description | Expected carriers |
|---|---|---|
| LOS-ABV / ABV-LOS | Lagos - Abuja | Air Peace, Arik, Ibom, United Nigeria |
| LOS-PHC / PHC-LOS | Lagos - Port Harcourt | Air Peace, Arik, Dana |
| LOS-ENU / ENU-LOS | Lagos - Enugu | Air Peace, Enugu Air, Ibom |
| LOS-BNI / BNI-LOS | Lagos - Benin City | Air Peace, Arik |
| LOS-KAN | Lagos - Kano | Air Peace, Arik |
| LOS-CBQ | Lagos - Calabar | Ibom Air, Air Peace |
| ABV-PHC | Abuja - Port Harcourt | Air Peace, Arik |
| ABV-ENU / ENU-ABV | Abuja - Enugu | Air Peace, Enugu Air |
| ABV-BNI | Abuja - Benin City | Air Peace |
| LOS-ACC / ACC-LOS | Lagos - Accra | Air Peace, AWA, Ethiopian |
| ACC-KMS / KMS-ACC | Accra - Kumasi | AWA |
| ACC-TML | Accra - Tamale | AWA |
| LOS-DKR | Lagos - Dakar | Royal Air Maroc, Ethiopian |
| LOS-ABJ | Lagos - Abidjan | Air Côte d'Ivoire, Air Peace |

To activate Google Flights:
```bash
pip install flights curl_cffi
# In .env:
FARE_SOURCE=google
# Or for maximum coverage:
FARE_SOURCE=hybrid
```

### Amadeus GDS coverage (international/regional routes)

Amadeus's GDS content does **not** include Air Peace, Dana Air, Ibom Air, Arik Air,
or AWA directly. It covers GDS-connected carriers on larger regional/international
routes. Use `FARE_SOURCE=hybrid` to combine both sources.

To try Amadeus only: get free-tier credentials at developers.amadeus.com, set
`AMADEUS_API_KEY` / `AMADEUS_API_SECRET` in `.env`, set `FARE_SOURCE=amadeus`,
restart.

## Notification emoji scheme (proposed, centralized)

Every outbound message is built in one place — `app/utils/notify_templates.py` —
so the scheme below is a one-line edit per message type if you want to change it.
Rationale for each choice is in that file's docstring.

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
| HELP text | *(none — plain instructions, an emoji adds noise not clarity)* |

## Boarding-status trust model (`app/services/status_service.py`)

- 1 report → **pending** (never pushed)
- 2+ **distinct** reporters, same state, within 30 min → **confirmed** → pushed
  once (deduped via `push_log`) to everyone subscribed to that flight
- Conflicting states → **disputed**, surfaced in admin, never silently overwritten
- Exception: a bucket with ≥2 reporters AND ≥2× the rival bucket wins
  (majority-wins); minority reports are marked disputed and their reporters'
  contradiction counts increase

### Anti-abuse
- Rate limit: 1 report / reporter / flight / 5 min
- Reporter scoring: contradiction rate > 50% over ≥3 reports → **flagged**;
  flagged reporters' reports are stored but excluded from confirmation counting
- Reward hook: `reporter_scores.credits` + `trust_level` columns exist now so a
  "trusted reporter" / credit system can be added without schema changes

### Assumptions still needing real-world tuning
- 30-min window + threshold 2: may need 3+ at high-traffic airports (LOS)
- Majority-wins 2× factor: untested against real gate-chaos patterns
- Reporter identity = WhatsApp number: SIM-swapping Sybil attacks not addressed

## Tests

```bash
cd naijafly && python -m pytest tests -v
```

**29 passing** — covers: fare ingestion (mock + Amadeus, HTTP mocked), FX conversion,
price-alert triggering, status parsing, confirmation/dispute/majority-wins/tie logic,
fare-drop push worker, boarding-status push loop (incl. dedupe), anti-abuse scoring,
emoji-template correctness (isolated + wired through the live bot router), and the
FARE_SOURCE toggle.

> A prior version of this suite had a failing test (`test_status_aggregation`) whose
> assertion didn't match the actual, intentional majority-wins reconciliation logic —
> it expected *any* conflicting report to dispute everything, but the real rule (see
> `status_service.py`) lets a clear majority stay confirmed. Fixed by replacing it with
> three correctly-targeted tests: confirms-at-threshold, majority-wins-over-minority,
> and genuine-tie-stays-disputed.

## What's REAL vs MOCKED — current state

| Component | Status |
|---|---|
| WhatsApp inbound webhook (Twilio form → TwiML reply) | **REAL** |
| WhatsApp outbound pushes (Twilio SDK) | **REAL**; console fallback without creds |
| Price-drop alert worker (APScheduler, end-to-end push) | **REAL** |
| Boarding-status confirm → push loop | **REAL** |
| FX rates (open.er-api.com, keyless, DB-cached) | **REAL** with cached/default fallback |
| Admin view (`/admin`) | **REAL** (no auth — put behind basic auth for pilot) |
| Fare data (mock) | **REAL code**, fake prices — default |
| Fare data (Amadeus) | **REAL** GDS integration, opt-in via `FARE_SOURCE=amadeus`; coverage gaps documented above |
| Fare data (Google Flights) | **REAL** via fli library, opt-in via `FARE_SOURCE=google` or `hybrid`; best West African carrier coverage |
| Emoji notification scheme | **REAL**, centralized, proposed scheme (table above) |
| Multi-currency (NGN, GHS, XOF, SLL, GMD, LRD, GNF) | **REAL** with live rate refresh |

## STILL not done (honest list)

1. **Production WhatsApp Business API approval** — sandbox only.
2. Admin auth (one line of basic-auth middleware before pilot).
3. **Google Flights rate-limit hardening** — at very high poll frequencies
   (sub-5-min) across 20+ routes, Google may rate-limit. Stagger polling if needed.
4. **fli legal review** — reverse-engineered API; review Google ToS before
   commercial deployment at scale. Consider official Google Flights API partnership.
