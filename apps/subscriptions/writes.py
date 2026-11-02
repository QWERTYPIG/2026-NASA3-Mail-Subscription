"""Write side of the alias cache and LDAP sync queue.

Every API change that must reach LDAP goes through one of these functions.
Each function, in one transaction:

1. takes the per-alias lock (``_lock_aliases``),
2. updates the local cache (``alias`` / ``alias_member``),
3. enqueues the matching ``sync_task`` row.

The per-alias lock is a PostgreSQL transaction-level advisory lock, held
until commit. Two writes to the same alias therefore commit one after the
other, so within one alias the ``sync_task.id`` order equals commit order.
The lock works even when the alias row does not exist yet (create) or is
being deleted.

Views translate the exceptions below into HTTP responses; they must not
write ``SyncTask`` or ``AliasMember`` rows themselves.
"""

from django.db import connection, transaction

from .models import Alias, AliasMember, SyncTask

# First key of the two-key advisory lock, so these locks never collide with
# advisory locks taken elsewhere for other purposes. ASCII "mail".
ALIAS_LOCK_NAMESPACE = 0x6D61696C


class WriteError(Exception):
    """Base class for expected write-side failures."""


class AliasNotFound(WriteError):
    pass


class AliasExists(WriteError):
    pass


class MemberNotFound(WriteError):
    pass


class MemberExists(WriteError):
    pass


def _lock_aliases(alias_names):
    """Take the per-alias lock for each name, in sorted order.

    Sorted order keeps multi-alias writers (subscription PUT) from
    deadlocking with each other. Must run inside a transaction.
    """
    with connection.cursor() as cursor:
        for name in sorted(set(alias_names)):
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
                [ALIAS_LOCK_NAMESPACE, name],
            )


def _enqueue(kind, action, alias_name, user_uid=None):
    return SyncTask.objects.create(
        kind=kind, action=action, alias_name=alias_name, user_uid=user_uid
    )


def _get_alias(alias_name):
    try:
        return Alias.objects.get(alias_name=alias_name)
    except Alias.DoesNotExist:
        raise AliasNotFound(alias_name) from None


@transaction.atomic
def create_alias(alias_name, display_name="", description=""):
    """Create an alias and enqueue ``alias/add``. Raises ``AliasExists``."""
    _lock_aliases([alias_name])
    if Alias.objects.filter(alias_name=alias_name).exists():
        raise AliasExists(alias_name)
    alias = Alias.objects.create(
        alias_name=alias_name, display_name=display_name, description=description
    )
    _enqueue(SyncTask.KIND_ALIAS, SyncTask.ACTION_ADD, alias_name)
    return alias


@transaction.atomic
def delete_alias(alias_name):
    """Delete an alias (members cascade) and enqueue ``alias/remove``.

    Raises ``AliasNotFound``.
    """
    _lock_aliases([alias_name])
    alias = _get_alias(alias_name)
    _enqueue(SyncTask.KIND_ALIAS, SyncTask.ACTION_REMOVE, alias_name)
    alias.delete()


@transaction.atomic
def add_member(alias_name, user_uid):
    """Add a member and enqueue ``member/add``.

    Raises ``AliasNotFound`` or ``MemberExists``.
    """
    _lock_aliases([alias_name])
    alias = _get_alias(alias_name)
    if AliasMember.objects.filter(alias=alias, user_uid=user_uid).exists():
        raise MemberExists(alias_name, user_uid)
    AliasMember.objects.create(alias=alias, user_uid=user_uid)
    return _enqueue(SyncTask.KIND_MEMBER, SyncTask.ACTION_ADD, alias_name, user_uid)


@transaction.atomic
def remove_member(alias_name, user_uid):
    """Remove a member and enqueue ``member/remove``.

    Raises ``AliasNotFound`` or ``MemberNotFound``.
    """
    _lock_aliases([alias_name])
    alias = _get_alias(alias_name)
    deleted, _ = AliasMember.objects.filter(alias=alias, user_uid=user_uid).delete()
    if not deleted:
        raise MemberNotFound(alias_name, user_uid)
    return _enqueue(SyncTask.KIND_MEMBER, SyncTask.ACTION_REMOVE, alias_name, user_uid)


@transaction.atomic
def set_subscriptions(user_uid, desired):
    """Bring one user's memberships to ``desired`` ({alias_name: bool}).

    Only aliases whose state changes get a task. Aliases that no longer exist
    are skipped. Returns ``(changed_alias_names, task_ids)``, both in alias
    name order.
    """
    _lock_aliases(desired.keys())
    existing = set(
        Alias.objects.filter(alias_name__in=desired.keys()).values_list(
            "alias_name", flat=True
        )
    )
    subscribed = set(
        AliasMember.objects.filter(
            user_uid=user_uid, alias_id__in=existing
        ).values_list("alias_id", flat=True)
    )

    changed, task_ids = [], []
    for alias_name in sorted(existing):
        want = desired[alias_name]
        if want == (alias_name in subscribed):
            continue
        if want:
            AliasMember.objects.create(alias_id=alias_name, user_uid=user_uid)
            action = SyncTask.ACTION_ADD
        else:
            AliasMember.objects.filter(alias_id=alias_name, user_uid=user_uid).delete()
            action = SyncTask.ACTION_REMOVE
        task = _enqueue(SyncTask.KIND_MEMBER, action, alias_name, user_uid)
        changed.append(alias_name)
        task_ids.append(task.id)
    return changed, task_ids
