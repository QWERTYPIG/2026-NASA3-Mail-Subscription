"""The sync module: runs a whole Flush of the Queue against a Directory.

One call does everything::

    report = sync.flush(directory)

``directory`` is anything implementing the ``Directory`` protocol (in
production, the LDAP Directory). The Directory sees only ``Task`` and returns
``Outcome``; it never touches models or tables. This module owns the Queue
and the Cache, and does no logging: everything worth logging is in the
returned ``FlushReport``.

Guarantees:

- Only one Flush runs at a time per database: a PostgreSQL session advisory
  lock. If it is held, ``flush`` returns a busy report without calling the
  Directory. The lock is released when ``flush`` returns or raises.
- Only Tasks that existed when the Flush started are handed out, so a Flush
  always ends.
- Tasks are handed out lowest id first, across Alias and Member Tasks alike.
  A Task that committed late with a lower id is still applied before later
  Tasks of the same Alias.
- ``DONE`` and ``OBSOLETE`` remove the Task from the Queue. ``RETRY`` keeps it
  and blocks its Alias for the rest of the Flush; other Aliases continue.
- The Task budget is checked before each Task is handed out. Once it has
  elapsed, the Task in progress has already finished and the rest stay
  queued. The Snapshot is still taken.
- ``DirectoryUnavailable`` from ``apply`` keeps the Task queued, stops the
  Flush and skips the Snapshot.
- The Snapshot corrects the Cache one Alias at a time, under the same
  per-Alias lock the write path takes. Aliases that still have queued Tasks
  are skipped. Display fields are never changed. ``DirectoryUnavailable``
  from ``snapshot`` leaves the Cache untouched.
- Any other exception propagates after the lock is released; the Task in
  progress stays queued.
- The whole Flush runs on Django's default database connection.
"""

import time
from collections.abc import Mapping, Set
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from django.db import connection, transaction
from django.db.models import Max, Min
from django.utils import timezone

from .models import Alias, AliasMember, SyncTask
from .writes import _lock_aliases

# Two-key advisory lock for the Flush. The first key differs from the
# per-Alias write lock's namespace (writes.ALIAS_LOCK_NAMESPACE), so the two
# can never collide. ASCII "flsh".
FLUSH_LOCK_NAMESPACE = 0x666C7368
FLUSH_LOCK_KEY = 0

DEFAULT_TASK_BUDGET = 300  # seconds


@dataclass(frozen=True)
class Task:
    """One queued change, read-only."""

    id: int
    kind: str  # "alias" | "member"
    action: str  # "add" | "remove"
    alias_name: str
    user_uid: str | None  # set only for kind == "member"

    KIND_ALIAS = SyncTask.KIND_ALIAS
    KIND_MEMBER = SyncTask.KIND_MEMBER
    ACTION_ADD = SyncTask.ACTION_ADD
    ACTION_REMOVE = SyncTask.ACTION_REMOVE


class Outcome(str, Enum):
    DONE = "done"  # the Directory is in the intended state (including "already was")
    RETRY = "retry"  # failed; try again next Flush
    OBSOLETE = "obsolete"  # no longer meaningful, e.g. its Alias is gone


# Every Alias in the Directory mapped to its Member uids (no Placeholder
# member). Aliases without Members map to an empty set.
Snapshot = Mapping[str, Set[str]]


class DirectoryUnavailable(Exception):
    """The Directory itself cannot be used right now (e.g. LDAP is down)."""


class Directory(Protocol):
    def apply(self, task: Task) -> Outcome:
        """Write one Task and return its Outcome.

        Raises ``DirectoryUnavailable`` if the Directory cannot be used.
        """

    def snapshot(self) -> Snapshot:
        """Return a complete Snapshot, never a partial one.

        Raises ``DirectoryUnavailable`` if a complete Snapshot cannot be read.
        """


class StopReason(str, Enum):
    NONE = "none"  # every Task the Flush could hand out was handed out
    BUDGET = "budget"
    DIRECTORY_UNAVAILABLE = "directory_unavailable"


class SnapshotStatus(str, Enum):
    APPLIED = "applied"
    FAILED = "failed"  # snapshot() raised DirectoryUnavailable; Cache untouched
    NOT_TAKEN = "not_taken"  # busy, or the Directory was unavailable during apply


