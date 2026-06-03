import json
import logging
import os
import ssl
import time

from django.core.cache import cache
from ldap3 import LEVEL, MODIFY_ADD, MODIFY_DELETE, Connection, Server, Tls
from ldap3.core.exceptions import (
    LDAPAttributeOrValueExistsResult,
    LDAPEntryAlreadyExistsResult,
    LDAPException,
    LDAPNoSuchAttributeResult,
)

from .models import Alias, AliasTaskQueue, UserTaskQueue

LOGGER_NAME = "mailsub-worker"
logger = logging.getLogger(LOGGER_NAME)


def log_event(level: int, event: str, message: str, **fields: object) -> None:
    """Emit one JSON log event for journal, rsyslog, and Loki ingestion."""
    payload: dict[str, object] = {
        "level": logging.getLevelName(level),
        "logger": LOGGER_NAME,
        "event": event,
        "message": message,
    }
    payload.update({key: value for key, value in fields.items() if value is not None})
    logger.log(level, json.dumps(payload, sort_keys=True, default=str))

# ---------------------------------------------------------------------------
# LDAP constants
# ---------------------------------------------------------------------------

LDAP_URI = os.environ.get("LDAP_URI", "ldaps://172.16.127.109:636")
LDAP_BIND_DN = os.environ.get(
    "LDAP_BIND_DN",
    "uid=mailtest,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw",
)
LDAP_BIND_PASSWORD = os.environ.get("LDAP_BIND_PASSWORD", "")
LDAP_CA_CERT_FILE = os.environ.get("LDAP_CA_CERT_FILE", "")

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
            log_event(
                logging.WARNING,
                "ldap_retry",
                "LDAP error, retrying",
                delay_seconds=delay,
                error=str(exc),
            )
            time.sleep(delay)
    # Final attempt — no sleep afterwards
    return fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# LDAP connection
# ---------------------------------------------------------------------------

def _connect() -> Connection:
    if not LDAP_CA_CERT_FILE:
        raise RuntimeError(
            "LDAP_CA_CERT_FILE is not set — refusing to connect without certificate validation"
        )
    tls = Tls(ca_certs_file=LDAP_CA_CERT_FILE, validate=ssl.CERT_REQUIRED)
    server = Server(LDAP_URI, use_ssl=True, tls=tls, connect_timeout=10)
    try:
        conn = Connection(
            server,
            user=LDAP_BIND_DN,
            password=LDAP_BIND_PASSWORD,
            auto_bind=True,
            raise_exceptions=True,
        )
    except LDAPException as exc:
        log_event(
            logging.ERROR,
            "ldap_connect_failed",
            "failed to connect to LDAP",
            ldap_uri=LDAP_URI,
            bind_dn=LDAP_BIND_DN,
            error=str(exc),
        )
        raise
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
    failures: list[str] = []

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
                    log_event(
                        logging.INFO,
                        "alias_already_exists",
                        "alias already exists in LDAP, skipping add",
                        alias_name=task.alias_name,
                    )

            elif task.action == "remove":
                _with_retry(conn.delete, dn)
                # Remove dangling user tasks for this alias (race condition guard)
                UserTaskQueue.objects.filter(alias_name=task.alias_name).delete()

            task.delete()

        except LDAPException as exc:
            # All retries exhausted — leave row in queue; it retains its id so
            # it will still be processed first next flush
            log_event(
                logging.ERROR,
                "alias_task_failed",
                "gave up on alias task",
                action=task.action,
                alias_name=task.alias_name,
                error=str(exc),
            )
            failures.append(f"  - {task.action} {task.alias_name}: {exc}")

    if failures:
        log_event(
            logging.ERROR,
            "alias_flush_failed",
            "alias task failures during flush",
            failure_count=len(failures),
            failures=failures,
        )


def flush_user_tasks(conn: Connection) -> None:
    """Process all rows in UserTaskQueue in id order."""
    failures: list[str] = []

    for task in UserTaskQueue.objects.all():
        dn = _alias_dn(task.alias_name)
        member = _member_dn(task.user_uid)
        try:
            if task.action == "add":
                try:
                    _with_retry(
                        conn.modify, dn, {"uniqueMember": [(MODIFY_ADD, [member])]}
                    )
                except LDAPAttributeOrValueExistsResult:
                    log_event(
                        logging.INFO,
                        "user_already_member",
                        "user already a member of alias, skipping add",
                        user_uid=task.user_uid,
                        alias_name=task.alias_name,
                    )
            elif task.action == "remove":
                try:
                    _with_retry(
                        conn.modify, dn, {"uniqueMember": [(MODIFY_DELETE, [member])]}
                    )
                except LDAPNoSuchAttributeResult:
                    log_event(
                        logging.INFO,
                        "user_not_member",
                        "user not a member of alias, skipping remove",
                        user_uid=task.user_uid,
                        alias_name=task.alias_name,
                    )

            task.delete()

        except LDAPException as exc:
            log_event(
                logging.ERROR,
                "user_task_failed",
                "gave up on user task",
                action=task.action,
                user_uid=task.user_uid,
                alias_name=task.alias_name,
                error=str(exc),
            )
            failures.append(
                f"  - {task.action} {task.user_uid} @ {task.alias_name}: {exc}"
            )

    if failures:
        log_event(
            logging.ERROR,
            "user_flush_failed",
            "user task failures during flush",
            failure_count=len(failures),
            failures=failures,
        )


def run_consistency_check(conn: Connection) -> None:
    """Pull ou=Aliases from LDAP and sync into the Alias cache (DB).

    LDAP is the source of truth; DB is always updated to match LDAP.
    """
    try:
        conn.search(
            ALIASES_DN,
            "(objectClass=groupOfUniqueNames)",
            search_scope=LEVEL,
            attributes=["cn", "uniqueMember"],
        )

        ldap_alias_names = set()
        for entry in conn.entries:
            alias_name = entry.cn.value
            ldap_alias_names.add(alias_name)
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

        Alias.objects.exclude(alias_name__in=ldap_alias_names).delete()

    except Exception as exc:
        log_event(
            logging.ERROR,
            "consistency_check_failed",
            "run_consistency_check failed",
            error=str(exc),
        )
        raise


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
    if os.environ.get("FLUSH_ENABLED", "1") != "1":
        log_event(
            logging.INFO,
            "flush_disabled",
            "FLUSH_ENABLED is not 1, skipping",
        )
        return
    acquired = cache.add(FLUSH_LOCK_KEY, "1", FLUSH_LOCK_TTL)
    if not acquired:
        log_event(
            logging.INFO,
            "flush_lock_busy",
            "previous flush still running, skipping",
        )
        return

    try:
        conn = _connect()
        try:
            flush_alias_tasks(conn)
            flush_user_tasks(conn)
            run_consistency_check(conn)
        finally:
            conn.unbind()
    except Exception as exc:
        log_event(
            logging.ERROR,
            "flush_unexpected_error",
            "flush_ldap_tasks failed with an unexpected error",
            error=str(exc),
        )
    finally:
        cache.delete(FLUSH_LOCK_KEY)
