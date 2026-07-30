# Phase Rules — Araha

## Active Phase: 3 (Production Readiness & Hardening)

## Scope Boundaries
### In Scope (Phase 3)
- Rate-limit hardening for external API calls (Google Flights)
- Error handling improvements
- Documentation of production blockers
- Legal/documentation review items

### Out of Scope (Phase 3)
- New features or workflows
- WhatsApp Business API approval process (Phase 6)
- Observability/monitoring dashboards (Phase 4)
- Mobile app or non-WhatsApp interfaces (Phase 7)
- West Africa / cross-border route expansion (Phase 7)

## Gate Rules
1. Every idea goes through PROJECT_UPGRADE_PIPELINE.md first
2. No implementation without an approved phase spec
3. No scope widening beyond active phase
4. Every milestone requires proof artifacts + compaction

## Phase Transition
- Phase 3 is complete when: rate-limit hardening is implemented and verified, production blockers are documented, and a compaction is written
- Next: Phase 4 (Observability & Monitoring)
