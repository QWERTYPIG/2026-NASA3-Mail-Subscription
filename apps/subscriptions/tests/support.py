"""Shared test helpers for the flush lock: a second database session and the
flush lock taken or probed from it, as another worker process would."""

from django.db import DEFAULT_DB_ALIAS, connections

from .. import sync


def other_connection(test):
    """A second database session, as another worker process would have."""
    conn = connections.create_connection(DEFAULT_DB_ALIAS)
    conn.ensure_connection()
    test.addCleanup(conn.close)
    return conn


def hold_flush_lock(conn):
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_lock(%s, %s)",
            [sync.FLUSH_LOCK_NAMESPACE, sync.FLUSH_LOCK_KEY],
        )


def flush_lock_is_free(conn):
    """Take and release the flush lock from ``conn``; True if it was free."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_lock(%s, %s)",
            [sync.FLUSH_LOCK_NAMESPACE, sync.FLUSH_LOCK_KEY],
        )
        free = cursor.fetchone()[0]
        if free:
            cursor.execute(
                "SELECT pg_advisory_unlock(%s, %s)",
                [sync.FLUSH_LOCK_NAMESPACE, sync.FLUSH_LOCK_KEY],
            )
    return free
