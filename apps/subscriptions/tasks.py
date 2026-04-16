import logging
import os
import time

from django.core.cache import cache
from ldap3 import LEVEL, MODIFY_ADD, MODIFY_DELETE, Connection, Server
from ldap3.core.exceptions import LDAPEntryAlreadyExistsResult, LDAPException

from core.mail import send_alert_email

from .models import Alias, AliasTaskQueue, UserTaskQueue

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LDAP constants
# ---------------------------------------------------------------------------

LDAP_URI = os.environ.get("LDAP_URI", "ldap://172.16.127.109:389")
LDAP_BIND_DN = os.environ.get(
    "LDAP_BIND_DN",
    "uid=mailtest,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw",
)
LDAP_BIND_PASSWORD = os.environ.get("LDAP_BIND_PASSWORD", "")

BASE_DN = "dc=csie,dc=ntu,dc=edu,dc=tw"
ALIASES_DN = f"ou=Aliases,{BASE_DN}"
PEOPLE_DN = f"ou=people,{BASE_DN}"

# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------

RETRY_DELAYS = [0.5, 1, 2, 4, 8]  # seconds between attempts


def _with_retry(fn, *args, **kwargs):
    """Call fn(*args, **kwargs), retrying on LDAPException with exponential backoff.

    Raises the last LDAPException if all retries are exhausted.
    """
    for delay in RETRY_DELAYS:
        try:
            return fn(*args, **kwargs)
        except LDAPException as exc:
            logger.warning("LDAP error, retrying in %.1fs: %s", delay, exc)
            time.sleep(delay)
    # Final attempt — no sleep afterwards
    return fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# LDAP connection
# ---------------------------------------------------------------------------


def _connect() -> Connection:
    server = Server(LDAP_URI, connect_timeout=10)
    if not server:
        send_alert_email(
            recipients=["chilfox@csie.ntu.edu.tw", "qwertypig@csie.ntu.edu.tw", "bbwinner@csie.ntu.edu.tw"],
            subject="LDAP Connection Failure",
            body=f"Failed to initialize LDAP server object for URI: {LDAP_URI}",
        )
    conn = Connection(
        server,
        user=LDAP_BIND_DN,
        password=LDAP_BIND_PASSWORD,
        auto_bind=True,
        raise_exceptions=True,
    )
    return conn


# ---------------------------------------------------------------------------
# Flush helpers
# ---------------------------------------------------------------------------


def _alias_dn(alias_name: str) -> str:
    return f"cn={alias_name},{ALIASES_DN}"


def _member_dn(user_uid: str) -> str:
    return f"uid={user_uid},{PEOPLE_DN}"


def flush_alias_tasks(conn: Connection) -> None:
    """Process all rows in AliasTaskQueue in id order."""
    for task in AliasTaskQueue.objects.all():
        dn = _alias_dn(task.alias_name)
        try:
            if task.action == "add":
                # groupOfUniqueNames requires at least one uniqueMember.
                # Use the bind DN as a placeholder; consistency check will
                # correct the member list after the first real subscription.
                try:
                    _with_retry(
                        conn.add,
                        dn,
                        object_class=["groupOfUniqueNames"],
                        attributes={
                            "cn": task.alias_name,
                            "uniqueMember": [LDAP_BIND_DN],
                        },
                    )
                except LDAPEntryAlreadyExistsResult:
                    # Entry already exists in LDAP — desired state reached,
                    # no retry needed.
                    logger.info(
                        "flush_alias_tasks: %s already exists in LDAP, skipping add",
                        task.alias_name,
                    )

            elif task.action == "remove":
                _with_retry(conn.delete, dn)
                # Remove dangling user tasks for this alias (race condition guard)
                UserTaskQueue.objects.filter(alias_name=task.alias_name).delete()

            task.delete()

        except LDAPException as exc:
            # All retries exhausted — leave row in queue; it retains its id so
            # it will still be processed first next flush
            logger.error(
                "flush_alias_tasks: gave up on %s %s — %s",
                task.action,
                task.alias_name,
                exc,
            )


def flush_user_tasks(conn: Connection) -> None:
    """Process all rows in UserTaskQueue in id order."""
    for task in UserTaskQueue.objects.all():
        dn = _alias_dn(task.alias_name)
        member = _member_dn(task.user_uid)
        try:
            if task.action == "add":
                _with_retry(conn.modify, dn, {"uniqueMember": [(MODIFY_ADD, [member])]})
            elif task.action == "remove":
                _with_retry(
                    conn.modify, dn, {"uniqueMember": [(MODIFY_DELETE, [member])]}
                )

            task.delete()

        except LDAPException as exc:
            logger.error(
                "flush_user_tasks: gave up on %s %s @ %s — %s",
                task.action,
                task.user_uid,
                task.alias_name,
                exc,
            )


def run_consistency_check(conn: Connection) -> None:
    """Pull ou=Aliases from LDAP and sync into the Alias cache (DB).

    LDAP is the source of truth; DB is always updated to match LDAP.
    """
    conn.search(
        ALIASES_DN,
        "(objectClass=groupOfUniqueNames)",
        search_scope=LEVEL,
        attributes=["cn", "uniqueMember"],
    )

    for entry in conn.entries:
        alias_name = entry.cn.value
        raw_members = entry.uniqueMember.values if entry.uniqueMember else []

        user_ids = []
        for member_dn in raw_members:
            # Full DN format: uid=<uid>,ou=people,...
            # Skip the placeholder bind DN used when an alias has no real members.
            if member_dn == LDAP_BIND_DN:
                continue
            if member_dn.startswith("uid="):
                uid = member_dn.split(",")[0][len("uid=") :]
                user_ids.append(uid)

        Alias.objects.update_or_create(
            alias_name=alias_name,
            defaults={"user_id": user_ids},
        )


# ---------------------------------------------------------------------------
# Entry point registered with Django-Q Schedule
# ---------------------------------------------------------------------------

FLUSH_LOCK_KEY = "flush_ldap_tasks_lock"
FLUSH_LOCK_TTL = 300  # seconds — must exceed worst-case flush duration


def flush_ldap_tasks() -> None:
    """Main scheduled task: flush task queues then run consistency check.

    A Redis lock prevents overlapping runs when the previous flush takes
    longer than the 3-minute schedule interval.
    """
    acquired = cache.add(FLUSH_LOCK_KEY, "1", FLUSH_LOCK_TTL)
    if not acquired:
        logger.info("flush_ldap_tasks: previous flush still running, skipping")
        return

    try:
        conn = _connect()
        try:
            flush_alias_tasks(conn)
            flush_user_tasks(conn)
            run_consistency_check(conn)
        finally:
            conn.unbind()
    except Exception:
        logger.exception("flush_ldap_tasks: unexpected error")
    finally:
        cache.delete(FLUSH_LOCK_KEY)
