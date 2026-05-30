import json
import logging
import subprocess
import unittest
from unittest.mock import Mock, patch

import monitor


def make_config() -> monitor.Config:
    return monitor.Config(
        this_ip="10.0.0.1",
        peers=["10.0.0.1", "10.0.0.2"],
        monitor_port=9123,
        check_interval=15,
        fail_threshold=3,
        recover_threshold=2,
        degraded_threshold=8,
        sync_interval=600,
        compose_file="docker-compose.yml",
        env_base=".env",
        env_role=".env.role",
        db_name="Subscriptions",
        db_user="MailAdmin",
        last_sync_file=None,
        pg_port=5432,
        redis_port=6379,
        web_port=8000,
        frontend_port=55111,
        tcp_timeout=2.0,
        health_timeout=2.0,
    )


class PeerStatusTest(unittest.TestCase):
    def test_core_healthy_ignores_serving_health(self):
        status = monitor.PeerStatus(
            ip="10.0.0.1",
            pg_ok=True,
            redis_ok=True,
            monitor_reachable=True,
            worker_running=True,
            db_sync_ready=True,
            web_running=False,
            web_api_ok=False,
            frontend_running=False,
            frontend_http_ok=False,
        )

        self.assertTrue(status.core_healthy)


class MonitorServingHealthTest(unittest.TestCase):
    def test_local_health_contains_serving_fields(self):
        mon = monitor.Monitor(make_config())
        mon.compose_service_running = Mock(
            side_effect=lambda service: service in {"worker", "web", "frontend"}
        )
        mon.worker_db_sync_ready = Mock(return_value=True)
        mon.http_ok = Mock(return_value=True)

        health = mon.local_health()

        self.assertEqual(
            health.to_payload(),
            {
                "worker_running": True,
                "db_sync_ready": True,
                "web_running": True,
                "web_api_ok": True,
                "frontend_running": True,
                "frontend_http_ok": True,
            },
        )

    def test_determine_active_ignores_failed_serving_checks(self):
        mon = monitor.Monitor(make_config())
        statuses = {
            "10.0.0.1": monitor.PeerStatus(
                ip="10.0.0.1",
                pg_ok=True,
                redis_ok=True,
                monitor_reachable=True,
                worker_running=True,
                db_sync_ready=True,
                web_running=False,
                web_api_ok=False,
                frontend_running=False,
                frontend_http_ok=False,
            )
        }

        self.assertEqual(mon.determine_active(statuses), "10.0.0.1")

    def test_serving_health_logs_down_and_recovered_transitions(self):
        mon = monitor.Monitor(make_config())
        logger = logging.getLogger("mailsub-monitor")

        with self.assertLogs(logger, level="INFO") as captured:
            mon.log_serving_health_transitions(
                monitor.LocalHealth(
                    worker_running=True,
                    db_sync_ready=True,
                    web_running=True,
                    web_api_ok=False,
                    frontend_running=True,
                    frontend_http_ok=True,
                )
            )
            mon.log_serving_health_transitions(
                monitor.LocalHealth(
                    worker_running=True,
                    db_sync_ready=True,
                    web_running=True,
                    web_api_ok=True,
                    frontend_running=True,
                    frontend_http_ok=True,
                )
            )

        events = [json.loads(line.split(":", 2)[-1].strip()) for line in captured.output]
        self.assertEqual(events[0]["event"], "serving_health_down")
        self.assertEqual(events[0]["service"], "web")
        self.assertEqual(events[0]["check"], "web_api_ok")
        self.assertEqual(events[1]["event"], "serving_health_recovered")
        self.assertEqual(events[1]["service"], "web")

    def test_http_ok_accepts_expected_status_range(self):
        response = Mock()
        response.status = 302
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        mon = monitor.Monitor(make_config())

        with patch("monitor.request.urlopen", return_value=response):
            self.assertTrue(mon.http_ok("http://127.0.0.1:55111/", range(200, 400)))

    def test_log_event_outputs_json(self):
        logger = logging.getLogger("mailsub-monitor")

        with self.assertLogs(logger, level="WARNING") as captured:
            monitor.log_event(
                logging.WARNING,
                "compose_command_failed",
                "docker compose command failed",
                service="web",
                error="timeout",
            )

        payload = json.loads(captured.output[0].split(":", 2)[-1].strip())
        self.assertEqual(payload["level"], "WARNING")
        self.assertEqual(payload["logger"], "mailsub-monitor")
        self.assertEqual(payload["event"], "compose_command_failed")
        self.assertEqual(payload["service"], "web")
        self.assertEqual(payload["error"], "timeout")


class ComposeServiceTest(unittest.TestCase):
    def test_compose_service_running_logs_structured_warning(self):
        mon = monitor.Monitor(make_config())
        mon.run_compose = Mock(
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="docker unavailable",
            )
        )
        logger = logging.getLogger("mailsub-monitor")

        with self.assertLogs(logger, level="WARNING") as captured:
            self.assertFalse(mon.compose_service_running("web"))

        payload = json.loads(captured.output[0].split(":", 2)[-1].strip())
        self.assertEqual(payload["event"], "compose_ps_failed")
        self.assertEqual(payload["error"], "docker unavailable")
