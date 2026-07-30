# Project Upgrade Pipeline

## Core Rule
Before anything enters planning or implementation, ask:
> Does this improve the project in a way that belongs to the current capability sequence?

## Intake Filter
Run every idea through these questions in order:
1. What concrete project problem does this solve?
2. Does the project currently have this problem?
3. Is this a current-phase problem or a future-phase problem?
4. Which phase owns this capability?
5. What breaks if we add it too early?
6. Does the active phase already have an approved spec?

## Decision Outcomes
- `BUILD NOW`
- `DEFER TO PHASE X`
- `REJECT`

## Phase Gating
Before implementation:
1. Confirm active phase
2. Confirm no earlier phase gap blocks it
3. Confirm `docs/specs/phase-x.md` exists
4. Confirm phase status is `Approved`
5. Only then implement

## Backlog Rule
If an idea passes the filter but doesn't belong in the active phase, add it to `PROJECT_PHASE_BACKLOG.md` under the correct future phase.

## Compaction Rule
When writing milestone compactions: record verified state, preserve the exact next move, keep specs authoritative.
