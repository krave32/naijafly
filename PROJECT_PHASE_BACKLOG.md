# Phase Backlog

## Phase 4 (Observability & Monitoring)
- Integrate structured logging (e.g., structlog)
- Add basic request-rate metrics
- Admin dashboard: fare-refresh health indicators

## Phase 5 (Calibration & Correctness)
- Fare accuracy benchmarks (mock vs Google Flights vs real prices)
- Alert threshold tuning
- **NLP: Improve pattern matcher coverage** — add more Nigerian city name variants (Ikeja→LOS, Benin→BNI, PH→PHC), handle abbreviations, improve date extraction
- **NLP: Reduce LLM parser dependency** — expand pattern matcher to handle more query patterns so fewer queries fall through to the slower/costly LLM parser
- **NLP: Edge-case hardening** — fix parsing failures for mixed-language messages, misspellings (e.g. "Lgos", "Abj"), and incomplete route descriptions

## Phase 6 (Production WhatsApp)
- WhatsApp Business API approval process
- Migrate from sandbox to production
- Scale webhook handling

## Phase 7 (Broader Capabilities)
- West Africa cross-border routes (multi-currency)
- Mobile app or web-based fare search
- Multi-language support (Pidgin English, Yoruba, Hausa, Igbo)
- **NLP: Natural language status reports** — parse free-form status reports like "just landed", "still waiting at gate", "they said 2 hour delay"
- **NLP: Conversational multi-turn** — handle follow-ups like "what about the return flight?" or "and Air Peace?"
- **NLP: Local language support** — add intent parsing for Nigerian Pidgin, Yoruba, Hausa, Igbo queries
