# AtlasRisk 3.10.37 Release Verification

## Required gate
Run in a clean environment with Docker and network access:

```bash
docker compose -f docker-compose.verify.yml up --build --abort-on-container-exit --exit-code-from verify
docker compose -f docker-compose.verify.yml down -v
```

The verification container runs:
1. Full pytest suite
2. Alembic upgrade to head against PostgreSQL 17
3. `alembic check`
4. Bandit 1.9.4
5. pip-audit 2.10.1

## Why this is separate from production compose
The verification database is disposable and bound to localhost on port 55432. It cannot touch production data.

## Current environment limitation
The supplied execution environment has no PostgreSQL server, no Docker runtime, and no outbound package-network access. Therefore these gates must be run in a normal CI/developer environment and must not be represented as passed here.

## Current dependency baselines

- aiosqlite 0.22.1
- asyncpg 0.31.0
- Bandit 1.9.4
- pip-audit 2.10.1

These are pinned for reproducible verification; the production image does not install Bandit or pip-audit.
