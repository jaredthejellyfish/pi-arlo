from __future__ import annotations

import json
import threading
from typing import Any

import paho.mqtt.client as mqtt

from .models import Camera
from .settings import Settings

SENSORS = {
    "BatteryLevel": ("Battery", "%", "battery", "measurement"),
    "BatPercent": ("Battery", "%", "battery", "measurement"),
    "BatteryCharging": ("Charging", None, None, None),
    "ChargingState": ("Charging", None, None, None),
    "WifiRSSI": ("Wi-Fi RSSI", "dBm", "signal_strength", "measurement"),
    "SignalStrength": ("Signal", None, "signal_strength", "measurement"),
    "Temperature": ("Temperature", "°C", "temperature", "measurement"),
    "SpotlightEnabled": ("Spotlight", None, None, None),
    "IRLEDsOn": ("Infrared LEDs", None, None, None),
}


class MqttBridge:
    def __init__(self, config: Settings):
        self.config = config
        self._client: mqtt.Client | None = None
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.config.mqtt_host)

    def _get_client(self) -> mqtt.Client:
        with self._lock:
            if self._client:
                return self._client
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2, client_id="arlo-base-station-manager"
            )
            if self.config.mqtt_username:
                client.username_pw_set(
                    self.config.mqtt_username, self.config.mqtt_password
                )
            client.connect(self.config.mqtt_host, self.config.mqtt_port, keepalive=30)
            client.loop_start()
            self._client = client
            return client

    def publish(self, topic: str, payload: str, retain: bool = False) -> bool:
        if not self.enabled:
            return False
        try:
            info = self._get_client().publish(topic, payload, qos=1, retain=retain)
            return info.rc == mqtt.MQTT_ERR_SUCCESS
        except (OSError, mqtt.MQTTException):
            with self._lock:
                self._client = None
            return False

    @staticmethod
    def _device(camera: Camera) -> dict[str, Any]:
        model = camera.hostname.split("-")[0]
        return {
            "identifiers": [f"arlo_{camera.serial}"],
            "name": camera.name,
            "manufacturer": "Arlo",
            "model": model,
            "serial_number": camera.serial,
        }

    def publish_discovery(self, camera: Camera, status: dict[str, Any]) -> None:
        state_topic = f"arlo/{camera.serial}/status"
        for key, (name, unit, device_class, state_class) in SENSORS.items():
            if key not in status:
                continue
            unique = f"arlo_{camera.serial}_{key.lower()}"
            payload: dict[str, Any] = {
                "name": name,
                "unique_id": unique,
                "state_topic": state_topic,
                "value_template": f"{{{{ value_json.{key} }}}}",
                "device": self._device(camera),
                "availability_topic": f"arlo/{camera.serial}/availability",
                "payload_available": "online",
                "payload_not_available": "offline",
            }
            if unit:
                payload["unit_of_measurement"] = unit
            if device_class:
                payload["device_class"] = device_class
            if state_class:
                payload["state_class"] = state_class
            self.publish(
                f"homeassistant/sensor/{unique}/config",
                json.dumps(payload),
                retain=True,
            )

        motion = {
            "name": "Motion",
            "unique_id": f"arlo_{camera.serial}_motion",
            "state_topic": f"arlo/{camera.serial}/motion",
            "device_class": "motion",
            "payload_on": "ON",
            "payload_off": "OFF",
            "device": self._device(camera),
        }
        self.publish(
            f"homeassistant/binary_sensor/arlo_{camera.serial}_motion/config",
            json.dumps(motion),
            retain=True,
        )

    def status(self, camera: Camera, status: dict[str, Any]) -> None:
        self.publish_discovery(camera, status)
        self.publish(f"arlo/{camera.serial}/status", json.dumps(status), retain=True)
        self.publish(f"arlo/{camera.serial}/availability", "online", retain=True)

    def motion(self, camera: Camera, active: bool) -> None:
        value = "ON" if active else "OFF"
        self.publish(f"arlo/{camera.serial}/motion", value, retain=False)
        self.publish(f"frigate/{camera.slug}/enabled/set", value, retain=False)

    def remove_discovery(self, camera: Camera) -> None:
        for key in SENSORS:
            unique = f"arlo_{camera.serial}_{key.lower()}"
            self.publish(f"homeassistant/sensor/{unique}/config", "", retain=True)
        self.publish(
            f"homeassistant/binary_sensor/arlo_{camera.serial}_motion/config",
            "",
            retain=True,
        )
