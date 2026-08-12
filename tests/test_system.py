from arlo_manager.settings import Settings
from arlo_manager.system import CommandResult, SystemReader


class SlowWpsSystem(SystemReader):
    def __init__(self):
        super().__init__(Settings())
        self.commands = []

    def run(self, args, timeout=8):
        self.commands.append((args, timeout))
        command = args[-1]
        if command == "wps_pbc":
            return CommandResult(False, "timed out", timed_out=True)
        if command == "wps_get_status":
            return CommandResult(True, "PBC Status: Active\nLast WPS result: Success")
        return CommandResult(True, "OK")


def test_wps_timeout_is_accepted_when_hostapd_reports_active():
    system = SlowWpsSystem()

    result = system.start_pairing()

    assert result.ok is True
    assert any(command[-1] == "wps_get_status" for command, _ in system.commands)


def test_hostapd_cli_uses_socket_directory_shared_with_hostapd():
    system = SystemReader(Settings())

    command = system.hostapd_cli()

    assert "-p/run/hostapd" in command
    assert "-s/run/hostapd" in command
    assert command[-2:] == ["-i", "wlan0"]


def test_stream_active_uses_direct_register_message(monkeypatch):
    requests = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"result": True}

    def post(url, **kwargs):
        requests.append((url, kwargs))
        return Response()

    monkeypatch.setattr("arlo_manager.system.httpx.post", post)
    system = SystemReader(Settings(arlo_api_url="http://arlo.test"))

    assert system.set_camera_stream_active("CAMERA123") is True
    assert requests == [
        (
            "http://arlo.test/device/CAMERA123/message",
            {
                "json": {
                    "Type": "registerSet",
                    "SetValues": {"UserStreamActive": 0},
                },
                "timeout": 6,
            },
        )
    ]


def test_floodlight_maps_percent_to_camera_intensity(monkeypatch):
    requests = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"result": True}

    monkeypatch.setattr(
        "arlo_manager.system.httpx.post",
        lambda url, **kwargs: requests.append((url, kwargs)) or Response(),
    )
    monkeypatch.setattr(
        SystemReader, "request_camera_status", lambda self, serial: True
    )
    resets = []
    monkeypatch.setattr(
        SystemReader,
        "reset_camera_stream",
        lambda self, ip, slug: resets.append((ip, slug)) or True,
    )
    system = SystemReader(Settings(arlo_api_url="http://arlo.test"))

    assert system.set_camera_floodlight(
        "CAMERA123", True, 75, "172.14.1.22", "side_yard"
    ) is True
    assert requests == [
        (
            "http://arlo.test/device/CAMERA123/registerset",
            {
                "json": {
                    "SpotlightEnabled": True,
                    "SpotlightIntensityManual": 19275,
                    "SpotlightIntensityAlert": 19275,
                    "NightModeLightSourceAlert": 1,
                    "NightVisionMode": True,
                    "PIRAction": "Stream+Spotlight",
                },
                "timeout": 6,
            },
        )
    ]
    assert resets == [("172.14.1.22", "side_yard")]


def test_floodlight_off_zeros_output_and_disables_motion_retrigger(monkeypatch):
    requests = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"result": True}

    monkeypatch.setattr(
        "arlo_manager.system.httpx.post",
        lambda url, **kwargs: requests.append((url, kwargs)) or Response(),
    )
    monkeypatch.setattr(
        SystemReader, "request_camera_status", lambda self, serial: True
    )
    resets = []
    monkeypatch.setattr(
        SystemReader,
        "reset_camera_stream",
        lambda self, ip, slug: resets.append((ip, slug)) or True,
    )
    system = SystemReader(Settings(arlo_api_url="http://arlo.test"))

    assert system.set_camera_floodlight(
        "CAMERA123", False, 75, "172.14.1.22", "side_yard"
    ) is True
    assert requests[0][1]["json"] == {
        "SpotlightEnabled": False,
        "SpotlightIntensityManual": 0,
        "SpotlightIntensityAlert": 19275,
        "NightModeLightSourceAlert": 0,
        "NightVisionMode": False,
        "PIRAction": "Stream",
    }
    assert resets == [("172.14.1.22", "side_yard")]


def test_stream_reset_temporarily_detaches_only_matching_camera(monkeypatch):
    patches = []

    class Response:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "arlo_manager.system.httpx.patch",
        lambda url, **kwargs: patches.append((url, kwargs)) or Response(),
    )
    monkeypatch.setattr("arlo_manager.system.time.sleep", lambda _: None)
    system = SystemReader(Settings(mediamtx_api_url="http://media.test"))
    assert system.reset_camera_stream("172.14.1.22", "side_yard") is True
    assert patches == [
        (
            "http://media.test/v3/config/paths/patch/side_yard",
            {
                "json": {"source": "publisher", "sourceOnDemand": False},
                "timeout": 4,
            },
        ),
        (
            "http://media.test/v3/config/paths/patch/side_yard",
            {
                "json": {
                    "source": "rtsp://172.14.1.22/live",
                    "sourceOnDemand": True,
                },
                "timeout": 4,
            },
        ),
    ]


class WakeSystem(SystemReader):
    def __init__(self, stations, stream_ok=True):
        super().__init__(Settings())
        self.station_results = iter(stations)
        self.last_stations = {}
        self.stream_ok = stream_ok
        self.actions = []

    def stations(self):
        try:
            self.last_stations = next(self.station_results)
        except StopIteration:
            pass
        return self.last_stations

    def request_camera_status(self, serial):
        self.actions.append(("status", serial))
        return True

    def set_camera_stream_active(self, serial, active=True):
        self.actions.append(("stream-active", serial, active))
        return True

    def test_stream(self, slug):
        self.actions.append(("stream-test", slug))
        return CommandResult(self.stream_ok, "")


def test_wake_camera_waits_for_association_then_validates_stream(monkeypatch):
    monkeypatch.setattr("arlo_manager.system.time.sleep", lambda _: None)
    times = iter([0, 0, 1, 2])
    monkeypatch.setattr("arlo_manager.system.time.monotonic", lambda: next(times))
    system = WakeSystem([{}, {"aa:bb:cc:dd:ee:ff": {}}])

    result = system.wake_camera(
        "CAMERA123", "AA:BB:CC:DD:EE:FF", "garage", association_timeout=5
    )

    assert result.ready is True
    assert result.associated is True
    assert system.actions == [
        ("status", "CAMERA123"),
        ("stream-active", "CAMERA123", True),
        ("stream-test", "garage"),
    ]


def test_wake_camera_returns_recovery_message_when_radio_stays_offline(
    monkeypatch,
):
    monkeypatch.setattr("arlo_manager.system.time.sleep", lambda _: None)
    times = iter([0, 0, 2])
    monkeypatch.setattr("arlo_manager.system.time.monotonic", lambda: next(times))
    system = WakeSystem([{}, {}])

    result = system.wake_camera(
        "CAMERA123", "aa:bb:cc:dd:ee:ff", "garage", association_timeout=1
    )

    assert result.ready is False
    assert result.associated is False
    assert "reseat the battery once" in result.message
    assert system.actions == []
