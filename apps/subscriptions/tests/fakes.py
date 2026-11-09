"""Shared test doubles for the Flush. Import from tests that need a Directory.

``FakeDirectory`` is an in-memory Directory (see ``apps.subscriptions.sync``):
no LDAP, no mocks. Script it, run ``sync.flush(directory)``, then inspect
what it was asked to do.
"""

from ..sync import Outcome


class FakeDirectory:
    """In-memory Directory with scripted Outcomes and Snapshot.

    - ``outcomes`` maps a Task id, or an Alias name (for every Task of that
      Alias), to the Outcome ``apply`` returns. A Task id entry wins over an
      Alias name entry. A value may also be an exception instance, which
      ``apply`` raises (e.g. ``DirectoryUnavailable()``). Anything not listed
      gets ``default``.
    - ``snapshot`` is what ``snapshot()`` returns: ``{alias_name: set_of_uids}``.
      It may be an exception instance, which ``snapshot()`` raises.
    - ``on_apply`` is called with each Task before its Outcome is returned,
      e.g. to enqueue more Tasks or advance a fake clock mid-Flush.

    After a Flush, ``applied`` lists every Task handed to ``apply`` in order,
    and ``snapshot_calls`` counts calls to ``snapshot()``.
    """

    def __init__(self, *, outcomes=None, default=Outcome.DONE, snapshot=None, on_apply=None):
        self.outcomes = dict(outcomes or {})
        self.default = default
        self.snapshot_result = {} if snapshot is None else snapshot
        self.on_apply = on_apply
        self.applied = []
        self.snapshot_calls = 0

    def apply(self, task):
        self.applied.append(task)
        if self.on_apply is not None:
            self.on_apply(task)
        result = self.outcomes.get(task.id, self.outcomes.get(task.alias_name, self.default))
        if isinstance(result, BaseException):
            raise result
        return result

    def snapshot(self):
        self.snapshot_calls += 1
        if isinstance(self.snapshot_result, BaseException):
            raise self.snapshot_result
        return {name: set(uids) for name, uids in self.snapshot_result.items()}
