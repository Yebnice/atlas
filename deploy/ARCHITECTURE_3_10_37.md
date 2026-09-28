# Atlas 3.10.37 — Target Runtime Architecture

## Process separation

- `PROCESS_ROLE=api`: HTTP/API only. Background reconciliation, custody scans, recovery and autonomous controllers do not start.
- `PROCESS_ROLE=worker`: continuous background work. Deploy this as a Cloud Run Worker Pool.
- `PROCESS_ROLE=job`: reserved for finite operational jobs such as migration/research.

Google Cloud Run currently documents Services for HTTP, Jobs for run-to-completion tasks, and Worker Pools for continuous non-HTTP background workloads.

## Security boundaries

1. Customer/API layer
2. Deterministic risk engine
3. Execution queue/worker
4. Exchange adapter
5. Custody policy and external signer boundary
6. Independent reconciliation
7. Authoritative customer ledger

## Exchange layer

CCXT is used as a common adapter boundary. The adapter exposes capability discovery so Atlas can refuse an operation when an exchange does not support the required unified capability. Exchange-specific APIs remain available behind dedicated adapters where necessary.

## Custody layer

Atlas prepares and records custody operations but does not receive private signing keys. Withdrawal and sweep actions remain policy-controlled, audited and reconciled.

## Release gate

A production promotion should require:

- clean PostgreSQL migration to head
- `alembic check` with no drift
- concurrency tests against PostgreSQL
- financial invariant tests
- dependency security scan
- worker failover drill
- exchange order idempotency/reconciliation drill
- custody/sweep reconciliation drill
