"""The scheduled Flush entry point, registered with a Django-Q Schedule.

A thin wrapper: check ``FLUSH_ENABLED``, build the LDAP Directory, run
``sync.flush`` and log the flush report. All Flush rules live in the sync
module; all LDAP knowledge lives in the LDAP Directory.
"""

import logging
import os

from . import sync
from .ldap_directory import LdapDirectory
from .log import log_event


def flush_ldap_tasks() -> None:
    """Run one Flush against LDAP, unless this node has Flush disabled."""
    if os.environ.get("FLUSH_ENABLED", "1") != "1":
        log_event(logging.INFO, "flush_disabled", "FLUSH_ENABLED is not 1, skipping")
        return

    try:
        report = _run_flush()
    except Exception as exc:
        log_event(
            logging.ERROR,
            "flush_unexpected_error",
            "flush_ldap_tasks failed with an unexpected error",
            error=str(exc),
        )
        return
    _log_report(report)


def _run_flush():
    directory = LdapDirectory()
    try:
        return sync.flush(directory)
    finally:
        directory.close()


def _log_report(report):
    if report.busy:
        log_event(logging.INFO, "flush_lock_busy", "previous flush still running, skipping")
        return

    # Each Retry is already logged by the LDAP Directory as alias_task_failed /
    # user_task_failed, with the LDAP error only it knows; not repeated here.
    for task in report.obsoleted:
        log_event(
            logging.INFO,
            "task_obsolete",
            "task no longer meaningful in LDAP, dropped",
            task_id=task.id,
            kind=task.kind,
            action=task.action,
            alias_name=task.alias_name,
            user_uid=task.user_uid,
        )
    log_event(
        logging.INFO,
        "flush_summary",
        "flush finished",
        done_count=report.done_count,
        retry_count=report.retry_count,
        obsolete_count=report.obsolete_count,
        stop_reason=report.stop_reason.value,
        snapshot_status=report.snapshot_status.value,
        snapshot_updated=report.snapshot_updated,
        snapshot_skipped=report.snapshot_skipped,
        elapsed_seconds=round(report.elapsed, 3),
        oldest_task_age_seconds=report.oldest_task_age,
    )
