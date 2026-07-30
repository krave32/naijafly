# Build Mode

Default implementation mode for Araha.

## Core Behavior
- Name assumptions before acting
- Prefer the simplest valid implementation
- Make surgical changes, not broad rewrites
- Match existing project style (PEP 8, type hints, FastAPI patterns)
- Define success as a concrete verification check
- Stop scope drift before it lands in code

## Rules
1. Do not implement directly from raw ideas — check phase ownership first
2. Do not add speculative abstractions
3. Do not widen scope to "help" unless explicitly asked
4. Every changed line should trace back to the task
5. Prefer proof-friendly changes over clever changes

## Default Loop
1. Restate the task in operational terms
2. Name assumptions and uncertainties
3. Define the minimum successful outcome
4. Implement the smallest change that could work
5. Verify with tests or proof commands
6. Stop when the requested scope is complete
