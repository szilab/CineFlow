# CineFlow Agent Rules

## Project Type
CineFlow is a modular media automation workflow engine.

It integrates media sources end self-hosted destination platforms (TMDB, Jackett, Plex, TRansmission, Jellyfin, etc.)

The system is YAML-driven and executes workflows composed of modular steps.

---

## Core Architecture Principles

### 1. Workflow-first design
All logic must be part of a workflow or workflow set described in YAML document.
Do NOT implement bussines logic outside the workflow system.

### 2. Strict module boundaries
Each integration must live in its own module like, modules must NOT directly depend on each other.
All communication must go through workflow orchestration layer and the data format should be module independent.

---

## Configuration

- All configuration MUST come from YAML files or ENV variables through special library. (e.g.: no hardcoded API keys)
- No environment-specific logic
- Config must be validated at startup

---

## Coding Rules

- Python 3.13+
- Use type hints everywhere
- Use base class where make sense
- Prefer pathlib over os
- Use structured logging
- Keep functions < 60 lines

---

## Agent Behavior Rules

When implementing a feature:

1. First inspect existing workflow structure
2. Reuse existing modules whenever possible
3. Do not create duplicate integrations
5. Always consider idempotency and retry safety