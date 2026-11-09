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
from dataclasses import dataclass

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
SNAPSHOT_BUDGET = 60  # seconds; checked before each Snapshot page
SNAPSHOT_PAGE_SIZE = 500

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

    Configuration not passed in is read from the environment (``LDAP_URI``,
    ``LDAP_BIND_DN``, ``LDAP_BIND_PASSWORD``, ``LDAP_CA_CERT_FILE``). Building
    one opens no connection: it connects on first use. Call ``close()`` when
    done. ``clock`` (monotonic seconds) is for tests.
    """

    def __init__(
        self,
        *,
        uri=None,
        bind_dn=None,
        bind_password=None,
        ca_cert_file=None,
        clock=time.monotonic,
    ):
        env = LdapConfig.from_env()
        self._config = LdapConfig(
            uri=env.uri if uri is None else uri,
            bind_dn=env.bind_dn if bind_dn is None else bind_dn,
            bind_password=env.bind_password if bind_password is None else bind_password,
            ca_cert_file=env.ca_cert_file if ca_cert_file is None else ca_cert_file,
        )
        self._clock = clock
        self._conn = None

    def close(self):
        """Disconnect, if connected. The Directory may be used again afterwards."""
        conn, self._conn = self._conn, None
        if conn is not None:
            conn.unbind()

    def apply(self, task):
        """Write one Task; see the Outcome table in docs/06-sync-interface.md."""
        try:
            self._request(lambda conn: self._write(conn, task))
        except _LDAP_ERRORS as exc:
            return self._classify(task, exc)
        return Outcome.DONE

    def _write(self, conn, task):
        dn = _alias_dn(task.alias_name)
        if task.kind == Task.KIND_ALIAS:
            if task.action == Task.ACTION_ADD:
                conn.add(
                    dn,
                    object_class=["groupOfUniqueNames"],
                    attributes={"cn": task.alias_name, "uniqueMember": [self._config.bind_dn]},
                )
            else:
                conn.delete(dn)
            return
        member = _member_dn(task.user_uid)
        if task.action == Task.ACTION_ADD:
            conn.modify(dn, {"uniqueMember": [(MODIFY_ADD, [member])]})
            return
        try:
            conn.modify(dn, {"uniqueMember": [(MODIFY_DELETE, [member])]})
        except LDAPObjectClassViolationResult:
            # The last Member: keep the entry valid with the Placeholder
            # member, in the same modify. It is never removed afterwards.
            conn.modify(
                dn,
                {
                    "uniqueMember": [
                        (MODIFY_ADD, [self._config.bind_dn]),
                        (MODIFY_DELETE, [member]),
                    ]
                },
            )

    def snapshot(self):
        """Read every Alias under ``ou=Aliases``, page by page; never partial."""
        started = self._clock()
        snapshot = {}
        cookie = None
        while True:
            if self._clock() - started > SNAPSHOT_BUDGET:
                self._snapshot_failed(f"Snapshot budget of {SNAPSHOT_BUDGET}s exceeded")
            try:
                entries, result = self._request(lambda conn: self._search_page(conn, cookie))
            except _LDAP_ERRORS as exc:
                self._snapshot_failed(str(exc), exc)
            if result.get("result") != 0:
                self._snapshot_failed(f"search result {result.get('description')}")
            for found in entries:
                if found.get("type") == "searchResEntry":
                    name, members = self._read_entry(found)
                    snapshot[name] = members
            cookie = (
                result.get("controls", {}).get(_PAGED_RESULTS_OID, {}).get("value", {}).get("cookie")
            )
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
        attributes = found.get("attributes", {})
        cn = attributes.get("cn")
        name = cn[0] if isinstance(cn, list) else cn
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

    def _request(self, fn):
        """Return ``fn(connection)``, retrying transient failures.

        Connection, server-availability and other non-result errors are
        retried after each of ``RETRY_DELAYS``; other result errors are raised
        at once. Once the waits run out, a failure meaning LDAP itself cannot
        be used raises ``DirectoryUnavailable``; anything else is re-raised.
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
        already = _ALREADY_IN_WANTED_STATE.get((task.kind, task.action))
        if already is not None and isinstance(exc, already[0]):
            log_event(
                logging.INFO,
                already[1],
                already[2],
                alias_name=task.alias_name,
                user_uid=task.user_uid,
            )
            return Outcome.DONE
        if isinstance(exc, LDAPNoSuchObjectResult):
            if task.kind == Task.KIND_MEMBER:
                return Outcome.OBSOLETE
            if task.action == Task.ACTION_REMOVE:
                return Outcome.DONE
        log_event(
            logging.ERROR,
            f"{_EVENT_KIND[task.kind]}_task_failed",
            f"gave up on {_EVENT_KIND[task.kind]} task",
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


# Event names kept from the old flush code: "alias_task_failed" / "user_task_failed".
_EVENT_KIND = {Task.KIND_ALIAS: "alias", Task.KIND_MEMBER: "user"}

# (kind, action) -> (result meaning "already in the wanted state", event, message)
_ALREADY_IN_WANTED_STATE = {
    (Task.KIND_ALIAS, Task.ACTION_ADD): (
        LDAPEntryAlreadyExistsResult,
        "alias_already_exists",
        "alias already exists in LDAP, skipping add",
    ),
    (Task.KIND_MEMBER, Task.ACTION_ADD): (
        LDAPAttributeOrValueExistsResult,
        "user_already_member",
        "user already a member of alias, skipping add",
    ),
    (Task.KIND_MEMBER, Task.ACTION_REMOVE): (
        LDAPNoSuchAttributeResult,
        "user_not_member",
        "user not a member of alias, skipping remove",
    ),
}
