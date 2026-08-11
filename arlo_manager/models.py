from __future__ import annotations

import ipaddress
import re
from dataclasses import asdict, dataclass
from typing import Any

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
MAC_PATTERN = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")
SERIAL_PATTERN = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


@dataclass(frozen=True)
class Camera:
    name: str
    slug: str
    mac: str
    ip: str
    hostname: str
    serial: str

    @classmethod
    def from_dict(cls, serial: str, value: dict[str, Any]) -> Camera:
        camera = cls(
            name=str(value.get("name", "")).strip(),
            slug=str(value.get("slug", "")).strip().lower(),
            mac=str(value.get("mac", "")).strip().lower(),
            ip=str(value.get("ip", "")).strip(),
            hostname=str(value.get("hostname", "")).strip(),
            serial=serial.strip(),
        )
        camera.validate()
        return camera

    def validate(self) -> None:
        if not self.name or len(self.name) > 80:
            raise ValueError("Friendly name must contain 1 to 80 characters")
        if not SLUG_PATTERN.fullmatch(self.slug):
            raise ValueError(
                "Stream ID must use lowercase letters, numbers, and underscores"
            )
        if not MAC_PATTERN.fullmatch(self.mac):
            raise ValueError("Invalid camera MAC address")
        if not SERIAL_PATTERN.fullmatch(self.serial):
            raise ValueError("Invalid camera serial number")
        address = ipaddress.ip_address(self.ip)
        network = ipaddress.ip_network("172.14.1.0/24")
        if address not in network or address in {
            network.network_address,
            network.broadcast_address,
            ipaddress.ip_address("172.14.1.1"),
        }:
            raise ValueError(
                "Camera address must be an available address in 172.14.1.0/24"
            )
        if not self.hostname or len(self.hostname) > 128:
            raise ValueError("Invalid camera hostname")

    def to_dict(self) -> dict[str, str]:
        value = asdict(self)
        value.pop("serial")
        return value


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "camera"
