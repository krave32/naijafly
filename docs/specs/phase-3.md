# Phase 3: Production Readiness & Hardening

## Status
`Approved`

## Summary
Phase 3 hardens the existing Araha system for production reliability. Core features are built and working (Phase 0-2 complete). This phase focuses on making external API calls resilient, documenting production blockers, and closing reliability gaps before scaling.

## Phase Goal
- Rate-limit hardening for Google Flights API calls (exponential backoff, configurable rate cap, graceful degradation)
- Production blocker documentation
- No new features or workflows

## Why Now
Araha's core loops work, but the Google Flights ingestor has no rate-limit protection. At higher poll frequencies (FARE_POLL_MINUTES < 10), API rejections could cascade into failed fare refreshes without clear error signals. Hardening this before scaling prevents silent data loss.

## Non-Goals
- No WhatsApp Business API approval (Phase 6)
- No observability/monitoring dashboards (Phase 4)
- No new fare sources or routes
- No mobile app or non-WhatsApp interfaces

## Scope
- GoogleFlightsIngestor rate-limit detection and backoff
- Configurable max requests per minute env var
- Graceful degradation: rate-limited ingestor falls back to last-known-good fares
- Tests for rate-limit scenarios
- Failure behavior documented

## Implementation Guardrails
- Keep the ingestor interface stable — no breaking changes to `FareIngestor` base class
- Add env vars with sensible defaults
- Log rate-limit events clearly at WARNING level

## Acceptance Criteria
- Worker survives sustained rate-limit responses without crashing
- Rate-limited periods return last-known-good fares instead of empty data
- Rate-limit events are logged with clear warnings
- Configurable rate cap via env var

## Verification Evidence Required
- Test: rate-limit response triggers backoff, not crash
- Test: after rate-limit backoff, normal polling resumes
- Test: config env var caps request frequency correctly
- Command trace: worker log showing rate-limit detection + recovery

## Test Plan
- Scenario A: mock a rate-limit response → worker backs off and retries
- Scenario B: continuous rate-limit responses → worker uses cached fares gracefully
- Scenario C: rate cap env var set to low value → requests are throttled correctly
- Scenario D: rate limit clears → normal polling resumes within expected window

## Risks
- Backoff delay could cause stale fares during prolonged rate-limiting
- Cached fallback masks API issues — operator may not notice without monitoring
- fli library changes could break the ingestor independently
