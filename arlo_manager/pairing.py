from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .system import SystemReader


@dataclass
class PairingSession:
    identifier: str
    started_at: float
    baseline_serials: set[str]
    baseline_stations: set[str]


class PairingCoordinator:
    def __init__(self, system: SystemReader):
        self.system = system
        self._sessions: dict[str, PairingSession] = {}
        self._lock = threading.Lock()

    def start(self) -> PairingSession:
        devices = self.system.arlo_devices()
        session = PairingSession(
            identifier=uuid.uuid4().hex,
            started_at=time.time(),
            baseline_serials={
                str(device.get("serial_number", "")) for device in devices
            },
            baseline_stations=set(self.system.stations()),
        )
        result = self.system.start_pairing()
        if not result.ok or "FAIL" in result.output.upper():
            raise RuntimeError(f"Could not start WPS pairing: {result.output}")
        with self._lock:
            self._sessions[session.identifier] = session
        return session

    def status(self, identifier: str) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(identifier)
        if not session:
            raise KeyError("Pairing session not found")
        if time.time() - session.started_at > 180:
            return {
                "expired": True,
                "message": "Pairing timed out. Start pairing again.",
            }

        stations = self.system.stations()
        new_station_macs = set(stations) - session.baseline_stations
        leases = self.system.leases()
        devices = self.system.arlo_devices()
        new_lease_ips = {
            lease["ip"] for lease in leases.values() if lease["mac"] in new_station_macs
        }
        candidate_devices = [
            device
            for device in devices
            if str(device.get("serial_number", "")) not in session.baseline_serials
            or str(device.get("ip", "")) in new_lease_ips
        ]
        response: dict[str, Any] = {
            "expired": False,
            "wifi_detected": bool(new_station_macs),
            "station_mac": next(iter(new_station_macs), None),
            "dhcp_detected": False,
            "registered": False,
        }
        for lease in leases.values():
            if lease["mac"] in new_station_macs:
                response.update({"dhcp_detected": True, "lease": lease})
                break
        if candidate_devices:
            device = candidate_devices[0]
            ip = str(device.get("ip", ""))
            lease = leases.get(ip, {})
            response.update(
                {
                    "registered": True,
                    "camera": {
                        "serial": str(device.get("serial_number", "")),
                        "hostname": str(device.get("hostname", "")),
                        "ip": ip,
                        "mac": str(
                            lease.get("mac") or response.get("station_mac") or ""
                        ),
                    },
                }
            )
        return response
