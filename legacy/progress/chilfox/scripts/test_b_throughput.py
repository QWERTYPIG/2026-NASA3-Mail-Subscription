"""Test B: Flush duration vs queue depth.

Simulates N sequential ldapmodify operations (like a flush with N tasks).
Answers: "how long would a flush with N pending tasks take?"
Run: LDAP_BIND_PASSWORD=xxx uv run python scripts/test_b_throughput.py
"""

import os
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

# Cycle through these 4 ops to simulate a realistic task queue
MEMBER_992 = f"uid=b13902992,{PEOPLE_DN}"
MEMBER_994 = f"uid=b13902994,{PEOPLE_DN}"
OP_CYCLE = [
    (MODIFY_ADD, MEMBER_992),
    (MODIFY_DELETE, MEMBER_992),
    (MODIFY_ADD, MEMBER_994),
    (MODIFY_DELETE, MEMBER_994),
]

QUEUE_SIZES = [10, 50, 100, 200, 1000, 5000, 10000, 20000, 50000]
LOCK_TTL_SECONDS = 300  # from tasks.py — flush must finish within this


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
    try:
        conn.add(
            TEST_ALIAS_DN,
            object_class=["groupOfUniqueNames"],
            attributes={"cn": "latency-test", "uniqueMember": [LDAP_BIND_DN]},
        )
        print(f"Created {TEST_ALIAS_DN}")
    except LDAPEntryAlreadyExistsResult:
        print(f"{TEST_ALIAS_DN} already exists, reusing it")


def cleanup_members(conn: Connection) -> None:
    # Remove both test members so the next run starts from a clean state
    for member in [MEMBER_992, MEMBER_994]:
        try:
            conn.modify(TEST_ALIAS_DN, {"uniqueMember": [(MODIFY_DELETE, [member])]})
        except Exception:
            pass


def run_n_ops(conn: Connection, n: int) -> float:
    """Run n sequential ldapmodify ops, return total elapsed seconds."""
    # Clean before timing so the clock only measures LDAP ops, not setup
    cleanup_members(conn)
    start = time.perf_counter()
    for i in range(n):
        # Cycle through add/remove for both users so LDAP state stays valid
        # (you can't add a member that already exists)
        op_type, member = OP_CYCLE[i % len(OP_CYCLE)]
        conn.modify(TEST_ALIAS_DN, {"uniqueMember": [(op_type, [member])]})
    elapsed = time.perf_counter() - start
    cleanup_members(conn)
    return elapsed


def main() -> None:
    conn = connect()
    setup(conn)

    print(
        f"\n{'N tasks':>10}  {'Total time':>12}  {'ops/sec':>10}  {'vs lock TTL':>12}"
    )
    print("-" * 52)

    for n in QUEUE_SIZES:
        elapsed = run_n_ops(conn, n)
        ops_per_sec = n / elapsed
        # If this percentage approaches 100%, a large queue could exceed the
        # Redis lock TTL (300s) and the next scheduled flush would be skipped
        pct_of_ttl = (elapsed / LOCK_TTL_SECONDS) * 100
        warning = " ⚠️  exceeds TTL!" if elapsed > LOCK_TTL_SECONDS else ""
        print(
            f"{n:>10}  {elapsed:>10.2f}s  {ops_per_sec:>10.1f}  {pct_of_ttl:>10.1f}%{warning}"
        )

    conn.unbind()


if __name__ == "__main__":
    main()
