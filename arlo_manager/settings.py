from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _secret(value_name: str, file_name: str) -> str:
    path = os.getenv(file_name, "")
    if path:
        try:
            return Path(path).read_text().rstrip("\r\n")
        except OSError:
            return ""
    return os.getenv(value_name, "")


@dataclass(frozen=True)
class Settings:
    state_path: Path = Path(
        os.getenv("ARLO_STATE_PATH", "/opt/arlo-manager/config.json")
    )
    dnsmasq_path: Path = Path(
        os.getenv("ARLO_DNSMASQ_PATH", "/etc/dnsmasq.d/arlo.conf")
    )
    mediamtx_path: Path = Path(
        os.getenv("ARLO_MEDIAMTX_PATH", "/opt/mediamtx/mediamtx.yml")
    )
    leases_path: Path = Path(
        os.getenv("ARLO_LEASES_PATH", "/var/lib/misc/dnsmasq.leases")
    )
    backup_dir: Path = Path(os.getenv("ARLO_BACKUP_DIR", "/var/backups/arlo-manager"))
    wifi_interface: str = os.getenv("ARLO_WIFI_INTERFACE", "wlan0")
    lan_interface: str = os.getenv("ARLO_LAN_INTERFACE", "eth0")
    gateway: str = os.getenv("ARLO_GATEWAY", "172.14.1.1")
    advertised_host: str = os.getenv("ARLO_ADVERTISED_HOST", "")
    arlo_api_url: str = os.getenv("ARLO_API_URL", "http://127.0.0.1:5000")
    mediamtx_api_url: str = os.getenv("ARLO_MEDIAMTX_API_URL", "http://127.0.0.1:9997")
    username: str = os.getenv("ARLO_MANAGER_USERNAME", "admin")
    password: str = _secret("ARLO_MANAGER_PASSWORD", "ARLO_MANAGER_PASSWORD_FILE")
    mqtt_host: str = os.getenv("ARLO_MQTT_HOST", "")
    mqtt_port: int = int(os.getenv("ARLO_MQTT_PORT", "1883"))
    mqtt_username: str = os.getenv("ARLO_MQTT_USERNAME", "")
    mqtt_password: str = _secret("ARLO_MQTT_PASSWORD", "ARLO_MQTT_PASSWORD_FILE")
    motion_off_delay: int = int(os.getenv("ARLO_MOTION_OFF_DELAY", "30"))


settings = Settings()
