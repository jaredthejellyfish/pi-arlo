from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import tempfile
from pathlib import Path

import yaml

from .models import Camera
from .settings import Settings
from .store import StateStore
from .system import SystemReader

BEGIN = "# BEGIN ARLO MANAGER CAMERAS"
END = "# END ARLO MANAGER CAMERAS"


class ConfigurationError(RuntimeError):
    pass


class ConfigurationManager:
    def __init__(self, config: Settings, store: StateStore, system: SystemReader):
        self.config = config
        self.store = store
        self.system = system

    @staticmethod
    def _dnsmasq_text(
        original: str, cameras: dict[str, Camera], removed_macs: set[str] | None = None
    ) -> str:
        managed_macs = {camera.mac for camera in cameras.values()} | (
            removed_macs or set()
        )
        output: list[str] = []
        in_managed = False
        for line in original.splitlines():
            stripped = line.strip()
            if stripped == BEGIN:
                in_managed = True
                continue
            if stripped == END:
                in_managed = False
                continue
            if in_managed:
                continue
            match = re.match(r"\s*dhcp-host=([^,]+),", line)
            if match and match.group(1).strip().lower() in managed_macs:
                continue
            output.append(line)
        while output and not output[-1].strip():
            output.pop()
        output.extend(["", BEGIN])
        for camera in sorted(cameras.values(), key=lambda item: item.ip):
            output.extend([f"# {camera.name}", f"dhcp-host={camera.mac},{camera.ip}"])
        output.extend([END, ""])
        return "\n".join(output)

    @staticmethod
    def _mediamtx_text(
        original: str, cameras: dict[str, Camera], removed_slugs: set[str]
    ) -> str:
        try:
            data = yaml.safe_load(original) or {}
        except yaml.YAMLError as error:
            raise ConfigurationError(
                f"MediaMTX configuration is invalid: {error}"
            ) from error
        if not isinstance(data, dict):
            raise ConfigurationError("MediaMTX configuration must be a YAML mapping")
        paths = data.setdefault("paths", {})
        if not isinstance(paths, dict):
            raise ConfigurationError("MediaMTX paths must be a YAML mapping")
        for slug in removed_slugs:
            paths.pop(slug, None)
        for camera in cameras.values():
            paths[camera.slug] = {
                "source": f"rtsp://{camera.ip}/live",
                "sourceOnDemand": True,
                "sourceOnDemandStartTimeout": "15s",
                "sourceOnDemandCloseAfter": "5s",
                "rtspAnyPort": True,
            }
        return yaml.safe_dump(data, sort_keys=False)

    def _write_temp(self, target: Path, content: str) -> Path:
        fd, name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if target.exists():
            current = target.stat()
            os.chmod(name, current.st_mode & 0o777)
            os.chown(name, current.st_uid, current.st_gid)
        else:
            os.chmod(name, 0o644)
        return Path(name)

    def apply(
        self,
        cameras: dict[str, Camera],
        removed_slugs: set[str] | None = None,
        removed_macs: set[str] | None = None,
        test_slug: str | None = None,
    ) -> None:
        removed_slugs = removed_slugs or set()
        removed_macs = removed_macs or set()
        slugs = [camera.slug for camera in cameras.values()]
        if len(slugs) != len(set(slugs)):
            raise ConfigurationError("Stream IDs must be unique")

        dns_original = self.config.dnsmasq_path.read_text()
        media_original = self.config.mediamtx_path.read_text()
        dns_temp = self._write_temp(
            self.config.dnsmasq_path,
            self._dnsmasq_text(dns_original, cameras, removed_macs),
        )
        media_temp = self._write_temp(
            self.config.mediamtx_path,
            self._mediamtx_text(media_original, cameras, removed_slugs),
        )
        timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S-%f")
        backup = self.config.backup_dir / timestamp
        backup.mkdir(parents=True, exist_ok=False)
        shutil.copy2(self.config.dnsmasq_path, backup / "arlo.conf")
        shutil.copy2(self.config.mediamtx_path, backup / "mediamtx.yml")

        validation = self.system.run(["dnsmasq", "--test", f"--conf-file={dns_temp}"])
        if not validation.ok:
            dns_temp.unlink(missing_ok=True)
            media_temp.unlink(missing_ok=True)
            raise ConfigurationError(
                f"dnsmasq rejected the proposed configuration: {validation.output}"
            )
        try:
            yaml.safe_load(media_temp.read_text())
            os.replace(dns_temp, self.config.dnsmasq_path)
            os.replace(media_temp, self.config.mediamtx_path)
            for service in ("dnsmasq", "mediamtx"):
                restarted = self.system.run(
                    ["systemctl", "restart", service], timeout=30
                )
                if not restarted.ok:
                    raise ConfigurationError(
                        f"Could not restart {service}: {restarted.output}"
                    )
            if test_slug:
                stream = self.system.test_stream(test_slug)
                if not stream.ok:
                    raise ConfigurationError(
                        "The camera was configured, but its MediaMTX stream could not be opened. "
                        "Move it near the Pi, wake it, and try Finish Setup again."
                    )
            self.store.save(cameras)
        except BaseException:
            shutil.copy2(backup / "arlo.conf", self.config.dnsmasq_path)
            shutil.copy2(backup / "mediamtx.yml", self.config.mediamtx_path)
            self.system.run(["systemctl", "restart", "dnsmasq"], timeout=30)
            self.system.run(["systemctl", "restart", "mediamtx"], timeout=30)
            raise
        finally:
            dns_temp.unlink(missing_ok=True)
            media_temp.unlink(missing_ok=True)
