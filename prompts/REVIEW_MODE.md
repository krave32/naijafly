# Review Mode

Default evaluation mode before accepting milestone work.

## Purpose
Catch bugs, regressions, scope leakage, invariant breaks, and missing proof before they compound.

## Review Order
1. Does the change match the approved scope?
2. Are there any regressions in existing tests?
3. Are there bugs or edge cases not handled?
4. Is there unnecessary abstraction or speculative code?
5. Is proof provided (test output, command trace)?
6. Are SEC files updated?

## Default Review Lens
- Prioritize simplicity, truthfulness, and reality-tested behavior
- Penalize false confidence, unnecessary abstraction, duplicated logic
- End with: `Accept`, `Accept With Follow-Ups`, or `Block`
