# VoiceLab Engineering Process

Every contribution follows this process:

```text
Architecture
    |
    v
Specification
    |
    v
Review
    |
    v
Approve
    |
    v
Implement
    |
    v
Review
    |
    v
Verify
    |
    v
Commit
```

## Required Standard

- If the work has no clear architectural home, stop before implementation.
- If ownership is ambiguous, create or update a Decision Queue page.
- If the work changes boundaries, contracts, lifecycle, invariants, or responsibilities, update architecture before implementation.
- If the work adds behavior, define the expected behavior before implementation.
- If the work changes code, verify that current behavior still works before commit.
- No feature is small enough to bypass architecture, ownership, review, and verification.

## Review Gate

A change is ready to implement only when:

- its owner is clear
- its interfaces are clear
- its test or verification path is clear
- it does not violate `NON_NEGOTIABLES.md`
- it does not contradict `ARCHITECTURE.md`
- unresolved decisions are tracked in `DECISION_QUEUE.md`

## Commit Gate

A change is ready to commit only when:

- implementation matches the approved specification
- review findings are addressed or explicitly deferred
- verification has been run or the gap is documented
- documentation remains accurate
- the app remains runnable
