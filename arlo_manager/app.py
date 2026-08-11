from __future__ import annotations

import asyncio
import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .configuration import ConfigurationError, ConfigurationManager
from .models import Camera
from .mqtt_bridge import MqttBridge
from .pairing import PairingCoordinator
from .settings import settings
from .store import StateStore
from .system import SystemReader

BASE_DIR = Path(__file__).resolve().parent.parent
app = FastAPI(title="Arlo Base Station Manager", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
security = HTTPBasic(auto_error=False)
store = StateStore(settings.state_path)
system = SystemReader(settings)
configuration = ConfigurationManager(settings, store, system)
pairing = PairingCoordinator(system)
mqtt = MqttBridge(settings)
motion_tasks: dict[str, asyncio.Task[None]] = {}


def require_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> str:
    valid_username = credentials is not None and secrets.compare_digest(
        credentials.username, settings.username
    )
    valid_password = (
        credentials is not None
        and bool(settings.password)
        and secrets.compare_digest(credentials.password, settings.password)
    )
    if not (valid_username and valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": 'Basic realm="Arlo Manager"'},
        )
    return credentials.username


def local_hook(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1"}:
        raise HTTPException(status_code=403, detail="Webhook is local-only")


async def webhook_payload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        value = await request.json()
        return value if isinstance(value, dict) else {}

    form = await request.form()
    payload: dict[str, Any] = dict(form)
    for key, value in tuple(payload.items()):
        if isinstance(value, str) and value[:1] in {"{", "["}:
            try:
                payload[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return payload


def recoverable_serials() -> set[str]:
    configured = store.all()
    leases = system.leases()
    recoverable: set[str] = set()
    for device in system.arlo_devices():
        serial = str(device.get("serial_number", ""))
        ip = str(device.get("ip", ""))
        lease = leases.get(ip)
        current = configured.get(serial)
        if lease and (
            current is None or current.ip != ip or current.mac != lease.get("mac")
        ):
            recoverable.add(serial)
    return recoverable


def camera_view(
    camera: Camera,
    devices: dict[str, dict[str, Any]],
    stations: dict[str, dict[str, Any]],
    statuses: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    device = devices.get(camera.serial, {})
    associated = camera.mac in stations
    state = "online" if associated else "sleeping" if device else "offline"
    status = statuses.get(camera.serial, {})
    return {
        "camera": camera,
        "online": state == "online",
        "state": state,
        "associated": associated,
        "battery": status.get("BatteryLevel", status.get("BatPercent")),
        "signal": status.get("WifiRSSI", stations.get(camera.mac, {}).get("signal")),
        "status": status,
        "station": stations.get(camera.mac, {}),
    }


def collect_camera_views() -> list[dict[str, Any]]:
    cameras = store.all()
    with ThreadPoolExecutor(max_workers=2) as executor:
        devices_future = executor.submit(system.arlo_devices)
        stations_future = executor.submit(system.stations)
        device_list = devices_future.result()
        stations = stations_future.result()
    devices = {str(item.get("serial_number", "")): item for item in device_list}
    reporting_serials = [serial for serial in cameras if serial in devices]
    with ThreadPoolExecutor(max_workers=max(1, len(reporting_serials))) as executor:
        status_futures = {
            serial: executor.submit(system.arlo_status, serial)
            for serial in reporting_serials
        }
        statuses = {
            serial: future.result() for serial, future in status_futures.items()
        }
    return [
        camera_view(camera, devices, stations, statuses)
        for camera in cameras.values()
    ]


@app.get("/", response_class=HTMLResponse)
def index(request: Request, _: str = Depends(require_auth)) -> HTMLResponse:
    with ThreadPoolExecutor(max_workers=2) as executor:
        health_future = executor.submit(system.health)
        cameras_future = executor.submit(collect_camera_views)
        health = health_future.result()
        cameras = cameras_future.result()
    context = {
        "request": request,
        "health": health,
        "cameras": cameras,
        "advertised_host": system.advertised_host(),
        "mqtt_enabled": mqtt.enabled,
    }
    return templates.TemplateResponse(request, "index.html", context)


@app.get("/api/health")
def health(_: str = Depends(require_auth)) -> dict[str, Any]:
    return system.health()


@app.get("/api/cameras/status")
def cameras_status(_: str = Depends(require_auth)) -> dict[str, Any]:
    views = collect_camera_views()
    return {
        "updated_at": time.time(),
        "interval_seconds": 7,
        "cameras": {
            item["camera"].serial: {
                "state": item["state"],
                "online": item["online"],
                "associated": item["associated"],
                "battery": item["battery"],
                "signal": item["signal"],
                "status": item["status"],
            }
            for item in views
        },
    }


@app.get("/pair", response_class=HTMLResponse)
def pair_page(request: Request, _: str = Depends(require_auth)) -> HTMLResponse:
    return templates.TemplateResponse(request, "pair.html", {"suggested_slug": ""})


@app.post("/api/pair/start")
def pair_start(_: str = Depends(require_auth)) -> dict[str, Any]:
    try:
        session = pairing.start(recoverable_serials())
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"session": session.identifier, "expires_in": 180}


@app.get("/api/pair/{identifier}")
def pair_status(identifier: str, _: str = Depends(require_auth)) -> dict[str, Any]:
    try:
        return pairing.status(identifier)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/pair/finish")
def pair_finish(
    serial: str = Form(...),
    hostname: str = Form(...),
    mac: str = Form(...),
    ip: str = Form(...),
    name: str = Form(...),
    slug: str = Form(...),
    _: str = Depends(require_auth),
) -> RedirectResponse:
    try:
        camera = Camera.from_dict(
            serial,
            {"hostname": hostname, "mac": mac, "ip": ip, "name": name, "slug": slug},
        )
        cameras = store.all()
        if any(
            item.slug == camera.slug and item.serial != camera.serial
            for item in cameras.values()
        ):
            raise ValueError("That stream ID is already in use")
        cameras[camera.serial] = camera
        configuration.apply(cameras, test_slug=camera.slug)
        system.set_arlo_friendly_name(camera.serial, camera.name)
    except (ValueError, ConfigurationError, OSError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(url=f"/camera/{camera.serial}?created=1", status_code=303)


@app.get("/camera/{serial}", response_class=HTMLResponse)
def camera_page(
    request: Request, serial: str, _: str = Depends(require_auth)
) -> HTMLResponse:
    camera = store.get(serial)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return templates.TemplateResponse(
        request,
        "camera.html",
        {
            "camera": camera,
            "status": system.arlo_status(serial),
            "host": system.advertised_host(),
            "frigate": frigate_snippet(camera, system.advertised_host()),
        },
    )


@app.post("/camera/{serial}/remove")
def camera_remove(
    serial: str, confirmation: str = Form(...), _: str = Depends(require_auth)
) -> RedirectResponse:
    camera = store.get(serial)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    if confirmation != serial:
        raise HTTPException(
            status_code=400, detail="Confirmation did not match the camera serial"
        )
    cameras = store.all()
    cameras.pop(serial)
    try:
        configuration.apply(
            cameras, removed_slugs={camera.slug}, removed_macs={camera.mac}
        )
    except (ConfigurationError, OSError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    mqtt.remove_discovery(camera)
    return RedirectResponse(url="/", status_code=303)


def frigate_snippet(camera: Camera, host: str) -> str:
    return f"""go2rtc:
  streams:
    {camera.slug}:
      - rtsp://{host}:8554/{camera.slug}

cameras:
  {camera.slug}:
    enabled: true
    friendly_name: {camera.name}
    ffmpeg:
      inputs:
        - path: rtsp://127.0.0.1:8554/{camera.slug}
          input_args: preset-rtsp-restream
          roles: [detect, record]
    detect:
      enabled: true
      fps: 5
    objects:
      track: [person]
    record:
      enabled: true
    snapshots:
      enabled: true
    live:
      streams:
        Stream 1: {camera.slug}
"""


@app.post("/api/hooks/status")
async def hook_status(request: Request, _: None = Depends(local_hook)) -> JSONResponse:
    payload = await webhook_payload(request)
    camera = store.get(str(payload.get("serial_number", "")))
    if camera and isinstance(payload.get("status"), dict):
        await asyncio.to_thread(mqtt.status, camera, payload["status"])
    return JSONResponse({"accepted": bool(camera)})


@app.post("/api/hooks/motion")
async def hook_motion(request: Request, _: None = Depends(local_hook)) -> JSONResponse:
    payload = await webhook_payload(request)
    serial = str(payload.get("serial_number", ""))
    camera = store.get(serial)
    if camera:
        pending = motion_tasks.pop(serial, None)
        if pending:
            pending.cancel()
        await asyncio.to_thread(mqtt.motion, camera, True)
    return JSONResponse({"accepted": bool(camera)})


async def delayed_motion_off(camera: Camera) -> None:
    try:
        await asyncio.sleep(settings.motion_off_delay)
        await asyncio.to_thread(mqtt.motion, camera, False)
    finally:
        motion_tasks.pop(camera.serial, None)


@app.post("/api/hooks/motion-timeout")
async def hook_motion_timeout(
    request: Request, _: None = Depends(local_hook)
) -> JSONResponse:
    payload = await webhook_payload(request)
    serial = str(payload.get("serial_number", ""))
    camera = store.get(serial)
    if camera:
        pending = motion_tasks.pop(serial, None)
        if pending:
            pending.cancel()
        motion_tasks[serial] = asyncio.create_task(delayed_motion_off(camera))
    return JSONResponse(
        {"accepted": bool(camera), "off_delay": settings.motion_off_delay}
    )


@app.post("/api/hooks/{event}")
async def hook_other(
    event: str, request: Request, _: None = Depends(local_hook)
) -> JSONResponse:
    await request.body()
    return JSONResponse({"accepted": True, "event": event})


@app.exception_handler(ConfigurationError)
async def configuration_error(_: Request, error: ConfigurationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(error)})
