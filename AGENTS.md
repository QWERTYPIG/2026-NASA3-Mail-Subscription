# NTU CSIE Mail Subscription System

## Overview

Departmental mail alias subscription management: users sign in with LDAP accounts to subscribe or unsubscribe. Administrators in the LDAP `mailAdmin` group manage aliases and members.

## Topic docs

Start with `docs/README.md` for the project entry point and repository layout, then read by task:

| Document | When to read |
|---|---|
| `docs/01-architecture.md` | System boundaries, data flows, synchronization, business rules, and HA limitations. |
| `docs/02-dependency-hardware.md` | External dependencies, ports, volumes, host files, and unverified infrastructure assumptions. |
| `docs/03-setup.md` | Development setup, pre-launch validation gate, Compose startup, testing, and troubleshooting. |
| `docs/04-api-and-db.md` | API routes, session/CSRF, permissions, requests/responses, schema, queue behavior, and known implementation differences. |
| `docs/05-migration.md` | Deployment, migrations, HA monitor, DB synchronization, backup, restore, and rollback. |

## Testing

Run the checks relevant to your changes from the project root. Before Compose-based checks, pass the validation gate in `docs/03-setup.md` and keep local `FLUSH_ENABLED=0`.

| Change scope | Checks |
|---|---|
| Backend (`apps/`, `core/`) | `docker compose exec web python manage.py check`; `docker compose exec web python manage.py test` |
| Frontend (`frontend/`) | `docker compose exec frontend npm run lint`; `docker compose exec frontend npm run build`; verify UI changes in a browser. |
| HA monitor (`scripts/monitor/`) | `python3 -m unittest discover -s scripts/monitor -p 'test_*.py'` |
| Startup or service configuration | Verify services and logs per `docs/03-setup.md`; `GET /api/v1/health/` must return `200` with `{"status":"ok"}`, and the frontend must load. |
| Documentation | Verify referenced paths exist and commands match the current implementation. |

Mock LDAP operations in tests; this repository has no local LDAP fixture. Report actual results and reasons for skipped checks. CI runs security scans only, not these checks.

## Hard Constraint

- LDAP is the sole source of truth; PostgreSQL is only a local cache and task queue. Changes requiring LDAP synchronization must update the cache and task queue in one transaction, then be written asynchronously by the ACTIVE node's Django-Q worker. The API must not write directly to `ou=Aliases`.
- Agents must not execute operations that mutate the LDAP tree, including `ldapadd`, `ldapmodify`, `ldapdelete`, or indirect writes through real API enqueue/worker flush operations. Provide steps for the user to execute instead.
- Destructive operations such as DB restore, `db_sync.sh`, and deleting data volumes require a confirmed target, backups, and human approval.
- `legacy/` contains personal team notes; do not read or reference them unless the user explicitly requests it.
