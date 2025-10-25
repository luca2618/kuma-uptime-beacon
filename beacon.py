import json
import logging
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from getpass import getuser
from pathlib import Path
from typing import Any, Dict, Union

import requests

try:
    import RPi.GPIO as GPIO
except ImportError:
    import dummy.GPIO as GPIO


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
stop = False

SERVICE_NAME = "kuma-uptime-beacon"
SERVICE_FILE_TARGET = Path("/etc/systemd/system") / f"{SERVICE_NAME}.service"

def handle_sigterm(*_):
    global stop
    logging.info("Received SIGTERM, shutting down...")
    stop = True

signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)

def run():
    logging.info("Service started")
    while not stop:
        # do work here
        time.sleep(1)
    logging.info("Service stopped")


def _ensure_systemd_env() -> None:
    if os.name != "posix":
        raise RuntimeError("Service management is only supported on systemd-based Linux systems")
    if not SERVICE_FILE_TARGET.parent.exists():
        raise RuntimeError("Systemd directory not found; ensure this is running on a systemd host")


def _build_service_unit(config_path: str) -> str:
    python_exec = Path(sys.executable).resolve()
    script_path = Path(__file__).resolve()
    working_dir = script_path.parent
    quoted_python = shlex.quote(str(python_exec))
    quoted_script = shlex.quote(str(script_path))
    quoted_config = shlex.quote(str(Path(config_path).resolve()))

    return "\n".join(
        [
            "[Unit]",
            "Description=Uptime Kuma hardware beacon",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"User={getuser()}",
            "Environment=PYTHONUNBUFFERED=1",
            f"Environment=KUMA_BEACON_CONFIG={quoted_config}",
            f"WorkingDirectory={working_dir}",
            f"ExecStart={quoted_python} {quoted_script} start {quoted_config}",
            "Restart=on-failure",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
        ]
    )


def install_service(config_path: str) -> None:
    _ensure_systemd_env()
    path_obj = Path(config_path).expanduser().resolve()
    if not path_obj.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    unit_contents = _build_service_unit(str(path_obj))
    SERVICE_FILE_TARGET.write_text(unit_contents, encoding="utf-8")
    logging.info("Service unit written to %s", SERVICE_FILE_TARGET)

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", SERVICE_NAME], check=True)
    subprocess.run(["systemctl", "start", SERVICE_NAME], check=True)
    logging.info("Service %s installed and started", SERVICE_NAME)


def uninstall_service() -> None:
    _ensure_systemd_env()

    subprocess.run(["systemctl", "disable", SERVICE_NAME], check=False)
    subprocess.run(["systemctl", "stop", SERVICE_NAME], check=False)

    if SERVICE_FILE_TARGET.exists():
        SERVICE_FILE_TARGET.unlink()
        logging.info("Removed service unit %s", SERVICE_FILE_TARGET)

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    logging.info("Service %s uninstalled", SERVICE_NAME)


def check_service_status() -> None:
    try:
        _ensure_systemd_env()
    except RuntimeError as exc:
        logging.error(str(exc))
        return

    try:
        subprocess.run([
            "systemctl",
            "status",
            SERVICE_NAME,
        ], check=False)
    except FileNotFoundError:
        logging.error("systemctl not found; cannot query service status")





