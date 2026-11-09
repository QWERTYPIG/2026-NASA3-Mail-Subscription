"""The LDAP Directory: the only code that knows LDAP.

``LdapDirectory`` implements the ``Directory`` protocol of
``apps.subscriptions.sync``: ``apply(task)`` writes one Task and returns its
Outcome, ``snapshot()`` reads every Alias and its Member uids. DNs, result
codes, the Placeholder member (the bind DN), retry waits, timeouts, paged
Snapshot reading and Member DN parsing all live here. When LDAP itself cannot
be used, both raise ``DirectoryUnavailable``.
"""

import logging
import os
import re
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

from ldap3 import LEVEL, MODIFY_ADD, MODIFY_DELETE, Connection, Server, Tls
from ldap3.core.exceptions import (
    LDAPAttributeOrValueExistsResult,
    LDAPBusyResult,
    LDAPCommunicationError,
    LDAPEntryAlreadyExistsResult,
    LDAPException,
    LDAPExceptionError,
    LDAPNoSuchAttributeResult,
    LDAPNoSuchObjectResult,
    LDAPObjectClassViolationResult,
    LDAPOperationResult,
    LDAPResponseTimeoutError,
    LDAPUnavailableResult,
    LDAPUnwillingToPerformResult,
)

from .log import log_event
from .sync import DirectoryUnavailable, Outcome, Task

BASE_DN = "dc=csie,dc=ntu,dc=edu,dc=tw"
ALIASES_DN = f"ou=Aliases,{BASE_DN}"
PEOPLE_DN = f"ou=people,{BASE_DN}"

CONNECT_TIMEOUT = 10  # seconds to open the connection
RECEIVE_TIMEOUT = 10  # seconds to wait for each reply
RETRY_DELAYS = [0.5, 1, 2, 4, 8]  # seconds between attempts of one request
# No retry wait or attempt starts later than this many seconds after apply
# began. Fast failures still get every wait (15.5 s in all); slow ones stop
# early, so one Task cannot hold up the Flush for minutes.
APPLY_DEADLINE = 16
SNAPSHOT_BUDGET = 60  # seconds; checked before each page and before each retry
SNAPSHOT_PAGE_SIZE = 500

# Worst cases, in seconds. One attempt on a new connection blocks at most:
# TCP connect (CONNECT_TIMEOUT), then the TLS handshake, the bind and the
# request (RECEIVE_TIMEOUT each). This assumes the LDAP URI resolves to one
# address and each reply arrives within one receive timeout.
ATTEMPT_WORST = CONNECT_TIMEOUT + 3 * RECEIVE_TIMEOUT  # 40
# The last attempt starts by the deadline; removing the last Member adds the
# Placeholder fallback modify to it.
APPLY_WORST = APPLY_DEADLINE + ATTEMPT_WORST + RECEIVE_TIMEOUT  # 66
# The last page, or its retry, starts by the Snapshot budget.
SNAPSHOT_WORST = SNAPSHOT_BUDGET + ATTEMPT_WORST  # 100

_PAGED_RESULTS_OID = "1.2.840.113556.1.4.319"
# A Member DN is exactly uid=<uid>,ou=people,<base DN> (matched lowercased).
_MEMBER_DN = re.compile(r"uid=([^,=+\\\s]+)," + re.escape(PEOPLE_DN.lower()))


@dataclass(frozen=True)
class LdapConfig:
    uri: str
    bind_dn: str  # also the Placeholder member
    bind_password: str
    ca_cert_file: str

    @classmethod
    def from_env(cls):
        return cls(
            uri=os.environ.get("LDAP_URI", "ldaps://172.16.127.109:636"),
            bind_dn=os.environ.get(
                "LDAP_BIND_DN", "uid=mailtest,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw"
            ),
            bind_password=os.environ.get("LDAP_BIND_PASSWORD", ""),
            ca_cert_file=os.environ.get("LDAP_CA_CERT_FILE", ""),
        )


