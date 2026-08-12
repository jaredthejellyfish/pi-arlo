import importlib

from arlo_manager.models import Camera
from arlo_manager.system import WakeResult

app_module = importlib.import_module("arlo_manager.app")


def camera():
    return Camera.from_dict(
        "AA382772D686E",
        {
            "name": "Garage",
            "slug": "garage",
            "mac": "fc:9c:98:3a:33:e7",
            "ip": "172.14.1.94",
            "hostname": "VMC4041PB-D686E",
        },
    )


def test_camera_view_exposes_live_battery_signal_and_connection_state():
    item = camera()
    view = app_module.camera_view(
        item,
        {item.serial: {"serial_number": item.serial}},
        {item.mac: {"signal": "-61"}},
        {item.serial: {"BatPercent": 37, "WifiRSSI": -62}},
    )

    assert view["state"] == "online"
    assert view["battery"] == 37
    assert view["signal"] == -62


def test_registered_camera_without_wifi_association_is_sleeping():
    item = camera()
    view = app_module.camera_view(
        item,
        {item.serial: {"serial_number": item.serial}},
        {},
        {item.serial: {"BatPercent": 37}},
    )

    assert view["state"] == "sleeping"
    assert view["online"] is False


def test_camera_status_endpoint_advertises_seven_second_refresh(monkeypatch):
    item = camera()
    monkeypatch.setattr(
        app_module,
        "collect_camera_views",
        lambda: [
            {
                "camera": item,
                "state": "online",
                "online": True,
                "associated": True,
                "battery": 37,
                "signal": -62,
                "status": {"BatPercent": 37, "WifiRSSI": -62},
            }
        ],
    )

    payload = app_module.cameras_status("admin")

    assert payload["interval_seconds"] == 7
    assert payload["cameras"][item.serial]["battery"] == 37
    assert payload["cameras"][item.serial]["state"] == "online"


def test_camera_wake_returns_live_url_only_after_stream_is_ready(monkeypatch):
    item = camera()

    class Store:
        def get(self, serial):
            return item if serial == item.serial else None

    class System:
        def wake_camera(self, serial, mac, slug):
            assert (serial, mac, slug) == (item.serial, item.mac, item.slug)
            return WakeResult(True, True, "Camera is ready.")

        def advertised_host(self):
            return "arlo-hub.local"

    monkeypatch.setattr(app_module, "store", Store())
    monkeypatch.setattr(app_module, "system", System())

    response = app_module.camera_wake(item.serial, "admin")

    assert response.status_code == 200
    assert b'"ready":true' in response.body
    assert b"http://arlo-hub.local:8888/garage/" in response.body


def test_camera_wake_returns_friendly_failure_instead_of_stream_500(monkeypatch):
    item = camera()

    class Store:
        def get(self, serial):
            return item

    class System:
        def wake_camera(self, serial, mac, slug):
            return WakeResult(False, False, "Trigger motion and try again.")

        def advertised_host(self):
            return "arlo-hub.local"

    monkeypatch.setattr(app_module, "store", Store())
    monkeypatch.setattr(app_module, "system", System())

    response = app_module.camera_wake(item.serial, "admin")

    assert response.status_code == 503
    assert b"Trigger motion and try again." in response.body


def test_floodlight_view_maps_native_intensity_to_percent():
    view = app_module.floodlight_view(
        {"SpotlightEnabled": True, "SpotlightIntensityManual": 19275}
    )

    assert view == {"enabled": True, "brightness": 75}


def test_floodlight_view_defaults_to_half_brightness_when_camera_omits_it():
    view = app_module.floodlight_view({"SpotlightEnabled": False})

    assert view == {"enabled": False, "brightness": 50}


def test_floodlight_endpoint_sends_toggle_and_brightness(monkeypatch):
    item = camera()
    calls = []

    class Store:
        def get(self, serial):
            return item

    class System:
        def stations(self):
            return {item.mac: {}}

        def set_camera_floodlight(self, serial, enabled, brightness, ip, slug):
            calls.append((serial, enabled, brightness, ip, slug))
            return True

    monkeypatch.setattr(app_module, "store", Store())
    monkeypatch.setattr(app_module, "system", System())

    payload = app_module.camera_floodlight(
        item.serial,
        app_module.FloodlightCommand(enabled=True, brightness=75),
        "admin",
    )

    assert calls == [(item.serial, True, 75, item.ip, item.slug)]
    assert payload["enabled"] is True
    assert payload["brightness"] == 75


def test_floodlight_endpoint_does_not_send_to_sleeping_camera(monkeypatch):
    item = camera()

    class Store:
        def get(self, serial):
            return item

    class System:
        def stations(self):
            return {}

    monkeypatch.setattr(app_module, "store", Store())
    monkeypatch.setattr(app_module, "system", System())

    try:
        app_module.camera_floodlight(
            item.serial,
            app_module.FloodlightCommand(enabled=False, brightness=40),
            "admin",
        )
    except app_module.HTTPException as error:
        assert error.status_code == 503
        assert "camera is asleep" in error.detail
    else:
        raise AssertionError("Sleeping camera should reject floodlight commands")
