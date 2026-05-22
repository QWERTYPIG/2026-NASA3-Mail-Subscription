#!/usr/bin/env python3
import json
import logging
import os
import signal
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, request

DEFAULT_PEERS = "172.16.127.102,172.16.127.116,172.16.127.117"


@dataclass(frozen=True)
class Config:
    this_ip: str
    peers: list[str]
    monitor_port: int
    check_interval: int
    fail_threshold: int
    recover_threshold: int
    degraded_threshold: int
    sync_interval: int
    compose_file: str
    env_base: str
    env_role: str
    last_sync_file: str | None
    pg_port: int
    redis_port: int
    tcp_timeout: float
    health_timeout: float


@dataclass
class PeerStatus:
    ip: str
    pg_ok: bool
    redis_ok: bool
    monitor_reachable: bool
    worker_running: bool
    db_sync_ready: bool

    @property
    def core_healthy(self) -> bool:
        """Return True when all core health checks pass."""
        return (
            self.pg_ok and self.redis_ok and self.worker_running and self.db_sync_ready
        )


def parse_csv(raw: str) -> list[str]:
    """Split a comma-separated list into stripped entries."""
    return [item.strip() for item in raw.split(",") if item.strip()]


def dedupe(items: list[str]) -> list[str]:
    """Return a list with duplicates removed while preserving order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def load_config() -> Config:
    """Load monitor configuration from environment variables."""

    def require(name: str) -> str:
        """Return required env var or exit with an error."""
        value = os.environ.get(name)
        if not value:
            raise SystemExit(f"Missing required env: {name}")
        return value

    peers_raw = os.environ.get("MONITOR_PEERS") or DEFAULT_PEERS
    peers = dedupe(parse_csv(peers_raw))
    this_ip = require("THIS_MACHINE_IP")
    if this_ip not in peers:
        logging.warning(
            "THIS_MACHINE_IP %s not in peer list; appending to end.", this_ip
        )
        peers.append(this_ip)

    return Config(
        this_ip=this_ip,
        peers=peers,
        monitor_port=int(os.environ.get("MONITOR_PORT", "9123")),
        check_interval=int(os.environ.get("CHECK_INTERVAL", "15")),
        fail_threshold=int(os.environ.get("FAIL_THRESHOLD", "3")),
        recover_threshold=int(os.environ.get("RECOVER_THRESHOLD", "2")),
        degraded_threshold=int(os.environ.get("DEGRADED_THRESHOLD", "8")),
        sync_interval=int(os.environ.get("SYNC_INTERVAL", "600")),
        compose_file=require("COMPOSE_FILE"),
        env_base=require("ENV_BASE"),
        env_role=require("ENV_ROLE"),
        last_sync_file=os.environ.get("LAST_SYNC_FILE"),
        pg_port=int(os.environ.get("PG_PORT", "5432")),
        redis_port=int(os.environ.get("REDIS_PORT", "6379")),
        tcp_timeout=float(os.environ.get("TCP_TIMEOUT", "2.0")),
        health_timeout=float(os.environ.get("HEALTH_TIMEOUT", "2.0")),
    )


def setup_logging(log_level: str) -> None:
    """Configure global logging with the requested level."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def tcp_reachable(host: str, port: int, timeout: float) -> bool:
    """Return True if a TCP connection can be established to host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class Monitor:
    def __init__(self, config: Config) -> None:
        """Initialize monitor state and caches."""
        self.config = config
        self._compose_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._last_active: str | None = None
        self._candidate_active: str | None = None
        self._candidate_count = 0
        self._no_peer_count = 0
        self._degraded_mode = False
        self._health_cache: tuple[float, bool, bool] | None = None
        self._last_freshness_warning = 0.0
        self._last_no_active_warning = 0.0
        self._last_sync_file_warning = 0.0

    def start_health_server(self) -> None:
        """Start the HTTP health server in a background thread."""
        monitor = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                """Serve the /health endpoint with worker readiness details."""
                if self.path != "/health":
                    self.send_response(404)
                    self.end_headers()
                    return

                worker_running, db_sync_ready = monitor.local_worker_health()
                payload = {
                    "worker_running": worker_running,
                    "db_sync_ready": db_sync_ready,
                }
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                """Route HTTP handler logs through the logging module."""
                logging.info("health: " + format, *args)

        self._server = ThreadingHTTPServer(("", self.config.monitor_port), Handler)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._server_thread.start()
        logging.info("health endpoint listening on :%s", self.config.monitor_port)

    def stop(self) -> None:
        """Signal the main loop and HTTP server to stop."""
        self._stop_event.set()
        if self._server:
            self._server.shutdown()

    def run(self) -> None:
        """Run the monitor loop until a stop signal is received."""
        self.start_health_server()
        logging.info("monitor loop starting with peers=%s", ",".join(self.config.peers))

        while not self._stop_event.is_set():
            loop_start = time.time()
            self.run_once()
            elapsed = time.time() - loop_start
            sleep_for = max(0.0, self.config.check_interval - elapsed)
            self._stop_event.wait(timeout=sleep_for)