def connect(config):
    """Open and bind an ``ldap3`` Connection; refuses without a CA certificate."""
    if not config.ca_cert_file:
        raise RuntimeError(
            "LDAP_CA_CERT_FILE is not set - refusing to connect without certificate validation"
        )
    tls = Tls(ca_certs_file=config.ca_cert_file, validate=ssl.CERT_REQUIRED)
    server = Server(config.uri, use_ssl=True, tls=tls, connect_timeout=CONNECT_TIMEOUT)
    return Connection(
        server,
        user=config.bind_dn,
        password=config.bind_password,
        auto_bind=True,
        raise_exceptions=True,
        receive_timeout=RECEIVE_TIMEOUT,
    )


class LdapDirectory:
    """The production Directory (see ``apps.subscriptions.sync.Directory``).

    ``config`` defaults to ``LdapConfig.from_env()`` (``LDAP_URI``,
    ``LDAP_BIND_DN``, ``LDAP_BIND_PASSWORD``, ``LDAP_CA_CERT_FILE``). Building
    one opens no connection: it connects on first use. Call ``close()`` when
    done. ``clock`` (monotonic seconds) is for tests.
    """

    def __init__(self, config: LdapConfig | None = None, *, clock=time.monotonic):
        self._config = LdapConfig.from_env() if config is None else config
        self._clock = clock
        self._conn = None

    def close(self):
        """Disconnect, if connected. The Directory may be used again afterwards."""
        conn, self._conn = self._conn, None
        if conn is not None:
            conn.unbind()

    def apply(self, task):
        """Write one Task; see the Outcome table in docs/06-sync-interface.md."""
        deadline = self._clock() + APPLY_DEADLINE
        try:
            self._request(lambda conn: self._write(conn, task), deadline)
        except _LDAP_ERRORS as exc:
            return self._classify(task, exc)
        return Outcome.DONE

    def _write(self, conn, task):
        _rule(task).write(conn, task, self._config.bind_dn)

    def snapshot(self):
        """Read every Alias under ``ou=Aliases``, page by page; never partial."""
        deadline = self._clock() + SNAPSHOT_BUDGET
        snapshot = {}
        cookie = None
        while True:
            if self._clock() > deadline:
                self._snapshot_failed(f"Snapshot budget of {SNAPSHOT_BUDGET}s exceeded")
            try:
                entries, result = self._request(
                    lambda conn: self._search_page(conn, cookie), deadline
                )
            except _LDAP_ERRORS as exc:
                self._snapshot_failed(str(exc), exc)
            if result.get("result") != 0:
                self._snapshot_failed(f"search result {result.get('description')}")
            for found in entries:
                if found.get("type") == "searchResEntry":
                    name, members = self._read_entry(found)
                    if name is not None:
                        snapshot[name] = members
            cookie = _next_cookie(result)
            if not cookie:
                return snapshot

    def _search_page(self, conn, cookie):
        conn.search(
            ALIASES_DN,
            "(objectClass=groupOfUniqueNames)",
            search_scope=LEVEL,
            attributes=["cn", "uniqueMember"],
            paged_size=SNAPSHOT_PAGE_SIZE,
            paged_cookie=cookie,
        )
        return list(conn.response or []), dict(conn.result or {})

    def _snapshot_failed(self, error, cause=None):
        log_event(logging.ERROR, "snapshot_failed", "LDAP Snapshot failed", error=error)
        raise DirectoryUnavailable(error) from cause

    def _read_entry(self, found):
        """Return ``(alias_name, member_uids)``; ``alias_name`` is None if unusable."""
        attributes = found.get("attributes", {})
        cn = attributes.get("cn")
        name = (cn[0] if cn else None) if isinstance(cn, list) else cn
        if not name:
            log_event(
                logging.WARNING,
                "alias_entry_skipped",
                "Alias entry has no cn, skipped",
                dn=found.get("dn"),
            )
            return None, set()
        members = set()
        for member_dn in attributes.get("uniqueMember") or []:
            if member_dn.lower() == self._config.bind_dn.lower():
                continue  # the Placeholder member
            match = _MEMBER_DN.fullmatch(member_dn.lower())
            if match is None:
                log_event(
                    logging.WARNING,
                    "member_dn_skipped",
                    "member DN is not a people uid, skipped",
                    alias_name=name,
                    member_dn=member_dn,
                )
                continue
            members.add(match.group(1))
        return name, members

    # -- connection and retries ------------------------------------------------

    def _connection(self):
        if self._conn is None:
            try:
                self._conn = connect(self._config)
            except _LDAP_ERRORS as exc:
                log_event(
                    logging.ERROR,
                    "ldap_connect_failed",
                    "failed to connect to LDAP",
                    ldap_uri=self._config.uri,
                    bind_dn=self._config.bind_dn,
                    error=str(exc),
                )
                raise _ConnectFailed(str(exc)) from exc
        return self._conn

    def _discard_connection(self):
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.unbind()
            except _LDAP_ERRORS:
                pass

    def _request(self, fn, deadline):
        """Return ``fn(connection)``, retrying transient failures.

        Connection, server-availability and other non-result errors are
        retried after each of ``RETRY_DELAYS``; other result errors are raised
        at once. No wait (and so no retry) starts if it would end after
        ``deadline`` (clock seconds). Once retries stop, a failure meaning
        LDAP itself cannot be used raises ``DirectoryUnavailable``; anything
        else is re-raised.
        """
        for delay in (*RETRY_DELAYS, None):
            try:
                return fn(self._connection())
            except LDAPOperationResult as exc:
                if not isinstance(exc, _SERVER_UNAVAILABLE_RESULTS):
                    raise
                error = exc
            except _LDAP_ERRORS as exc:
                # The connection may be broken: open a new one next attempt.
                self._discard_connection()
                error = exc
            if delay is None:
                break
            if self._clock() + delay > deadline:
                log_event(
                    logging.WARNING,
                    "ldap_retry_deadline",
                    "LDAP error, no time left to retry",
                    error=str(error),
                )
                break
            log_event(
                logging.WARNING,
                "ldap_retry",
                "LDAP error, retrying",
                delay_seconds=delay,
                error=str(error),
            )
            time.sleep(delay)
        if isinstance(error, _UNAVAILABLE):
            log_event(
                logging.ERROR,
                "ldap_unavailable",
                "LDAP unavailable after retries",
                ldap_uri=self._config.uri,
                error=str(error),
            )
            raise DirectoryUnavailable(str(error)) from error
        raise error

    def _classify(self, task, exc):
        rule = _rule(task)
        already = rule.already_in_wanted_state
        if already is not None and isinstance(exc, already.result):
            log_event(
                logging.INFO,
                already.event,
                already.message,
                alias_name=task.alias_name,
                user_uid=task.user_uid,
            )
            return Outcome.DONE
        if isinstance(exc, LDAPNoSuchObjectResult) and rule.entry_missing is not None:
            return rule.entry_missing
        log_event(
            logging.ERROR,
            rule.failed_event,
            rule.failed_message,
            task_id=task.id,
            action=task.action,
            alias_name=task.alias_name,
            user_uid=task.user_uid,
            error=str(exc),
        )
        return Outcome.RETRY


