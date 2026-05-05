"""Test C: Read latency during writes.

Measures whether our sequential flush affects ldapsearch latency
(which SSH login and other LDAP services depend on).

Two threads run simultaneously:
  - Write thread: sends sequential ldapmodify (simulating a flush)
  - Read monitor:  sends ldapsearch every 200ms and records the latency

Results are compared against a baseline (ldapsearch with no writes).
Run: LDAP_BIND_PASSWORD=xxx uv run python scripts/test_c_impact.py
"""

import os
import statistics
import threading
import time

from ldap3 import LEVEL, MODIFY_ADD, MODIFY_DELETE, Connection, Server
from ldap3.core.exceptions import LDAPEntryAlreadyExistsResult

LDAP_URI = os.environ.get("LDAP_URI", "ldap://172.16.127.109:389")
LDAP_BIND_DN = os.environ.get(
    "LDAP_BIND_DN", "uid=mailtest,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw"
)
LDAP_BIND_PASSWORD = os.environ.get("LDAP_BIND_PASSWORD", "")

BASE_DN = "dc=csie,dc=ntu,dc=edu,dc=tw"
ALIASES_DN = f"ou=Aliases,{BASE_DN}"
PEOPLE_DN = f"ou=people,{BASE_DN}"

TEST_ALIAS_DN = f"cn=latency-test,{ALIASES_DN}"
MEMBER_992 = f"uid=b13902992,{PEOPLE_DN}"
MEMBER_994 = f"uid=b13902994,{PEOPLE_DN}"
OP_CYCLE = [
    (MODIFY_ADD, MEMBER_992),
    (MODIFY_DELETE, MEMBER_992),
    (MODIFY_ADD, MEMBER_994),
    (MODIFY_DELETE, MEMBER_994),
]

WRITE_OPS = 2000  # total write ops to simulate the flush
READ_INTERVAL = 0.2  # seconds between each ldapsearch
BASELINE_READS = 200  # ldapsearch samples before writes start


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
    for member in [MEMBER_992, MEMBER_994]:
        try:
            conn.modify(TEST_ALIAS_DN, {"uniqueMember": [(MODIFY_DELETE, [member])]})
        except Exception:
            pass


def measure_search(conn: Connection) -> float:
    """Return ldapsearch latency in ms.

    Searches ou=Aliases — the same query our consistency check runs,
    and similar to what SSH auth does against ou=people.
    """
    start = time.perf_counter()
    conn.search(ALIASES_DN, "(objectClass=groupOfUniqueNames)", search_scope=LEVEL)
    return (time.perf_counter() - start) * 1000


def write_worker(conn: Connection, stop_event: threading.Event) -> None:
    # Simulates flush_user_tasks() in tasks.py: sequential ldapmodify ops
    # on a single connection, no concurrency
    for i in range(WRITE_OPS):
        if stop_event.is_set():
            break
        op_type, member = OP_CYCLE[i % len(OP_CYCLE)]
        try:
            conn.modify(TEST_ALIAS_DN, {"uniqueMember": [(op_type, [member])]})
        except Exception:
            pass
    # Signal the read monitor to stop once all writes are done
    stop_event.set()


def read_monitor(conn: Connection, stop_event: threading.Event) -> list[float]:
    # Polls ldapsearch every READ_INTERVAL seconds until writes finish.
    # Each sample represents "how long would an SSH login or mail auth take?"
    samples: list[float] = []
    while not stop_event.is_set():
        samples.append(measure_search(conn))
        time.sleep(READ_INTERVAL)
    return samples


def summarize(label: str, samples: list[float]) -> None:
    s = sorted(samples)
    n = len(s)
    print(f"\n  {label} ({n} samples)")
    print(f"    min  = {s[0]:.1f} ms")
    print(f"    p50  = {s[n // 2]:.1f} ms")
    print(f"    p95  = {s[int(n * 0.95)]:.1f} ms")
    print(f"    max  = {s[-1]:.1f} ms")
    print(f"    mean = {statistics.mean(s):.1f} ms")


def main() -> None:
    # Two separate connections: one for writes, one for reads.
    # ldap3 Connection is not thread-safe, so each thread needs its own.
    write_conn = connect()
    read_conn = connect()

    setup(write_conn)
    cleanup_members(write_conn)

    # --- Phase 1: baseline (no writes) ---
    print(f"\nMeasuring baseline ({BASELINE_READS} ldapsearch, no writes)...")
    baseline = [measure_search(read_conn) for _ in range(BASELINE_READS)]

    # --- Phase 2: writes and reads running simultaneously ---
    print(f"\nStarting write load ({WRITE_OPS} sequential ldapmodify ops)...")
    print("Measuring ldapsearch latency during writes...\n")

    stop_event = threading.Event()
    read_results: list[float] = []

    def read_thread_fn() -> None:
        nonlocal read_results
        read_results = read_monitor(read_conn, stop_event)

    t_write = threading.Thread(target=write_worker, args=(write_conn, stop_event))
    t_read = threading.Thread(target=read_thread_fn)

    # Start read monitor first so it's already sampling when writes begin
    t_read.start()
    t_write.start()
    t_write.join()
    t_read.join()

    # --- Results ---
    print("\n=== Results ===")
    summarize("Baseline (no writes)", baseline)
    summarize("During flush (sequential writes)", read_results)

    baseline_p50 = sorted(baseline)[len(baseline) // 2]
    load_p50 = sorted(read_results)[len(read_results) // 2]
    delta = load_p50 - baseline_p50
    # A delta under 50ms is generally acceptable for a LAN LDAP server
    print(
        f"\n  p50 delta = {delta:+.1f} ms  ({'acceptable' if abs(delta) < 50 else 'significant impact'})"
    )

    cleanup_members(write_conn)
    write_conn.unbind()
    read_conn.unbind()


if __name__ == "__main__":
    main()
