"""Test A: Single operation latency baseline.

Measures how long each ldapmodify takes (add + remove = 1 round).
Run: LDAP_BIND_PASSWORD=xxx uv run python scripts/test_a_baseline.py
"""

import os
import statistics
import time

from ldap3 import MODIFY_ADD, MODIFY_DELETE, Connection, Server
from ldap3.core.exceptions import LDAPEntryAlreadyExistsResult, LDAPNoSuchObjectResult

LDAP_URI = os.environ.get("LDAP_URI", "ldap://172.16.127.109:389")
LDAP_BIND_DN = os.environ.get(
    "LDAP_BIND_DN", "uid=mailtest,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw"
)
LDAP_BIND_PASSWORD = os.environ.get("LDAP_BIND_PASSWORD", "")

BASE_DN = "dc=csie,dc=ntu,dc=edu,dc=tw"
ALIASES_DN = f"ou=Aliases,{BASE_DN}"
PEOPLE_DN = f"ou=people,{BASE_DN}"

TEST_ALIAS_DN = f"cn=latency-test,{ALIASES_DN}"
MEMBER_DN = f"uid=b13902992,{PEOPLE_DN}"

ROUNDS = 50


def connect() -> Connection:
    server = Server(LDAP_URI, connect_timeout=10)
    return Connection(
        server,
        user=LDAP_BIND_DN,
        password=LDAP_BIND_PASSWORD,
        auto_bind=True,
        raise_exceptions=True,
    )


def setup(conn: Connection) -> None:
    # groupOfUniqueNames requires at least one uniqueMember — use the bind DN
    # as a placeholder, same pattern as the real worker in tasks.py
    try:
        conn.add(
            TEST_ALIAS_DN,
            object_class=["groupOfUniqueNames"],
            attributes={"cn": "latency-test", "uniqueMember": [LDAP_BIND_DN]},
        )
        print(f"Created {TEST_ALIAS_DN}")
    except LDAPEntryAlreadyExistsResult:
        print(f"{TEST_ALIAS_DN} already exists, reusing it")


def cleanup_member(conn: Connection) -> None:
    # Make sure the test member isn't already in the alias before we start,
    # otherwise the first MODIFY_ADD will fail with "already exists"
    try:
        conn.modify(TEST_ALIAS_DN, {"uniqueMember": [(MODIFY_DELETE, [MEMBER_DN])]})
    except LDAPNoSuchObjectResult:
        pass
    except Exception:
        pass


def main() -> None:
    conn = connect()
    setup(conn)
    cleanup_member(conn)

    times_ms: list[float] = []
    print(f"\nRunning {ROUNDS} rounds (add + remove per round)...\n")

    for i in range(ROUNDS):
        # Time one full add+remove pair — this mirrors one user_task_queue entry
        # being processed (subscribe then unsubscribe counts as two tasks,
        # but we batch them here to get a per-round number)
        start = time.perf_counter()
        conn.modify(TEST_ALIAS_DN, {"uniqueMember": [(MODIFY_ADD, [MEMBER_DN])]})
        conn.modify(TEST_ALIAS_DN, {"uniqueMember": [(MODIFY_DELETE, [MEMBER_DN])]})
        elapsed = (time.perf_counter() - start) * 1000
        times_ms.append(elapsed)
        print(f"  [{i + 1:3d}/{ROUNDS}]  {elapsed:.1f} ms")

    times_ms.sort()
    n = len(times_ms)
    # p50 = typical case, p95/p99 = tail latency (what slow requests look like)
    print(f"\n--- Results ({n} rounds × 2 ops = {n * 2} total operations) ---")
    print(f"  min  = {times_ms[0]:.1f} ms")
    print(f"  p50  = {times_ms[n // 2]:.1f} ms")
    print(f"  p95  = {times_ms[int(n * 0.95)]:.1f} ms")
    print(f"  p99  = {times_ms[int(n * 0.99)]:.1f} ms")
    print(f"  max  = {times_ms[-1]:.1f} ms")
    print(f"  mean = {statistics.mean(times_ms):.1f} ms")

    conn.unbind()


if __name__ == "__main__":
    main()
