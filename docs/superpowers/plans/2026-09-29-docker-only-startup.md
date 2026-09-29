# Docker-Only Startup Implementation Plan

> **For agentic workers:** This plan is being executed inline per the user's explicit request.

**Goal:** Keep `make docker-start` as the only project application startup configuration and remove alternate native-process and container-development startup paths.

**Architecture:** Retain the existing Docker Compose stack and its lifecycle helpers. Remove host-side service orchestration and unused Compose development image stages; update command documentation to describe the sole supported Docker startup accurately, while preserving container runtime commands.

**Tech Stack:** GNU Make, Bash, Docker Compose, Python, pnpm.

**Spec:** User request in this conversation.

## Global Constraints

- Preserve user changes unrelated to startup configuration.
- Retain `make docker-start` and the Docker stop/log/build/configuration workflows.
- Preserve the frontend and backend container runtime commands.
- Remove host-native startup entry points, unused container-development entrypoints, and stale references to them.

## Review Focus

- Docker container commands that resemble local startup commands must remain intact.
- Shared validation, configuration, and logging commands must not be removed with the local launcher.
- Documentation must not suggest a local startup mode that no longer exists.

---

### Task 1: Remove alternate startup launchers

**Files:** Root `Makefile`, `backend/Makefile`, `frontend/Makefile`, `frontend/package.json`, Dockerfiles, and launcher scripts.

- [x] Remove native-process `dev` / `start` and daemon targets, retaining Docker targets and container runtime commands.
- [x] Remove scripts used only by deleted startup launchers after confirming no remaining callers.
- [x] Remove unreferenced Docker `dev` build stages and entrypoint if the Compose stack does not use them.

### Task 2: Align documentation and verify

**Files:** Existing setup/deployment documentation that references local startup.

- [x] Replace alternate startup instructions with `make docker-start` and applicable Docker lifecycle commands.
- [x] Search the whole repository for stale alternate-startup references and host-side launchers.
- [x] Run focused static checks and Docker Compose configuration validation where available.
