"""Shared JSON event logging for the background Flush.

Both the scheduled task module and the LDAP Directory log through
``log_event``, so every event has the same shape and logger name.
"""

import json
import logging
from collections.abc import Iterable

LOGGER_NAME = "mailsub-worker"
logger = logging.getLogger(LOGGER_NAME)


def log_event(
    level: int,
    event: str,
    message: str,
    *,
    keep_null: Iterable[str] = (),
    **fields: object,
) -> None:
    """Emit one JSON log event for journal, rsyslog, and Loki ingestion.

    Fields whose value is None are omitted, except those named in
    ``keep_null``, which are always present (as JSON null when None).
    """
    payload: dict[str, object] = {
        "level": logging.getLevelName(level),
        "logger": LOGGER_NAME,
        "event": event,
        "message": message,
    }
    keep_null = set(keep_null)
    payload.update(
        {key: value for key, value in fields.items() if value is not None or key in keep_null}
    )
    logger.log(level, json.dumps(payload, sort_keys=True, default=str))
