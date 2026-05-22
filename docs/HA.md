# Mail Subscription System — High Availability
## Machines
| Name | IP | Usage |
|------|----|-------|
| mail1 | 172.16.127.102 | default main DB and Redis; frontend and backend server |
| mail2 | 172.16.127.116 | backup DB and Redis; frontend and backend server |
| mail3 | 172.16.127.117 | backup main DB and Redis; frontend and backend server |
| mail4 | 172.16.127.118 | Nginx reverse-proxy |

## Structure
Each machine has its own copy of all containers.
One machine is used as main DB (default mail1), and all workers / backend read main DB for data.
The same machine hosts Redis, which is used to store TTL and locks.
Nginx reverse-proxy sends both frontend and backend requests to the three machines in round-robin fashion.
Main machine is switched by changing `DB_HOST` in .env (TBD).

## Syncing
The main DB is selected by `DB_HOST` in `.env`. A worker script syncs the
primary to the other two machines every 10 minutes using `pg_dump` and
`pg_restore`.

- Script: [scripts/db_sync.sh](scripts/db_sync.sh)
- Primary discovery: `DB_HOST` in `.env` on the worker machine
- Targets: `DB_REPLICA_HOSTS` (comma-separated list of the mail1/2/3 IPs)
- Trigger: parent scheduler runs the script every 10 minutes
