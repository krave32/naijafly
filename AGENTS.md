# Araha — Agent Instructions

This repository uses the Project OS operating system for disciplined, phase-based, LLM-assisted engineering.

## Reading Order (when entering this repo fresh)

1. `docs/BUILD_CONTEXT.md` — project identity, architecture, state
2. `PROJECT_BRIEF.md` — mission, users, constraints, phase sequence
3. `docs/SEC.json` — machine-readable summary
4. `docs/PHASE_RULES.md` — what's in/out of scope for active phase
5. `docs/NEXT_STEPS.md` — what to do next
6. `docs/TASK_BOARD.md` — task status
7. `docs/DEV_RULES.md` — coding conventions
8. `docs/DEFINITION_OF_DONE.md` — completion standards

## Hard Rules

- Do not implement directly from raw ideas — gate through PROJECT_UPGRADE_PIPELINE.md
- Do not widen scope beyond the approved phase
- Do not treat backlog items as implementation approval
- Do not claim a milestone without proof artifacts
- SEC files are the authoritative collaboration contract
- Write compaction after any phase completion

## Build Discipline

- State assumptions when they affect implementation
- Prefer the simplest valid change
- Make surgical edits, avoid speculative abstractions
- Define success as a concrete verification check (test output, command trace)

## Review Discipline

- Findings first — bugs, regressions, scope leakage, missing proof
- Prefer reality-tested behavior over theoretical correctness
- Penalize unnecessary abstraction and false confidence

## Source of Truth

- Intake pipeline: `PROJECT_UPGRADE_PIPELINE.md`
- Deferred work: `PROJECT_PHASE_BACKLOG.md`
- Phase contracts: `docs/specs/`
- Proof artifacts: `verification/`
- Review artifacts: `docs/reviews/`
- Compactions: `docs/compactions/`

## Source Files

Read these to understand the codebase:
- `app/main.py` — endpoints, startup
- `app/services/bot_router.py` — command parsing
- `app/services/fare_ingestor.py` — fare data sources
- `app/services/fare_service.py` — fare comparison
- `app/services/status_service.py` — boarding trust model
- `app/services/notifier.py` — WhatsApp push
- `app/workers/fare_worker.py` — polling worker
- `app/models/models.py` — DB schema
