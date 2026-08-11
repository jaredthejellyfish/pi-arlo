from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from .models import Camera


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    def all(self) -> dict[str, Camera]:
        with self._lock:
            if not self.path.exists():
                return {}
            raw = json.loads(self.path.read_text())
            return {
                serial: Camera.from_dict(serial, value)
                for serial, value in raw.get("cameras", {}).items()
            }

    def get(self, serial: str) -> Camera | None:
        return self.all().get(serial)

    def save(self, cameras: dict[str, Camera]) -> None:
        data = {
            "cameras": {
                serial: camera.to_dict() for serial, camera in sorted(cameras.items())
            }
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.", dir=self.path.parent
            )
            try:
                with os.fdopen(fd, "w") as handle:
                    json.dump(data, handle, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary_name, 0o600)
                os.replace(temporary_name, self.path)
            except BaseException:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
                raise
