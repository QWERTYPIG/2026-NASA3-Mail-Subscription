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
LOGGER_NAME = "mailsub-monitor"
LOGGER = logging.getLogger(LOGGER_NAME)


def log_event(level: int, event: str, message: str, **fields: object) -> None:
    """Emit one JSON log event for systemd journal and Loki ingestion."""
    payload = {
        "level": logging.getLevelName(level),
        "logger": LOGGER_NAME,
        "event": event,
        "message": message,
    }
    payload.update({key: value for key, value in fields.items() if value is not None})
    LOGGER.log(level, json.dumps(payload, sort_keys=True, default=str))


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
    db_name: str
    db_user: str
    last_sync_file: str | None
    pg_port: int
    redis_port: int
    web_port: int
    frontend_port: int
    tcp_timeout: float
    health_timeout: float


@dataclass(frozen=True)
class LocalHealth:
    worker_running: bool
    db_sync_ready: bool
    web_running: bool
    web_api_ok: bool
    frontend_running: bool
    frontend_http_ok: bool

    def to_payload(self) -> dict[str, bool]:
        return {
            "worker_running": self.worker_running,
            "db_sync_ready": self.db_sync_ready,
            "web_running": self.web_running,
            "web_api_ok": self.web_api_ok,
            "frontend_running": self.frontend_running,
            "frontend_http_ok": self.frontend_http_ok,
        }


@dataclass
class PeerStatus:
    ip: str
    pg_ok: bool
    redis_ok: bool
    monitor_reachable: bool
    worker_running: bool
    db_sync_ready: bool
    web_running: bool = False
    web_api_ok: bool = False
    frontend_running: bool = False
    frontend_http_ok: bool = False

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
        log_event(
            logging.WARNING,
            "this_ip_not_in_peer_list",
            "THIS_MACHINE_IP not in peer list; appending to end",
            this_ip=this_ip,
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
        db_name=os.environ.get("DB_NAME", "Subscriptions"),
        db_user=os.environ.get("DB_USER", "MailAdmin"),
        last_sync_file=os.environ.get("LAST_SYNC_FILE"),
        pg_port=int(os.environ.get("PG_PORT", "5432")),
        redis_port=int(os.environ.get("REDIS_PORT", "6379")),
        web_port=int(os.environ.get("WEB_PORT", "8000")),
        frontend_port=int(os.environ.get("FRONTEND_PORT", os.environ.get("VITE_PORT", "55111"))),
        tcp_timeout=float(os.environ.get("TCP_TIMEOUT", "2.0")),
        health_timeout=float(os.environ.get("HEALTH_TIMEOUT", "2.0")),
    )