class _ConnectFailed(LDAPExceptionError):
    """Opening or binding the connection failed."""


# Everything a request can raise that is an LDAP or network failure.
_LDAP_ERRORS = (LDAPException, OSError)

# Result codes meaning the server cannot serve requests right now.
_SERVER_UNAVAILABLE_RESULTS = (LDAPBusyResult, LDAPUnavailableResult, LDAPUnwillingToPerformResult)

# Failures meaning LDAP itself cannot be used (socket and connection errors,
# timeouts, server unavailability, failure to connect or bind).
_UNAVAILABLE = (
    _ConnectFailed,
    LDAPCommunicationError,
    LDAPResponseTimeoutError,
    OSError,
    *_SERVER_UNAVAILABLE_RESULTS,
)


def _alias_dn(alias_name):
    return f"cn={alias_name},{ALIASES_DN}"


def _member_dn(user_uid):
    return f"uid={user_uid},{PEOPLE_DN}"


def _next_cookie(result):
    """The paged-results cookie of a search reply; empty when no pages remain."""
    control = result.get("controls", {}).get(_PAGED_RESULTS_OID, {})
    return control.get("value", {}).get("cookie")


def _add_alias(conn, task, placeholder_dn):
    conn.add(
        _alias_dn(task.alias_name),
        object_class=["groupOfUniqueNames"],
        attributes={"cn": task.alias_name, "uniqueMember": [placeholder_dn]},
    )


