"""Sync interface: the only thing the LDAP sync side (``tasks.py``) imports.

The sync side never touches models or tables. It sees three formats:

- ``Task``: one queued change, read-only.
- ``Outcome``: what happened to a task in LDAP.
- Snapshot: ``{alias_name: set_of_uids}`` for every alias in LDAP (uids, not
  DNs; no placeholder member).

Call flow::

    with sync.flush_session() as session:
        while (task := session.next_task()) is not None:
            ...apply task to LDAP...
            session.report(task, sync.Outcome.DONE)
        session.apply_snapshot(read_ldap_snapshot())

Guarantees:

- Tasks come out in ``id`` order. Within one alias, that is the order the
  API writes committed.
- After an alias's task is reported ``RETRY``, the session gives out no more
  tasks for that alias. Other aliases continue.
- ``DONE`` and ``OBSOLETE`` tasks leave the queue. ``RETRY`` tasks stay and
  are retried in the same position next session.
- A task fetched but not reported counts as ``RETRY`` (when the next task is
  fetched, or when the session ends).
- A session only gives out tasks that existed when it opened, so it always
  ends.
- ``apply_snapshot`` does not overwrite the cache for an alias that still has
  queued tasks. Each alias is checked and written under the same per-alias
  lock the API writes take, so an API write cannot slip in between.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum

from django.db import transaction
from django.db.models import Max

from .models import Alias, AliasMember, SyncTask
from .writes import _lock_aliases


@dataclass(frozen=True)
class Task:
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
    DONE = "done"  # LDAP is in the intended state
    RETRY = "retry"  # temporary failure; try again next session
    OBSOLETE = "obsolete"  # the task no longer makes sense; drop it


@dataclass(frozen=True)
class SnapshotResult:
    updated: list[str]  # aliases whose cache now matches the snapshot
    skipped: list[str]  # aliases left alone because tasks are still queued


class SessionError(Exception):
    """Interface misuse, e.g. reporting a task that is not outstanding."""


class FlushSession:
    """One pass over the queue. Get it from ``flush_session()``."""

    def __init__(self):
        self._max_id = SyncTask.objects.aggregate(m=Max("id"))["m"] or 0
        self._blocked = set()  # aliases that hit RETRY this session
        self._outstanding = None  # task given out, not yet reported
        self._closed = False

    def next_task(self):
        """Return the next ``Task``, or ``None`` when the session is done."""
        self._check_open()
        self._retry_outstanding()
        # No cursor: always take the lowest remaining id. A task whose
        # transaction committed late (lower id, seen later) is still given
        # out before any later task of the same alias.
        row = (
            SyncTask.objects.filter(id__lte=self._max_id)
            .exclude(alias_name__in=self._blocked)
            .order_by("id")
            .first()
        )
        if row is None:
            return None
        self._outstanding = Task(
            id=row.id,
            kind=row.kind,
            action=row.action,
            alias_name=row.alias_name,
            user_uid=row.user_uid,
        )
        return self._outstanding

    def report(self, task, outcome):
        """Report the outcome of the task last returned by ``next_task``."""
        self._check_open()
        if self._outstanding is None or task.id != self._outstanding.id:
            raise SessionError(f"task {task.id} is not the outstanding task")
        outcome = Outcome(outcome)
        if outcome is Outcome.RETRY:
            self._blocked.add(task.alias_name)
        else:
            SyncTask.objects.filter(id=task.id).delete()
        self._outstanding = None

    def apply_snapshot(self, snapshot):
        """Make the cache match LDAP for every alias without queued tasks.

        ``snapshot`` maps every alias in LDAP to its set of member uids.
        Aliases in the cache but missing from the snapshot are deleted.
        Returns a ``SnapshotResult``.
        """
        self._check_open()
        self._retry_outstanding()
        snapshot = {name: set(uids) for name, uids in snapshot.items()}
        names = set(snapshot) | set(Alias.objects.values_list("alias_name", flat=True))

        updated, skipped = [], []
        for name in sorted(names):
            if _apply_one(name, snapshot.get(name)):
                updated.append(name)
            else:
                skipped.append(name)
        return SnapshotResult(updated=updated, skipped=skipped)

    def _retry_outstanding(self):
        if self._outstanding is not None:
            self._blocked.add(self._outstanding.alias_name)
            self._outstanding = None

    def _check_open(self):
        if self._closed:
            raise SessionError("session is closed")

    def _close(self):
        self._retry_outstanding()
        self._closed = True


@contextmanager
def flush_session():
    """Open a flush session. Unreported tasks count as ``RETRY`` on exit."""
    session = FlushSession()
    try:
        yield session
    finally:
        session._close()


@transaction.atomic
def _apply_one(alias_name, uids):
    """Overwrite one alias's cache from LDAP; ``uids is None`` = not in LDAP.

    Returns False (and changes nothing) if the alias has queued tasks.
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
