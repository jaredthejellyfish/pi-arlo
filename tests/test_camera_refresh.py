import importlib

from arlo_manager.models import Camera

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
