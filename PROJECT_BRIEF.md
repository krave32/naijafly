# Araha — Nigeria's Flight Fare Tracker + Crowdsourced Boarding Status

## Mission
Make Nigeria domestic air travel more predictable and affordable through WhatsApp-first fare alerts and passenger-reported real-time flight status.

## Primary User
- Nigerian domestic air travelers
- Frequent flyers on routes: LOS, ABV, PHC, ENU, BNI, KAN, CBQ, ILR, QOW, AKR
- Users who rely on WhatsApp as their primary messaging platform

## Core Problem
Nigerian domestic flyers have no reliable way to:
1. Track fare drops without manually checking multiple airline sites
2. Get real-time boarding/gate/delay status before heading to the airport

## Product Shape
WhatsApp-first: a user sends a message and gets an instant reply. The full loop is:
- `SUBSCRIBE LOS ABV` → fare-drop alerts pushed via WhatsApp
- `FARE LOS ABV` → cheapest fare in next 30 days
- `TRACK P47123` → live boarding/gate/delay pushes
- Crowdsourced status: 2+ distinct reporters confirm a state → push to all

## Current State (what's built)
- Real WhatsApp inbound webhook (Twilio → TwiML reply)
- Real WhatsApp outbound pushes (Twilio SDK, console fallback)
- Price-drop alert worker (APScheduler, date-aware, rolling 30-day window)
- Boarding-status confirm → push loop (trust model: pending→confirmed→disputed)
- FX rates from open.er-api.com (keyless, NGN only, cached fallback)
- Admin view (`/admin`) with HTTP Basic Auth
- Google Flights fare ingestion (via `fli` library, primary production source)
- 226 passing tests
- Docker Compose + Railway deployment
- NDPA-compliant privacy & data deletion

## What's NOT done yet
1. Production WhatsApp Business API approval (currently sandbox only)
2. Google Flights rate-limit hardening
3. `fli` legal review (reverse-engineered API — Google ToS review needed)

## Constraints
- Nigeria-domestic only (no cross-border/multi-currency)
- WhatsApp-first (no separate mobile app for MVP)
- Local-first development, Docker/Railway deployment

## Phase Sequence
- Phase 0-2: DONE — Foundation, core loop, bounded expansion
- Phase 3 (ACTIVE): Production readiness & hardening
- Phase 4: Observability & monitoring
- Phase 5: Calibration & correctness hardening
- Phase 6: Production WhatsApp approval + scaled deployment
- Phase 7: Broader capabilities (West Africa, mobile app, etc.)

## Working Rules
- Ideas gate through PROJECT_UPGRADE_PIPELINE.md first
- Active phase spec is the implementation contract
- Build Mode is default implementation posture
- Review Mode required before milestone acceptance
- Proof and compaction mandatory for meaningful milestones
