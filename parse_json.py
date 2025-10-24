import json
import requests
import threading
import time
from typing import Any, Dict, Union
import dotenv

import argparse

try:
    import RPi.GPIO as GPIO
except ImportError:
    import dummy.GPIO as GPIO



class StatusMonitor:
    def __init__(self, base_url: str, slug: str):
        self.base_url = base_url.rstrip("/")
        self.slug = slug
        self.name_to_id: Dict[str, int] = {}
        self.heartbeat_data: Dict[str, Any] = {}
        self._stop_event = threading.Event()
        self._thread: Union[threading.Thread, None] = None

    def fetch_status_page(self) -> None:
        """Fetch and parse monitor name→id mapping."""
        response = requests.get(f"{self.base_url}/api/status-page/{self.slug}")
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


# Example usage:
if __name__ == "__main__":
    dotenv.load_dotenv()
    base_url = dotenv.get_key(".env", "base_url")
    slug = dotenv.get_key(".env", "slug")
    monitor = StatusMonitor(base_url, slug)
    monitor.fetch_status_page()
    #monitor._run_periodic(interval=10)  # Initial run
    monitor.start_periodic_check(interval=10)  # Check every 10s
    while True:
        time.sleep(1)

    # Press Ctrl+C to exit or call monitor.stop_periodic_check()

# run on program exit
GPIO.cleanup()