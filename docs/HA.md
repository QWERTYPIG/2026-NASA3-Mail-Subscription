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

## Syncing (TBD)
Need a worker to sync the two backup DBs with main DB.
