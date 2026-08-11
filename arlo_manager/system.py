from __future__ import annotations

import json
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import httpx
import yaml

from .settings import Settings


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    output: str
    timed_out: bool = False


class SystemReader:
    def __init__(self, config: Settings):
        self.config = config

    def run(self, args: list[str], timeout: int = 8) -> CommandResult:
        try:
            result = subprocess.run(
                args, text=True, capture_output=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired as error:
            return CommandResult(False, str(error), timed_out=True)
        except OSError as error:
            return CommandResult(False, str(error))
        output = (result.stdout or result.stderr).strip()
        return CommandResult(result.returncode == 0, output)

    def service_active(self, name: str) -> bool:
        return self.run(["systemctl", "is-active", "--quiet", name]).ok

    def lan_address(self) -> str | None:
        result = self.run(
            ["ip", "-4", "-j", "addr", "show", "dev", self.config.lan_interface]
        )
        if not result.ok:
            return None
        try:
            for interface in json.loads(result.output):
                for address in interface.get("addr_info", []):
                    if address.get("scope") == "global":
                        return str(address["local"])
        except (ValueError, KeyError, TypeError):
            return None
        return None

    def advertised_host(self) -> str:
        return (
            self.config.advertised_host or f"{socket.gethostname().split('.')[0]}.local"
        )

    def wlan_info(self) -> dict[str, Any]:
        info = self.run(["iw", "dev", self.config.wifi_interface, "info"])
        status = self.run([*self.hostapd_cli(), "status"])
        address = self.run(
            ["ip", "-4", "-o", "addr", "show", "dev", self.config.wifi_interface]
        )
        values: dict[str, Any] = {
            "ap": False,
            "ssid": "Unavailable",
            "channel": "—",
            "address_ok": False,
        }
        for line in info.output.splitlines():
            words = line.strip().split()
            if len(words) >= 2 and words[0] == "ssid":
                values["ssid"] = " ".join(words[1:])
            elif len(words) >= 2 and words[0] == "type":
                values["ap"] = words[1] == "AP"
            elif len(words) >= 2 and words[0] == "channel":
                values["channel"] = words[1]
        values["enabled"] = "state=ENABLED" in status.output
        values["address_ok"] = f"{self.config.gateway}/24" in address.output
        return values

    def stations(self) -> dict[str, dict[str, Any]]:
        result = self.run(["iw", "dev", self.config.wifi_interface, "station", "dump"])
        stations: dict[str, dict[str, Any]] = {}
        current: dict[str, Any] | None = None
        for line in result.output.splitlines():
            stripped = line.strip()
            if stripped.startswith("Station "):
                mac = stripped.split()[1].lower()
                current = {"mac": mac}
                stations[mac] = current
            elif current and stripped.startswith("signal:"):
                current["signal"] = stripped.split()[1]
            elif current and stripped.startswith("connected time:"):
                current["connected_seconds"] = stripped.split()[2]
        return stations

    def leases(self) -> dict[str, dict[str, str]]:
        leases: dict[str, dict[str, str]] = {}
        try:
            lines = self.config.leases_path.read_text().splitlines()
        except OSError:
            return leases
        for line in lines:
            fields = line.split()
            if len(fields) >= 4:
                _, mac, ip, hostname = fields[:4]
                leases[ip] = {"mac": mac.lower(), "ip": ip, "hostname": hostname}
        return leases

    def arlo_devices(self) -> list[dict[str, Any]]:
        try:
            response = httpx.get(f"{self.config.arlo_api_url}/device", timeout=3)
            response.raise_for_status()
            value = response.json()
            return value if isinstance(value, list) else []
        except (httpx.HTTPError, ValueError):
            return []

    def arlo_status(self, serial: str) -> dict[str, Any]:
        try:
            response = httpx.get(
                f"{self.config.arlo_api_url}/device/{serial}", timeout=3
            )
            response.raise_for_status()
            value = response.json()
            return value if isinstance(value, dict) else {}
        except (httpx.HTTPError, ValueError):
            return {}

    def set_arlo_friendly_name(self, serial: str, name: str) -> bool:
        try:
            response = httpx.post(
                f"{self.config.arlo_api_url}/device/{serial}/friendlyname",
                json={"name": name},
                timeout=3,
            )
            response.raise_for_status()
            return bool(response.json().get("result"))
        except (httpx.HTTPError, ValueError, AttributeError):
            return False

    def mediamtx_paths(self) -> dict[str, Any]:
        try:
            value = yaml.safe_load(self.config.mediamtx_path.read_text()) or {}
            return (
                value.get("paths", {})
                if isinstance(value.get("paths", {}), dict)
                else {}
            )
        except (OSError, yaml.YAMLError):
            return {}

    def health(self) -> dict[str, Any]:
        service_names = (
            "arlo-wlan",
            "hostapd",
            "dnsmasq",
            "arlo-cam-api",
            "mediamtx",
        )
        with ThreadPoolExecutor(max_workers=7) as executor:
            service_futures = {
                name: executor.submit(self.service_active, name)
                for name in service_names
            }
            wlan_future = executor.submit(self.wlan_info)
            lan_future = executor.submit(self.lan_address)
            services = {
                name: future.result() for name, future in service_futures.items()
            }
            wlan = wlan_future.result()
            lan_address = lan_future.result()
        return {
            "services": services,
            "wlan": wlan,
            "lan_address": lan_address,
        }

    def hostapd_cli(self) -> list[str]:
        # The manager runs with systemd's PrivateTmp enabled. Give hostapd_cli a
        # shared client-socket directory so hostapd can send its reply back into
        # the manager's mount namespace instead of waiting for the timeout.
        return [
            "hostapd_cli",
            "-p/run/hostapd",
            "-s/run/hostapd",
            "-i",
            self.config.wifi_interface,
        ]

    def start_pairing(self) -> CommandResult:
        base = self.hostapd_cli()
        self.run([*base, "wps_cancel"], timeout=5)
        result = self.run([*base, "wps_pbc"], timeout=8)
        if result.timed_out:
            wps_status = self.run([*base, "wps_get_status"], timeout=5)
            if wps_status.ok and (
                "PBC Status: Active" in wps_status.output
                or "Last WPS result: Success" in wps_status.output
            ):
                return CommandResult(True, wps_status.output)
        return result

    def test_stream(self, slug: str) -> CommandResult:
        return self.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-rtsp_transport",
                "udp",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "json",
                f"rtsp://127.0.0.1:8554/{slug}",
            ],
            timeout=25,
        )
