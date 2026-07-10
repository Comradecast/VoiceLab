# VoiceLab Non-Negotiables

## Purpose

This document defines the rules VoiceLab refuses to break.

These rules exist to prevent architectural drift, patch rabbit holes, hidden coupling, and untestable code.

## Rules

1. **The engine never imports UI.**

2. **The UI never processes audio.**

3. **Effects are plugins, not engine code.**

4. **Every effect must be independently testable.**

5. **Every effect must expose telemetry.**

6. **The engine owns audio flow, not effect behavior.**

7. **Characters are configuration, not Python code.**

8. **No global mutable state unless explicitly justified.**

9. **Every architectural change updates documentation first.**

10. **Every commit must leave the app runnable.**

11. **Features are added through interfaces, not special cases.**

12. **The core should become simpler as capabilities grow.**

13. **Every responsibility has exactly one owner.**

14. **No subsystem may know more than it needs to perform its responsibility.**

15. **Data flows through defined interfaces; side-door coupling is forbidden.**

## Review Standard

Before implementing any feature, ask:

- Does this belong in the subsystem being changed?
- Which subsystem owns this responsibility?
- Can this be tested without the GUI, microphone, or virtual cable?
- Does this introduce a new coupling?
- Is data flowing through a defined interface?
- Does this make Version 2 easier or harder?
- Does this violate any rule above?

If the answer is unclear, stop and design before coding.
