from django.db import models
from django.core.validators import RegexValidator
from django.contrib.postgres.fields import ArrayField

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
    user_id = ArrayField(models.CharField(max_length=255), blank=True, default=list)

    class Meta:
        db_table = 'alias'

    def __str__(self):
        return self.alias_name

class AliasTaskQueue(models.Model):
    ACTION_CHOICES = [
        ('add', 'Add Alias'),
        ('remove', 'Remove Alias'),
    ]

    alias_name = models.CharField(max_length=255, validators=[alias_validator])
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)

    class Meta:
        db_table = 'alias_task_queue'
        ordering = ['id']

    def __str__(self):
        return f"{self.action} alias {self.alias_name}"

class UserTaskQueue(models.Model):
    ACTION_CHOICES = [
        ('add', 'Add Users'),
        ('remove', 'Remove Users'),
    ]

    alias_name = models.CharField(max_length=255, validators=[alias_validator])
    user_uid = models.CharField(max_length=255)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)

    class Meta:
        db_table = 'user_task_queue'
        ordering = ['id']

    def __str__(self):
        return f"{self.action} users on {self.alias_name}"