class StatusMonitor:
    def __init__(self, base_url: str, slug: str, services : list = [], pin_mode: str = "BCM"):
        self.base_url = base_url.rstrip("/")
        self.slug = slug
        self.name_to_id: Dict[str, int] = {}
        self.heartbeat_data: Dict[str, Any] = {}
        self._stop_event = threading.Event()
        self._thread: Union[threading.Thread, None] = None
        self.services = services

        self.fetch_status_page()

        if pin_mode.upper() == "BCM":
            GPIO.setmode(GPIO.BCM)
        else:
            GPIO.setmode(GPIO.BOARD)
        

        for service in self.services:
            GPIO.setup(service["pin"], GPIO.OUT)

    def fetch_status_page(self) -> None:
        """Fetch and parse monitor name→id mapping."""
        response = requests.get(f"{self.base_url}/api/status-page/{self.slug}")
        print(f"{self.base_url}/api/status-page/{self.slug}")
        response.raise_for_status()
        data = response.json()

        mapping = {}
        for group in data.get("publicGroupList", []):
            mapping[group["name"]] = group["id"]
            for monitor in group.get("monitorList", []):
                mapping[monitor["name"]] = monitor["id"]
        self.name_to_id = mapping

    def fetch_heartbeat(self) -> None:
        """Fetch latest heartbeat data."""
        response = requests.get(f"{self.base_url}/api/status-page/heartbeat/{self.slug}")
        response.raise_for_status()
        self.heartbeat_data = response.json()

    def is_up(self, monitor_id: Union[int, str]) -> bool:
        """Return True if latest heartbeat status is 1."""
        entries = self.heartbeat_data.get("heartbeatList", {}).get(str(monitor_id), [])
        return bool(entries) and entries[-1].get("status") == 1

    def check_all(self) -> Dict[str, bool]:
        """Return dict of monitor name → up/down (True/False)."""
        self.fetch_heartbeat()
        return {name: self.is_up(id_) for name, id_ in self.name_to_id.items()}

    def start_periodic_check(self, interval: int = 30) -> None:
        """Start background periodic check every `interval` seconds."""
        if self._thread and self._thread.is_alive():
            return  # Already running

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_periodic, args=(interval,), daemon=True)
        self._thread.start()

    def _run_periodic(self, interval: int):
        """Background thread loop for periodic checks."""
        while not self._stop_event.is_set():
            try:
                status_dict = self.check_all()
                print(f"\n[STATUS UPDATE] ({time.strftime('%H:%M:%S')})")
                for name, status in status_dict.items():
                    print(f"{name}: {'UP' if status else 'DOWN'}")
            except Exception as e:
                print(f"Error during check: {e}")
            time.sleep(interval)

    def stop_periodic_check(self) -> None:
        """Stop background periodic checks."""
        self._stop_event.set()
        if self._thread:
            self._thread.join()
            self._thread = None

    def update_gpio(self) -> None:
        """Setup GPIO pins for services."""
        for service in self.services:
            if service.get("enabled", True):
                service_id = service.get("id") or self.name_to_id.get(service["name"])
                pin = service["pin"]
                if self.is_up(service_id):
                    GPIO.output(pin, GPIO.HIGH)
                else:
                    GPIO.output(pin, GPIO.LOW)
                


# Example usage:
if __name__ == "__main__":
    if len(sys.argv) < 2:
        logging.error("Missing command. Use 'start <config>' or 'service <action>'")
        sys.exit(1)

    if sys.argv[1] == "start":
        if len(sys.argv) < 3:
            logging.error("Missing config path for start command")
            sys.exit(1)
        config_path = sys.argv[2]
        with open(config_path, "r") as f:
            config = json.load(f)
        print(config)
        monitor = StatusMonitor(config["url"], config["slug"], config["services"], config.get("pin_mode", "BCM"))
        #monitor._run_periodic(interval=10)  # Initial run
        monitor.start_periodic_check(interval=config.get("interval", 10))  # Check every 10s
        run()
    elif sys.argv[1] == "service":
        if len(sys.argv) < 3:
            logging.error("Missing service action. Use install, status, or uninstall.")
            sys.exit(1)

        action = sys.argv[2]

        if action == "install":
            if len(sys.argv) < 4:
                logging.error("Missing config path for service installation")
                sys.exit(1)
            try:
                install_service(sys.argv[3])
            except Exception as exc:
                logging.error("Failed to install service: %s", exc)
                sys.exit(1)

        elif action == "status":
            check_service_status()

        elif action == "uninstall":
            try:
                uninstall_service()
            except Exception as exc:
                logging.error("Failed to uninstall service: %s", exc)
                sys.exit(1)
        else:
            logging.error("Unknown service action '%s'", action)
            sys.exit(1)

    # Press Ctrl+C to exit or call monitor.stop_periodic_check()

    # run on program exit
    GPIO.cleanup()