# Next Steps

## Active: Phase 3 — Production Readiness & Hardening

### Immediate Next Task
**Task: Google Flights rate-limit hardening**
- Implement exponential backoff / retry logic in GoogleFlightsIngestor
- Add rate-limit detection and graceful degradation
- Add configurable max requests per minute env var
- Verify with tests that rate-limited responses don't crash the worker

### Priority Queue
1. Google Flights rate-limit hardening (HIGH)
2. Write compaction for current Phase 3 work (once task 1 is verified)
3. fli legal review — document findings in docs/reviews/ (MEDIUM)
4. Production WhatsApp Business API prep (LOW until Phase 6)

### Known Issues / Tech Debt
- Google Flights `fli` library uses reverse-engineered API — legal risk for commercial deployment
- `fli` library Airline enum has incorrect string values for some carriers (safety filter in place)
- No monitoring/observability beyond basic logging
- Admin dashboard is minimal HTML — no analytics or charts
