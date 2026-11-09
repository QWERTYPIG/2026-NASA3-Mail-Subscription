import logging
import os

from django.core.cache import cache
from ldap3 import LEVEL, MODIFY_ADD, MODIFY_DELETE, Connection
from ldap3.core.exceptions import (
    LDAPAttributeOrValueExistsResult,
    LDAPEntryAlreadyExistsResult,
    LDAPException,
    LDAPNoSuchAttributeResult,
)

from .ldap_directory import ALIASES_DN, PEOPLE_DN, LdapConfig, connect
from .log import log_event
from .models import Alias, AliasTaskQueue, UserTaskQueue

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
                    conn.add(
                        dn,
                        object_class=["groupOfUniqueNames"],
                        attributes={
                            "cn": task.alias_name,
                            "uniqueMember": [conn.user],
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
                conn.delete(dn)
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
                    conn.modify(dn, {"uniqueMember": [(MODIFY_ADD, [member])]})
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
                    conn.modify(dn, {"uniqueMember": [(MODIFY_DELETE, [member])]})
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
                if member_dn == conn.user:
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
        conn = connect(LdapConfig.from_env())
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