def _delete_alias(conn, task, placeholder_dn):
    conn.delete(_alias_dn(task.alias_name))


def _add_member(conn, task, placeholder_dn):
    conn.modify(
        _alias_dn(task.alias_name),
        {"uniqueMember": [(MODIFY_ADD, [_member_dn(task.user_uid)])]},
    )


def _remove_member(conn, task, placeholder_dn):
    dn = _alias_dn(task.alias_name)
    member = _member_dn(task.user_uid)
    try:
        conn.modify(dn, {"uniqueMember": [(MODIFY_DELETE, [member])]})
    except LDAPObjectClassViolationResult:
        # The last Member: keep the entry valid with the Placeholder member,
        # in the same modify. It is never removed afterwards.
        conn.modify(
            dn,
            {"uniqueMember": [(MODIFY_ADD, [placeholder_dn]), (MODIFY_DELETE, [member])]},
        )


class _AlreadyInWantedState(NamedTuple):
    """The LDAP result meaning a Task's change is already in LDAP (Done)."""

    result: type[LDAPOperationResult]
    event: str  # INFO event logged when it happens
    message: str


class _TaskRule(NamedTuple):
    """Everything LDAP-specific about one (kind, action) of Task."""

    write: Callable[[Connection, Task, str], None]  # (conn, task, Placeholder member DN)
    already_in_wanted_state: _AlreadyInWantedState | None
    entry_missing: Outcome | None  # Outcome on noSuchObject; None means Retry
    failed_event: str  # ERROR event for a Retry, with the LDAP error
    failed_message: str


# Member Task events say "user" (user_task_failed, user_already_member,
# user_not_member and their "user ..." messages) on purpose: the names are
# kept from the old flush code so existing log queries and alerts keep
# working. They mean a Member. See docs/06-sync-interface.md.
_ALIAS_TASK_FAILED = ("alias_task_failed", "gave up on alias task")
_MEMBER_TASK_FAILED = ("user_task_failed", "gave up on user task")

# The single source of how each Task becomes an LDAP request and which LDAP
# reply means which Outcome (the Outcome table in docs/06-sync-interface.md).
_TASK_RULES = {
    (Task.KIND_ALIAS, Task.ACTION_ADD): _TaskRule(
        _add_alias,
        _AlreadyInWantedState(
            LDAPEntryAlreadyExistsResult,
            "alias_already_exists",
            "alias already exists in LDAP, skipping add",
        ),
        None,
        *_ALIAS_TASK_FAILED,
    ),
    (Task.KIND_ALIAS, Task.ACTION_REMOVE): _TaskRule(
        _delete_alias, None, Outcome.DONE, *_ALIAS_TASK_FAILED
    ),
    (Task.KIND_MEMBER, Task.ACTION_ADD): _TaskRule(
        _add_member,
        _AlreadyInWantedState(
            LDAPAttributeOrValueExistsResult,
            "user_already_member",
            "user already a member of alias, skipping add",
        ),
        Outcome.OBSOLETE,
        *_MEMBER_TASK_FAILED,
    ),
    (Task.KIND_MEMBER, Task.ACTION_REMOVE): _TaskRule(
        _remove_member,
        _AlreadyInWantedState(
            LDAPNoSuchAttributeResult,
            "user_not_member",
            "user not a member of alias, skipping remove",
        ),
        Outcome.OBSOLETE,
        *_MEMBER_TASK_FAILED,
    ),
}


def _rule(task):
    return _TASK_RULES[(task.kind, task.action)]
