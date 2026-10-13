# DB Sync

## Where LDAP sync lives

The LDAP sync logic is implemented as a Django-Q scheduled task.

- Task implementation: [apps/subscriptions/tasks.py](apps/subscriptions/tasks.py)
  - Entry point: `flush_ldap_tasks()`
  - Flushes alias/user task queues, then runs consistency check
- Schedule registration (every 3 minutes): [apps/subscriptions/migrations/0002_add_flush_ldap_schedule.py](apps/subscriptions/migrations/0002_add_flush_ldap_schedule.py)
- Worker process: Django-Q `qcluster` (see [core/settings.py](core/settings.py))

## DB sync worker (pg_dump)

The DB sync worker script is:

- Script: [scripts/db_sync.sh](scripts/db_sync.sh)

### What it does

- Reads primary DB host from `DB_HOST` in `.env` (or environment)
- Runs `pg_dump` on primary
- Runs `pg_restore` on the other two hosts listed in `DB_REPLICA_HOSTS`
- Skips locks (parent script is responsible for coordination)

### Required env

- `DB_HOST` (primary DB host)
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- Optional: `DB_REPLICA_HOSTS` (comma-separated list, defaults to mail1/2/3)
- Optional: `ENV_FILE` (override which env file to load)

### Requirements

- `pg_dump`, `pg_restore`, `psql` installed on the worker machine
- Network access to all DB hosts on port 5432

Install on Ubuntu on three machines:

```
sudo apt-get update
sudo apt-get install -y postgresql-client
```

### Notes

- Primary DB is chosen by the `.env` on the machine that runs the worker.
- The script is designed to be called by a parent scheduler (cron/monitor).
- If replicas are down, the script will exit with an error when it cannot connect.

### Testing

Test flow used:

1. Update the workstation alias from the frontend UI.
2. Run the DB sync script to propagate changes.
3. Verify on mail1/mail2/mail3 using the SQL commands below.

```
docker compose exec -T postgres psql -U MailAdmin -d Subscriptions -c \
"SELECT alias_name, display_name, description FROM alias WHERE alias_name='workstation';"
```