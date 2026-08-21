# Antigravity Rules & Workspace Guidelines

Welcome! This file configures the workflow for **Antigravity** (your AI coding companion) within the Mistilteinn (Genshin Impact optimizer) codebase.

## 1. Instruction Sources of Truth
Antigravity automatically references and adheres to the following instructions files:
* **Global Rules**: [CLAUDE.md](file:///\\wsl.localhost\Ubuntu\root\mistilteinn\CLAUDE.md)
* **Backend Guidelines**: [backend/CLAUDE.md](file:///\\wsl.localhost\Ubuntu\root\mistilteinn\backend\CLAUDE.md)
* **Frontend Guidelines**: [frontend/CLAUDE.md](file:///\\wsl.localhost\Ubuntu\root\mistilteinn\frontend\CLAUDE.md)

---

## 2. Git & Branching Strategy
To maintain a safe, reviewable development environment, the following git rules are strictly enforced for Antigravity:

* **Protected Branches**: `dev` and `main` are strictly read-only for Antigravity. Direct commits to these branches are prohibited.
* **Feature Branches**: All feature development, refactoring, and bug fixes must occur on a new branch branched off `dev`.
* **Branch Suffix**: All Antigravity feature branches **must** end with the `_agy` suffix (e.g., `feat/add-disc-sorting_agy`, `fix/damage-calc-crit_agy`).
* **Pull Requests & Code Review**: Once changes are complete and verified (tests and lints passing), the branch will be pushed for you to review and merge into `dev`.

---

## 3. Workflow Checklist
Before every commit or push, the environment must satisfy:
* **Backend**: `docker compose run --rm backend ruff check app/` (lint) and `docker compose run --rm backend pytest` (tests) must pass.
* **Frontend**: `npm run lint` and `npm run test` (Vitest) must pass.
