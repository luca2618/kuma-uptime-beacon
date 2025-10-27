# kuma-uptime-beacon
kuma-uptime-beacon turns your Raspberry Pi into a physical status light. It connects to Uptime Kuma's API and changes LED colors or turns the lamp on/off based on real-time service status so you can integrate your alert system into a physical gadget.

- Polls Uptime Kuma for the latest heartbeat and keeps simple on/off state per configured service.
- Drives one or more GPIO pins per service, with optional reversed logic for normally-closed circuits or active-low LEDs.
- Can run as a foreground script or install itself as a `systemd` service on a Linux host.
- Ships with a dummy GPIO shim so you can test on non-Pi hardware without toggling real pins.

## Requirements

- Python 3.9+
- `requests` (see `requirements.txt`)
- A Raspberry Pi (or other SBC) with accessible GPIO pins for production use
- An Uptime Kuma instance with a public status page you can query

Install dependencies with:

```cmd
pip install -r requirements.txt
```

## Configuration

Runtime configuration lives in a JSON file. See `example.json` for a full sample. Important fields:

- `url`: Base URL of your Uptime Kuma instance.
- `slug`: Status page slug to query (path segment after `/status/`).
- `pin_mode`: Either `BCM` (Broadcom numbering, default) or `BOARD` for physical pin numbers.
- `interval`: Polling interval in seconds.
- `services`: List of monitored services:
	- `name`: Display name matching a monitor or group on the status page.
	- `id`: Alternative to `name` if you prefer to reference monitors by numeric ID.
	- `pin`: Single pin number or list of pins to toggle together.
	- `reverse`: Optional boolean to invert the signal (defaults to `false`).

The monitor will normalize every `pin` value to a list and set each pin as `GPIO.OUT` on start-up. When a service is reported up, the pin(s) are driven `HIGH` (or `LOW` if `reverse` is true).

## Running the Beacon

To run interactively, point the script at a config file:

```cmd
python beacon.py start example.json
```

The program spawns a background polling thread that prints status updates and keeps GPIO pins in sync. Press `Ctrl+C` to exit; cleanup handlers will release GPIO resources.

While developing on non-Pi hardware, the fallback `dummy.GPIO` module provides console output instead of real pin toggling.

## Installing as a systemd Service

On a systemd-based Linux machine you can install the beacon as a persistent service. This requires root privileges because it writes to `/etc/systemd/system/`.

```cmd
python beacon.py service install /path/to/config.json
```

The script will generate a unit file named `kuma-uptime-beacon.service`, enable it, and start it immediately. Use the helper commands to inspect or remove the service:

```cmd
python beacon.py service status
python beacon.py service uninstall
```

During status checks the script runs `systemctl status kuma-uptime-beacon` so the usual journal output is available.

