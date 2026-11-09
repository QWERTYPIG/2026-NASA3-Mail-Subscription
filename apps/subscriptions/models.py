from django.db import models
from django.core.validators import RegexValidator

# Prevent LDAP Injection
alias_validator = RegexValidator(
    regex=r'^[a-zA-Z0-9-]+$',
    message='Alias name can only contain letters, numbers, and hyphens.'
)


class Alias(models.Model):
    alias_name = models.CharField(
        max_length=255,
        unique=True,
        primary_key=True,
        validators=[alias_validator]
    )
    display_name = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        db_table = 'alias'

    def __str__(self):
        return self.alias_name


class AliasMember(models.Model):
    """One row per (alias, member) pair — local cache of LDAP uniqueMember.

    Insertion order is kept by ``id`` so member lists stay in the order
    members were added.
    """

    alias = models.ForeignKey(
        Alias,
        on_delete=models.CASCADE,
        related_name='members',
        db_column='alias_name',
    )
    user_uid = models.CharField(max_length=255)

    class Meta:
        db_table = 'alias_member'
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(
                fields=['alias', 'user_uid'],
                name='alias_member_unique_alias_user',
            ),
        ]
        indexes = [
            models.Index(fields=['user_uid'], name='alias_member_user_uid_idx'),
        ]

    def __str__(self):
        return f"{self.user_uid} in {self.alias_id}"


class SyncTask(models.Model):
    """Single LDAP sync queue for alias and member changes.

    The auto-increment ``id`` is the global processing order across both
    kinds of task. No FK to ``alias``: a task must outlive the alias row
    (e.g. a pending ``alias/remove``).
    """

    KIND_ALIAS = 'alias'
    KIND_MEMBER = 'member'
    KIND_CHOICES = [
        (KIND_ALIAS, 'Alias'),
        (KIND_MEMBER, 'Member'),
    ]

    ACTION_ADD = 'add'
    ACTION_REMOVE = 'remove'
    ACTION_CHOICES = [
        (ACTION_ADD, 'Add'),
        (ACTION_REMOVE, 'Remove'),
    ]

    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    alias_name = models.CharField(max_length=255, validators=[alias_validator])
    user_uid = models.CharField(max_length=255, null=True, blank=True)
    # When the write path enqueued the task; shows how long it has waited.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sync_task'
        ordering = ['id']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind__in=['alias', 'member']),
                name='sync_task_kind_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(action__in=['add', 'remove']),
                name='sync_task_action_valid',
            ),
            # alias tasks carry no member; member tasks must carry one
            models.CheckConstraint(
                condition=(
                    models.Q(kind='alias', user_uid__isnull=True)
                    | models.Q(kind='member', user_uid__isnull=False)
                ),
                name='sync_task_user_uid_matches_kind',
            ),
        ]
        indexes = [
            models.Index(fields=['alias_name', 'id'], name='sync_task_alias_id_idx'),
        ]

    def __str__(self):
        if self.kind == self.KIND_MEMBER:
            return f"{self.action} member {self.user_uid} on {self.alias_name}"
        return f"{self.action} alias {self.alias_name}"