def setup_logging(log_level: str) -> None:
    """Configure global logging with the requested level."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(message)s",
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
        self._health_cache: tuple[float, LocalHealth] | None = None
        self._last_serving_health: dict[str, bool] | None = None
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

                payload = monitor.local_health().to_payload()
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                """Route HTTP handler logs through the logging module."""
                log_event(
                    logging.INFO,
                    "health_http_request",
                    format % args,
                )

        self._server = ThreadingHTTPServer(("", self.config.monitor_port), Handler)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._server_thread.start()
        log_event(
            logging.INFO,
            "health_endpoint_listening",
            "monitor health endpoint listening",
            port=self.config.monitor_port,
        )

    def stop(self) -> None:
        """Signal the main loop and HTTP server to stop."""
        self._stop_event.set()
        if self._server:
            self._server.shutdown()

    def run(self) -> None:
        """Run the monitor loop until a stop signal is received."""
        self.start_health_server()
        log_event(
            logging.INFO,
            "monitor_loop_starting",
            "monitor loop starting",
            peers=self.config.peers,
        )

        while not self._stop_event.is_set():
            loop_start = time.time()
            self.run_once()
            elapsed = time.time() - loop_start
            sleep_for = max(0.0, self.config.check_interval - elapsed)
            self._stop_event.wait(timeout=sleep_for)

    def run_once(self) -> None:
        """Execute one monitoring cycle of checks and role transitions."""
        statuses = self.collect_peer_statuses()
        any_peer_reachable = any(
            status.monitor_reachable
            for ip, status in statuses.items()
            if ip != self.config.this_ip
        )

        if any_peer_reachable:
            if self._degraded_mode:
                log_event(
                    logging.WARNING,
                    "peer_reachability_restored",
                    "peer reachability restored; exiting degraded mode",
                )
            self._degraded_mode = False
            self._no_peer_count = 0
        else:
            self._no_peer_count += 1

        desired_active = self.determine_active(statuses)
        desired_active = self.apply_peer_fence(desired_active, any_peer_reachable)

        if desired_active is None:
            now = time.time()
            # Avoid too frequent logging
            if now - self._last_no_active_warning > 60:
                log_event(
                    logging.WARNING,
                    "no_eligible_active",
                    "no eligible ACTIVE; keeping current role",
                    current_active=self._last_active,
                )
                self._last_no_active_warning = now
            self._candidate_active = None
            self._candidate_count = 0
            # Assume local machine is ACTIVE but Redis bye-bye for 5 sec
            # local machine become unhealthy -> desired_active is none
            # However before handing out ACTIVE flag, we should still try to do DB sync
            self.maybe_run_db_sync(self._last_active)
            return

        if desired_active == self._last_active:
            self._candidate_active = None
            self._candidate_count = 0
            self.maybe_run_db_sync(self._last_active)
            return

        if self._candidate_active == desired_active:
            self._candidate_count += 1
        else:
            self._candidate_active = desired_active
            self._candidate_count = 1

        required = self.required_threshold(self._last_active, desired_active)
        log_event(
            logging.INFO,
            "active_candidate_progress",
            "ACTIVE candidate progress",
            candidate_active=desired_active,
            candidate_count=self._candidate_count,
            required_count=required,
        )

        if self._candidate_count < required:
            self.maybe_run_db_sync(self._last_active)
            return

        if (
            self.is_failback(self._last_active, desired_active)
            and desired_active == self.config.this_ip
        ):
            if not self.is_sync_fresh():
                now = time.time()
                if now - self._last_freshness_warning > 60:
                    log_event(
                        logging.WARNING,
                        "failback_blocked_stale_sync",
                        "failback blocked: last sync too old or missing",
                        desired_active=desired_active,
                    )
                    self._last_freshness_warning = now
                self._candidate_active = None
                self._candidate_count = 0
                self.maybe_run_db_sync(self._last_active)
                return

        if desired_active == self.config.this_ip:
            if not self.local_postgres_writable():
                log_event(
                    logging.WARNING,
                    "active_transition_blocked_postgres_readonly",
                    "local postgres not writable; aborting ACTIVE transition",
                    desired_active=desired_active,
                )
                self._candidate_active = None
                self._candidate_count = 0
                self.maybe_run_db_sync(self._last_active)
                return

        old_active = self._last_active
        self._last_active = desired_active
        self._candidate_active = None
        self._candidate_count = 0

        log_event(
            logging.INFO,
            "active_transition",
            "ACTIVE transition",
            old_active=old_active,
            new_active=desired_active,
        )
        self.apply_role(desired_active)
        self.maybe_run_db_sync(self._last_active)

    def apply_peer_fence(
        self, desired_active: str | None, any_peer_reachable: bool
    ) -> str | None:
        """Apply peer-reachability fencing and degraded-mode rules."""
        # This means that there exists peer with healthy service and healthy priority
        # -> just use it
        if desired_active != self.config.this_ip:
            return desired_active

        # Since exist reachable peer we can infer that it is not this machine who's disconnected
        if any_peer_reachable:
            return desired_active

        # This machine is currently ACTIVE
        if self._last_active == self.config.this_ip:
            # Cannot connect to any peer but I'm ACTIVE before disconnecting
            # We infer that other two machines down thus we stay ACTIVE with degraded mode
            if (
                self._no_peer_count >= self.config.degraded_threshold
                and not self._degraded_mode
            ):
                log_event(
                    logging.WARNING,
                    "degraded_mode_staying_active",
                    "no peers reachable; staying ACTIVE in degraded mode",
                    active_ip=self.config.this_ip,
                )
                self._degraded_mode = True
            return desired_active

        # No peer reachable, wait more time to determine whether to enter degraded mode
        if self._no_peer_count < self.config.degraded_threshold:
            if self._no_peer_count == 1:
                log_event(
                    logging.WARNING,
                    "self_activation_deferred",
                    "no peers reachable; deferring self-activation until degraded threshold",
                    no_peer_count=self._no_peer_count,
                    degraded_threshold=self.config.degraded_threshold,
                )
            return None

        # Enter degraded mode
        if not self._degraded_mode:
            log_event(
                logging.WARNING,
                "degraded_mode_self_activation",
                "no peers reachable; entering degraded mode for self-activation",
                active_ip=self.config.this_ip,
            )
            self._degraded_mode = True
        return desired_active

    def determine_active(self, statuses: dict[str, PeerStatus]) -> str | None:
        """Return the highest-priority peer that is core-healthy."""
        for ip in self.config.peers:
            status = statuses.get(ip)
            if status and status.core_healthy:
                return ip
        return None

    def required_threshold(self, last_active: str | None, desired_active: str) -> int:
        """Choose the stabilization threshold for a role transition."""
        if last_active is None:
            return self.config.recover_threshold

        if self.is_failback(last_active, desired_active):
            return self.config.recover_threshold

        return self.config.fail_threshold

    def is_failback(self, last_active: str | None, desired_active: str) -> bool:
        """Return True when switching to a higher-priority peer."""
        if last_active is None:
            return False

        # dict [ip: priority]
        priority = {ip: idx for idx, ip in enumerate(self.config.peers)}

        # Maybe misconfiguration in MONITOR_PEERS
        if last_active not in priority or desired_active not in priority:
            return False
        return priority[desired_active] < priority[last_active]

    def is_sync_fresh(self) -> bool:
        """Return True if the last DB sync is within the freshness window."""
        if not self.config.last_sync_file:
            return False
        try:
            with open(self.config.last_sync_file, "r", encoding="utf-8") as handle:
                raw = handle.read().strip()
        except FileNotFoundError:
            return False
        except OSError as exc:
            log_event(
                logging.WARNING,
                "last_sync_file_read_failed",
                "failed to read LAST_SYNC_FILE",
                path=self.config.last_sync_file,
                error=str(exc),
            )
            return False

        if not raw.isdigit():
            log_event(
                logging.WARNING,
                "last_sync_file_invalid",
                "LAST_SYNC_FILE contains invalid timestamp",
                path=self.config.last_sync_file,
                value=raw,
            )
            return False

        last_sync = int(raw)
        age = time.time() - last_sync

        # Allow the DB sync with age two times of sync interval
        return age <= self.config.sync_interval * 2

    def collect_peer_statuses(self) -> dict[str, PeerStatus]:
        """Gather health details for all peers and return a status map."""
        statuses: dict[str, PeerStatus] = {}
        local_health = self.local_health()

        for ip in self.config.peers:
            pg_ok = tcp_reachable(ip, self.config.pg_port, self.config.tcp_timeout)
            redis_ok = tcp_reachable(
                ip, self.config.redis_port, self.config.tcp_timeout
            )

            if ip == self.config.this_ip:
                status = PeerStatus(
                    ip=ip,
                    pg_ok=pg_ok,
                    redis_ok=redis_ok,
                    monitor_reachable=True,
                    worker_running=local_health.worker_running,
                    db_sync_ready=local_health.db_sync_ready,
                    web_running=local_health.web_running,
                    web_api_ok=local_health.web_api_ok,
                    frontend_running=local_health.frontend_running,
                    frontend_http_ok=local_health.frontend_http_ok,
                )
            else:
                # 戳 /health api provided by monitor peer
                health = self.fetch_peer_health(ip)
                monitor_reachable = health is not None
                worker_running = bool(health.get("worker_running")) if health else False
                db_sync_ready = bool(health.get("db_sync_ready")) if health else False
                web_running = bool(health.get("web_running")) if health else False
                web_api_ok = bool(health.get("web_api_ok")) if health else False
                frontend_running = (
                    bool(health.get("frontend_running")) if health else False
                )
                frontend_http_ok = (
                    bool(health.get("frontend_http_ok")) if health else False
                )
                status = PeerStatus(
                    ip=ip,
                    pg_ok=pg_ok,
                    redis_ok=redis_ok,
                    monitor_reachable=monitor_reachable,
                    worker_running=worker_running,
                    db_sync_ready=db_sync_ready,
                    web_running=web_running,
                    web_api_ok=web_api_ok,
                    frontend_running=frontend_running,
                    frontend_http_ok=frontend_http_ok,
                )

            statuses[ip] = status

        return statuses

    def local_health(self) -> LocalHealth:
        """Check local core and serving health."""
        now = time.time()

        if self._health_cache and (now - self._health_cache[0]) < 3:
            return self._health_cache[1]

        worker_running = self.compose_service_running("worker")
        db_sync_ready = self.worker_db_sync_ready() if worker_running else False

        web_running = self.compose_service_running("web")
        web_target = f"http://127.0.0.1:{self.config.web_port}/api/v1/health/"
        web_api_ok = web_running and self.http_ok(web_target, {200})

        frontend_running = self.compose_service_running("frontend")
        frontend_target = f"http://127.0.0.1:{self.config.frontend_port}/"
        frontend_http_ok = frontend_running and self.http_ok(
            frontend_target, range(200, 400)
        )

        health = LocalHealth(
            worker_running=worker_running,
            db_sync_ready=db_sync_ready,
            web_running=web_running,
            web_api_ok=web_api_ok,
            frontend_running=frontend_running,
            frontend_http_ok=frontend_http_ok,
        )
        self._health_cache = (now, health)
        self.log_serving_health_transitions(health)
        return health

    def local_worker_health(self) -> tuple[bool, bool]:
        """Check local worker running state and db sync readiness."""
        health = self.local_health()
        return health.worker_running, health.db_sync_ready

    def log_serving_health_transitions(self, health: LocalHealth) -> None:
        """Log serving down/recovered events when web/frontend health changes."""
        checks = {
            "web_running": (
                "web",
                health.web_running,
                "web compose service is not running",
                "web compose service recovered",
                "web",
            ),
            "web_api_ok": (
                "web",
                health.web_api_ok,
                "web API health check failed",
                "web API health check recovered",
                f"http://127.0.0.1:{self.config.web_port}/api/v1/health/",
            ),
            "frontend_running": (
                "frontend",
                health.frontend_running,
                "frontend compose service is not running",
                "frontend compose service recovered",
                "frontend",
            ),
            "frontend_http_ok": (
                "frontend",
                health.frontend_http_ok,
                "frontend HTTP health check failed",
                "frontend HTTP health check recovered",
                f"http://127.0.0.1:{self.config.frontend_port}/",
            ),
        }
        current = {check: ok for check, (_, ok, _, _, _) in checks.items()}
        previous = self._last_serving_health

        for check, (service, ok, down_message, recovered_message, target) in checks.items():
            was_ok = previous.get(check) if previous is not None else True
            if was_ok and not ok:
                log_event(
                    logging.WARNING,
                    "serving_health_down",
                    down_message,
                    service=service,
                    check=check,
                    target=target,
                )
            elif not was_ok and ok:
                log_event(
                    logging.INFO,
                    "serving_health_recovered",
                    recovered_message,
                    service=service,
                    check=check,
                    target=target,
                )

        self._last_serving_health = current

    def http_ok(self, url: str, expected_statuses: range | set[int]) -> bool:
        """Return True if an HTTP GET returns an expected status."""
        try:
            with request.urlopen(url, timeout=self.config.health_timeout) as response:
                return response.status in expected_statuses
        except (OSError, TimeoutError, error.URLError):
            return False

    def fetch_peer_health(self, ip: str) -> dict[str, object] | None:
        """Fetch /health JSON from a peer monitor."""
        url = f"http://{ip}:{self.config.monitor_port}/health"
        try:
            with request.urlopen(url, timeout=self.config.health_timeout) as response:
                if response.status != 200:
                    return None
                data = json.loads(response.read().decode("utf-8"))
                if not isinstance(data, dict):
                    return None
                return data
        except (error.URLError, TimeoutError, json.JSONDecodeError):
            return None

    def compose_service_running(self, service: str) -> bool:
        """Return True if the docker compose service is running."""
        result = self.run_compose(
            ["ps", "--services", "--status", "running"], timeout=10
        )
        if result is None:
            return False
        if result.returncode != 0:
            log_event(
                logging.WARNING,
                "compose_ps_failed",
                "docker compose ps failed",
                service=service,
                error=result.stderr.strip(),
            )
            return False
        running = result.stdout.split()
        return service in running

    def worker_db_sync_ready(self) -> bool:
        """Check db_sync prerequisites inside the worker container."""
        # This command check if DB sync script exist and every tool the script required is prepared
        cmd = [
            "exec",
            "-T",
            "worker",
            "sh",
            "-lc",
            "test -f scripts/db_sync.sh && command -v pg_dump >/dev/null && command -v pg_restore >/dev/null && command -v psql >/dev/null",
        ]
        result = self.run_compose(cmd, timeout=30)
        if result is None:
            return False
        if result.returncode != 0:
            log_event(
                logging.WARNING,
                "worker_db_sync_readiness_failed",
                "worker db sync readiness check failed",
                service="worker",
                error=result.stderr.strip(),
            )
            return False
        return True

    def local_postgres_writable(self) -> bool:
        """Return True if the local Postgres instance is writable."""
        cmd = [
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            self.config.db_user,
            "-d",
            self.config.db_name,
            "-Atc",
            "SELECT pg_is_in_recovery();",
        ]
        result = self.run_compose(cmd, timeout=30)
        if result is None:
            return False
        if result.returncode != 0:
            log_event(
                logging.WARNING,
                "postgres_writability_check_failed",
                "local postgres writability check failed",
                service="postgres",
                error=result.stderr.strip(),
            )
            return False
        status = result.stdout.strip().lower()
        if status in {"f", "false"}:
            return True
        log_event(
            logging.WARNING,
            "postgres_read_only",
            "local postgres is read-only",
            service="postgres",
            pg_is_in_recovery=status,
        )
        return False

    def apply_role(self, active_ip: str) -> None:
        """Write role env and restart web/worker containers."""
        role_env = self.build_role_env(active_ip)
        changed = self.write_env_role(role_env)
        if changed:
            log_event(
                logging.INFO,
                "role_env_written",
                "wrote role env file",
                path=self.config.env_role,
                active_ip=active_ip,
            )
        else:
            log_event(
                logging.INFO,
                "role_env_unchanged",
                "role env unchanged",
                path=self.config.env_role,
                active_ip=active_ip,
            )

        result = self.run_compose(
            ["up", "-d", "--force-recreate", "web", "worker"],
            timeout=120,
        )
        if result is None:
            return
        if result.returncode != 0:
            log_event(
                logging.WARNING,
                "compose_up_failed",
                "docker compose up failed",
                services=["web", "worker"],
                error=result.stderr.strip(),
            )

    def build_role_env(self, active_ip: str) -> list[str]:
        """Build the .env.role content for the selected ACTIVE host."""
        flush_enabled = "1" if active_ip == self.config.this_ip else "0"
        lines = [
            "# Role-specific overrides written by the monitor",
            f"DB_HOST={active_ip}",
            f"REDIS_QUEUE_URL=redis://{active_ip}:6379/0",
            f"REDIS_CACHE_URL=redis://{active_ip}:6379/1",
            f"FLUSH_ENABLED={flush_enabled}",
        ]
        if self.config.last_sync_file:
            lines.append(f"LAST_SYNC_FILE={self.config.last_sync_file}")
        return lines

    def write_env_role(self, lines: list[str]) -> bool:
        """Write .env.role atomically and return True if changed."""
        new_content = "\n".join(lines) + "\n"
        existing = ""
        try:
            with open(self.config.env_role, "r", encoding="utf-8") as handle:
                existing = handle.read()
        except FileNotFoundError:
            existing = ""
        except OSError as exc:
            log_event(
                logging.WARNING,
                "role_env_read_failed",
                "failed to read env role file",
                path=self.config.env_role,
                error=str(exc),
            )

        if existing == new_content:
            return False

        directory = os.path.dirname(self.config.env_role) or "."
        os.makedirs(directory, exist_ok=True)

        # The implementation below makes file content replacement become atomic
        # This avoid .env.role broken while writing into it
        with tempfile.NamedTemporaryFile(
            "w", delete=False, dir=directory, encoding="utf-8"
        ) as handle:
            handle.write(new_content)
            temp_name = handle.name
        os.replace(temp_name, self.config.env_role)
        return True

    def maybe_run_db_sync(self, current_active: str | None) -> None:
        """Trigger db_sync.sh if this host is ACTIVE and due."""
        if current_active != self.config.this_ip:
            return

        # Abort DB sync scheduling if LAST_SYNC_FILE is misconfigured
        if not self.config.last_sync_file:
            now = time.time()
            if now - self._last_sync_file_warning > 60:
                log_event(
                    logging.WARNING,
                    "last_sync_file_not_set",
                    "LAST_SYNC_FILE not set; skip DB sync scheduling",
                )
                self._last_sync_file_warning = now
            return

        last_sync = self.read_last_sync_timestamp()
        now = time.time()
        if last_sync and (now - last_sync) < self.config.sync_interval:
            return

        log_event(
            logging.INFO,
            "db_sync_triggered",
            "triggering db_sync.sh",
            service="worker",
        )
        result = self.run_compose(
            ["exec", "-T", "worker", "scripts/db_sync.sh"], timeout=600
        )
        if result is None:
            return
        if result.returncode != 0:
            log_event(
                logging.WARNING,
                "db_sync_failed",
                "db_sync.sh failed",
                service="worker",
                error=result.stderr.strip(),
            )

    def read_last_sync_timestamp(self) -> int | None:
        """Read the last sync timestamp from LAST_SYNC_FILE."""
        if not self.config.last_sync_file:
            return None
        try:
            with open(self.config.last_sync_file, "r", encoding="utf-8") as handle:
                raw = handle.read().strip()
        except FileNotFoundError:
            return None
        except OSError as exc:
            log_event(
                logging.WARNING,
                "last_sync_file_read_failed",
                "failed to read LAST_SYNC_FILE",
                path=self.config.last_sync_file,
                error=str(exc),
            )
            return None
        if not raw.isdigit():
            log_event(
                logging.WARNING,
                "last_sync_file_invalid",
                "LAST_SYNC_FILE contains invalid timestamp",
                path=self.config.last_sync_file,
                value=raw,
            )
            return None
        return int(raw)

    def run_compose(
        self, args: list[str], timeout: int
    ) -> subprocess.CompletedProcess[str] | None:
        """Run a docker compose command with a process lock."""
        cmd = ["docker", "compose", "-f", self.config.compose_file] + args
        try:
            with self._compose_lock:
                return subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            log_event(
                logging.WARNING,
                "compose_command_failed",
                "docker compose command failed",
                args=args,
                error=str(exc),
            )
            return None


def main() -> None:
    """Monitor entrypoint that wires logging, config, and signals."""
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
    config = load_config()

    monitor = Monitor(config)

    def handle_signal(signum: int, _frame: object) -> None:
        """Handle SIGTERM/SIGINT by stopping the monitor."""
        log_event(
            logging.INFO,
            "shutdown_signal_received",
            "received signal; stopping monitor",
            signal=signum,
        )
        monitor.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    monitor.run()


if __name__ == "__main__":
    main()