@dataclass
class FlushReport:
    busy: bool = False  # the flush lock was held elsewhere; nothing ran
    done_count: int = 0
    retried: list[Task] = field(default_factory=list)
    obsoleted: list[Task] = field(default_factory=list)
    stop_reason: StopReason = StopReason.NONE
    snapshot_status: SnapshotStatus = SnapshotStatus.NOT_TAKEN
    snapshot_updated: list[str] = field(default_factory=list)  # Alias names
    snapshot_skipped: list[str] = field(default_factory=list)  # Alias names
    elapsed: float = 0.0  # seconds
    oldest_task_age: float | None = None  # seconds; None if the Queue is empty

    @property
    def retry_count(self):
        return len(self.retried)

    @property
    def obsolete_count(self):
        return len(self.obsoleted)


def flush(directory, *, task_budget=DEFAULT_TASK_BUDGET, clock=time.monotonic):
    """Run one Flush against ``directory`` and return a ``FlushReport``.

    ``task_budget`` (seconds) and ``clock`` (monotonic seconds) are for tests.
    """
    started = clock()
    if not _try_lock():
        return FlushReport(busy=True, oldest_task_age=_oldest_task_age())
    try:
        report = FlushReport()
        _apply_tasks(directory, report, task_budget, started, clock)
        if report.stop_reason is not StopReason.DIRECTORY_UNAVAILABLE:
            _take_snapshot(directory, report)
        report.oldest_task_age = _oldest_task_age()
        report.elapsed = clock() - started
        return report
    finally:
        _unlock()


def _try_lock():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_lock(%s, %s)", [FLUSH_LOCK_NAMESPACE, FLUSH_LOCK_KEY]
        )
        return cursor.fetchone()[0]


def _unlock():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_unlock(%s, %s)", [FLUSH_LOCK_NAMESPACE, FLUSH_LOCK_KEY]
        )


def _apply_tasks(directory, report, task_budget, started, clock):
    max_id = SyncTask.objects.aggregate(m=Max("id"))["m"] or 0
    blocked = set()  # Aliases that got RETRY in this Flush
    while True:
        # No cursor: always take the lowest remaining id, so a Task that
        # committed late with a lower id is not skipped.
        row = (
            SyncTask.objects.filter(id__lte=max_id)
            .exclude(alias_name__in=blocked)
            .order_by("id")
            .first()
        )
        if row is None:
            return
        if clock() - started >= task_budget:
            report.stop_reason = StopReason.BUDGET
            return
        task = Task(
            id=row.id,
            kind=row.kind,
            action=row.action,
            alias_name=row.alias_name,
            user_uid=row.user_uid,
        )
        try:
            outcome = Outcome(directory.apply(task))
        except DirectoryUnavailable:
            report.stop_reason = StopReason.DIRECTORY_UNAVAILABLE
            return
        if outcome is Outcome.RETRY:
            blocked.add(task.alias_name)
            report.retried.append(task)
            continue
        SyncTask.objects.filter(id=task.id).delete()
        if outcome is Outcome.OBSOLETE:
            report.obsoleted.append(task)
        else:
            report.done_count += 1


def _take_snapshot(directory, report):
    try:
        snapshot = directory.snapshot()
    except DirectoryUnavailable:
        report.snapshot_status = SnapshotStatus.FAILED
        return
    snapshot = {name: set(uids) for name, uids in snapshot.items()}
    names = set(snapshot) | set(Alias.objects.values_list("alias_name", flat=True))
    for name in sorted(names):
        if _correct_alias(name, snapshot.get(name)):
            report.snapshot_updated.append(name)
        else:
            report.snapshot_skipped.append(name)
    report.snapshot_status = SnapshotStatus.APPLIED


@transaction.atomic
def _correct_alias(alias_name, uids):
    """Make one Alias's Cache match the Snapshot; ``uids is None`` = absent.

    Returns False (and changes nothing) if the Alias has queued Tasks.
    """
    _lock_aliases([alias_name])
    if SyncTask.objects.filter(alias_name=alias_name).exists():
        return False

    if uids is None:
        Alias.objects.filter(alias_name=alias_name).delete()
        return True

    alias, _ = Alias.objects.get_or_create(alias_name=alias_name)
    current = set(alias.members.values_list("user_uid", flat=True))
    alias.members.exclude(user_uid__in=uids).delete()
    AliasMember.objects.bulk_create(
        AliasMember(alias=alias, user_uid=uid) for uid in sorted(uids - current)
    )
    return True


def _oldest_task_age():
    oldest = SyncTask.objects.aggregate(t=Min("created_at"))["t"]
    if oldest is None:
        return None
    return (timezone.now() - oldest).total_seconds()
