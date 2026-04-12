import logging
import os
import time

from django.core.cache import cache
from ldap3 import LEVEL, MODIFY_ADD, MODIFY_DELETE, Connection, Server
from ldap3.core.exceptions import LDAPException

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
    server = Server(LDAP_URI)
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
                _with_retry(
                    conn.add,
                    dn,
                    object_class=["groupOfUniqueNames"],
                    attributes={
                        "cn": task.alias_name,
                        "uniqueMember": [LDAP_BIND_DN],
                    },


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
