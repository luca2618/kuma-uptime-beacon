import json
import requests
import threading
import time
from typing import Any, Dict, Union
import dotenv

import sys

try:
    import RPi.GPIO as GPIO
except ImportError:
    import dummy.GPIO as GPIO



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
            if service.get("enabled", False):
                service_id = service.get("id") or self.name_to_id.get(service["name"])
                pin = service["pin"]
                if self.is_up(service_id):
                    GPIO.output(pin, GPIO.HIGH)
                else:
                    GPIO.output(pin, GPIO.LOW)
                


# Example usage:
if __name__ == "__main__":
    dotenv.load_dotenv()
    if sys.argv[1] == "start":
        config_path = sys.argv[2]
        with open(config_path, "r") as f:
            config = json.load(f)
        monitor = StatusMonitor(config["url"], config["slug"], config["services"], config.get("pin_mode", "BCM"))
        #monitor._run_periodic(interval=10)  # Initial run
        monitor.start_periodic_check(interval=config.get("interval", 10))  # Check every 10s
        while True:
            time.sleep(1)
    if sys.argv[1] == "service":
        pass 

    # Press Ctrl+C to exit or call monitor.stop_periodic_check()

    # run on program exit
    GPIO.cleanup()