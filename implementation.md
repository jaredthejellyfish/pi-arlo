# ARLO PRO 4 LOCAL BASE STATION / FRIGATE / HOME ASSISTANT PROJECT HANDOFF

## 1. Overall Goal

The user is building a **fully local Arlo Pro 4 camera system** without relying on Arlo Cloud.

The desired architecture is:

```text
Arlo Pro 4 cameras
        │
        │ private Wi-Fi network
        ▼
Raspberry Pi 3B+ acting as fake Arlo base station
        │
        ├── hostapd
        │     └── Wi-Fi AP / WPS pairing
        │
        ├── dnsmasq
        │     └── DHCP for Arlo cameras
        │
        ├── arlo-cam-api
        │     └── emulates Arlo VMB-style base station
        │
        └── MediaMTX
              └── on-demand RTSP restream
        │
        │ Ethernet / normal LAN
        ▼
Frigate
        │
        ├── object detection
        ├── face recognition
        ├── recordings
        ├── snapshots
        ├── semantic search
        └── MQTT
        │
        ▼
Home Assistant
```

The user wants:

* fully local operation
* Arlos paired to a Raspberry Pi acting as a base station
* multiple cameras on one Pi where Wi-Fi range allows
* on-demand streaming to preserve battery
* Frigate to perform object detection/classification
* Frigate event recordings and snapshots
* Home Assistant live viewing
* Home Assistant battery/RSSI/status entities
* Arlo PIR motion to automatically wake Frigate processing
* cameras to return to sleep when no longer needed
* no manual "turn camera on before viewing" workflow
* eventual **web UI for managing the Pi**
* adding a camera through the web UI should automate:

  * WPS
  * device discovery
  * IP reservation
  * MediaMTX configuration
  * HA status integration
  * generation of Frigate config

The user specifically considers the current manual process too fragile/janky and wants the Pi to become a deterministic appliance that survives reboot.

---

# 2. Hardware / Network

## Raspberry Pi

Current Arlo base station node:

```text
Hostname: arlo-garage
Hardware: Raspberry Pi 3B+
```

The Pi uses:

```text
eth0  → regular household LAN
wlan0 → dedicated Arlo Wi-Fi AP
```

Normal LAN IP of this Pi:

```text
192.168.1.79
```

Arlo-side network:

```text
172.14.1.0/24
```

Pi/base station address:

```text
172.14.1.1
```

Arlo cameras use the Pi as their DHCP default gateway because `arlo-cam-api` expects cameras to contact their default gateway on TCP 4000.

The normal household LAN is:

```text
192.168.1.0/24
```

Home Assistant:

```text
192.168.1.20
```

Frigate MQTT broker is currently also configured at:

```text
192.168.1.20
```

Do NOT assume credentials; preserve the user's existing credentials.

---

# 3. Arlo Cameras Currently Paired

Two Arlo Pro 4 cameras are now successfully paired to this Pi.

## Camera 1 — Garage

MAC:

```text
fc:9c:98:3a:33:e7
```

Reserved camera-side IP:

```text
172.14.1.15
```

Model/hostname:

```text
VMC4041PB-D686E
```

Serial:

```text
AA382772D686E
```

Desired friendly name:

```text
Garage
```

MediaMTX path:

```text
garage
```

LAN-facing RTSP URL:

```text
rtsp://192.168.1.79:8554/garage
```

Direct Arlo RTSP:

```text
rtsp://172.14.1.15/live
```

Ports 554 and 555 have previously both been observed open when the camera is awake.

---

## Camera 2 — Backyard

MAC:

```text
fc:9c:98:39:ea:e9
```

Current / desired reserved IP:

```text
172.14.1.21
```

Model/hostname:

```text
VMC4041PB-D5620
```

Serial:

```text
AA382772D5620
```

Desired friendly name:

```text
Backyard
```

MediaMTX path:

```text
backyard
```

LAN-facing RTSP URL:

```text
rtsp://192.168.1.79:8554/backyard
```

Direct Arlo RTSP:

```text
rtsp://172.14.1.21/live
```

IMPORTANT: The second camera was initially difficult to WPS pair, but eventually paired successfully. Both cameras were confirmed simultaneously associated to `wlan0`.

Example confirmed station state:

```text
Station fc:9c:98:3a:33:e7
authorized: yes
authenticated: yes
associated: yes

Station fc:9c:98:39:ea:e9
authorized: yes
authenticated: yes
associated: yes
```

---

# 4. arlo-cam-api

Project:

```text
https://github.com/brianschrameck/arlo-cam-api
```

Purpose:

* simulates an Arlo base station
* camera must be paired in base-station mode
* direct native Arlo Wi-Fi mode is not suitable
* camera contacts base station/default gateway
* camera API connection uses TCP 4000
* doorbells may use TCP 4100
* REST API runs on TCP 5000

Container name:

```text
arlo-cam-api
```

Persistent mounts currently confirmed:

```text
/opt/arlo-cam-api/config.yaml
    ->
/opt/arlo-cam-api/config.yaml

/opt/arlo-cam-api/arlo.db
    ->
/opt/arlo-cam-api/arlo.db
```

This was verified with:

```bash
sudo docker inspect arlo-cam-api \
  --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

Therefore configuration should be edited directly on the Pi host:

```bash
sudo nano /opt/arlo-cam-api/config.yaml
```

Do NOT try:

```bash
docker exec ... vi
docker exec ... nano
```

because the container is stripped down and contains neither editor.

Useful API:

```bash
curl -s http://127.0.0.1:5000/device | python3 -m json.tool
```

Current expected output conceptually:

```json
[
  {
    "friendly_name": "AA382772D686E",
    "hostname": "VMC4041PB-D686E",
    "ip": "172.14.1.15",
    "serial_number": "AA382772D686E"
  },
  {
    "friendly_name": "AA382772D5620",
    "hostname": "VMC4041PB-D5620",
    "ip": "172.14.1.21",
    "serial_number": "AA382772D5620"
  }
]
```

Detailed status:

```bash
curl -s \
  http://127.0.0.1:5000/device/AA382772D686E \
  | python3 -m json.tool
```

and:

```bash
curl -s \
  http://127.0.0.1:5000/device/AA382772D5620 \
  | python3 -m json.tool
```

The API status has exposed fields such as:

```text
BatteryLevel
BatteryCharging
SignalStrength
WifiRSSI
SpotlightEnabled
IRLEDsOn
```

and many other camera status fields.

IMPORTANT behavior from upstream:

`arlo-cam-api` does not maintain complete runtime state when a camera falls off Wi-Fi or re-registers. The camera gets reprovisioned when it reconnects.

Persistent config/database files therefore matter.

---

# 5. Spotlight Changes Already Attempted

For Garage camera:

```text
AA382772D686E
```

We sent:

```bash
curl -s -X POST \
  http://127.0.0.1:5000/device/AA382772D686E/registerset \
  -H 'Content-Type: application/json' \
  -d '{
    "NightModeLightSourceAlert": 0,
    "PIRAction": "Stream",
    "SpotlightIntensityAlert": 0
  }' | python3 -m json.tool
```

It returned:

```json
{
  "result": true
}
```

Status later reported:

```text
"IRLEDsOn": 0
"SpotlightEnabled": false
```

However, there was still some confusion about a visible light being on. Do not assume `SpotlightEnabled:false` necessarily controls every physical illumination state.

This is NOT currently the main project priority.

---

# 6. hostapd / Wi-Fi AP

Pi is intentionally pretending to be an Arlo base station.

SSID:

```text
NETGEAR07
```

Interface:

```text
wlan0
```

Channel:

```text
1 / 2.4 GHz
```

Known-working hostapd state:

```text
state=ENABLED
ssid[0]=NETGEAR07
```

`iw dev wlan0 info` should show:

```text
Interface wlan0
ssid NETGEAR07
type AP
channel 1
```

The original hostapd config contains roughly:

```ini
interface=wlan0
driver=nl80211

ssid=NETGEAR07

hw_mode=g
channel=1
country_code=US

ieee80211n=1
wmm_enabled=1

auth_algs=1

wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP

wpa_passphrase=<PRESERVE EXISTING VALUE>

ctrl_interface=/var/run/hostapd
ctrl_interface_group=0

eap_server=1
wps_state=2
ap_setup_locked=1

device_name=Arlo Base Station
manufacturer=NETGEAR
model_name=VMB4000
model_number=VMB4000
serial_number=000000000001
device_type=6-0050F204-1
os_version=01020300
config_methods=label display push_button keypad
```

Do NOT change the SSID or WPA passphrase now that cameras are paired.

WPS command for adding another camera:

```bash
sudo hostapd_cli -i wlan0 wps_cancel
sudo hostapd_cli -i wlan0 wps_pbc
```

Watch pairing:

```bash
sudo journalctl -u hostapd -f
```

Useful filtered version:

```bash
sudo journalctl -u hostapd -f \
  | grep --line-buffered -Ei 'WPS|EAP|STA|associated|disassociated|FAIL'
```

Successful pairing eventually contains:

```text
WPA: pairwise key handshake completed (RSN)
```

---

# 7. IMPORTANT NetworkManager Failure That Was Fixed

This was a major cause of instability.

At one point:

```bash
iw dev wlan0 info
```

showed:

```text
ssid LotusBiscoff
type managed
```

instead of:

```text
ssid NETGEAR07
type AP
```

NetworkManager had reclaimed `wlan0` and connected it to the household Wi-Fi network.

This caused:

* NETGEAR07 to disappear
* iPhone could not see the Arlo AP
* cameras could not pair
* original camera disconnected
* `iw dev wlan0 station dump` was empty

The intended solution is to permanently stop NetworkManager from managing `wlan0`.

File:

```text
/etc/NetworkManager/conf.d/arlo-ap.conf
```

Expected:

```ini
[keyfile]
unmanaged-devices=interface-name:wlan0
```

Also manually used:

```bash
sudo nmcli device disconnect wlan0
sudo nmcli device set wlan0 managed no
```

After hardening, `wlan0` must remain dedicated to hostapd.

---

# 8. arlo-wlan.service

We created a systemd service so `wlan0` always gets its Arlo-side IP before hostapd/dnsmasq start.

File:

```text
/etc/systemd/system/arlo-wlan.service
```

Current intended version:

```ini
[Unit]
Description=Configure Arlo WiFi interface
After=systemd-udev-settle.service
Wants=systemd-udev-settle.service
Before=hostapd.service dnsmasq.service

[Service]
Type=oneshot
RemainAfterExit=yes

ExecStart=/bin/sh -c 'for i in $(seq 1 30); do [ -e /sys/class/net/wlan0 ] && exit 0; sleep 1; done; exit 1'
ExecStart=/usr/sbin/ip link set wlan0 down
ExecStart=/usr/sbin/ip addr flush dev wlan0
ExecStart=/usr/sbin/ip addr add 172.14.1.1/24 dev wlan0
ExecStart=/usr/sbin/ip link set wlan0 up

[Install]
WantedBy=multi-user.target
```

Enabled with:

```bash
sudo systemctl daemon-reload
sudo systemctl enable arlo-wlan.service
```

It was confirmed healthy:

```text
arlo-wlan.service
Active: active (exited)
status=0/SUCCESS
```

And:

```bash
ip -4 addr show wlan0
```

showed:

```text
inet 172.14.1.1/24
```

---

# 9. systemd Ordering

hostapd override:

```bash
sudo systemctl edit hostapd
```

Expected:

```ini
[Unit]
Requires=arlo-wlan.service
After=arlo-wlan.service
```

This was confirmed:

```text
Requires=... arlo-wlan.service
After=... arlo-wlan.service ...
```

dnsmasq override:

```bash
sudo systemctl edit dnsmasq
```

Expected:

```ini
[Unit]
Requires=arlo-wlan.service
After=arlo-wlan.service hostapd.service
```

Confirmed systemd state included:

```text
Requires=network-online.target arlo-wlan.service ...
After=arlo-wlan.service ... network-online.target hostapd.service
```

This ordering is critical.

Previously dnsmasq failed with:

```text
DHCP packet received on wlan0 which has no address
```

and:

```text
dnsmasq: unknown interface wlan0
```

because it started before the Wi-Fi interface was ready.

That has now been corrected.

---

# 10. dnsmasq

There was duplicate configuration initially.

Old Arlo configuration existed both in:

```text
/etc/dnsmasq.conf
```

and:

```text
/etc/dnsmasq.d/arlo.conf
```

This caused:

```text
DHCP, IP range 172.14.1.10 -- 172.14.1.20
DHCP, IP range 172.14.1.10 -- 172.14.1.30

Ignoring duplicate dhcp-option 3
```

The duplicates in `/etc/dnsmasq.conf` were commented out.

Now `/etc/dnsmasq.d/arlo.conf` should be the single source of truth.

Desired current file:

```ini
interface=wlan0
bind-interfaces

dhcp-range=172.14.1.10,172.14.1.30,255.255.255.0,24h

dhcp-option=3,172.14.1.1
dhcp-option=6,172.14.1.1

# Garage
dhcp-host=fc:9c:98:3a:33:e7,172.14.1.15

# Backyard
dhcp-host=fc:9c:98:39:ea:e9,172.14.1.21

log-dhcp
```

Validate:

```bash
sudo dnsmasq --test
```

Expected:

```text
dnsmasq: syntax check OK.
```

Restart:

```bash
sudo systemctl restart dnsmasq
```

Healthy startup now shows only:

```text
DHCP, IP range 172.14.1.10 -- 172.14.1.30, lease time 1d
DHCP, sockets bound exclusively to interface wlan0
```

No duplicate range.

Current leases previously confirmed:

```text
fc:9c:98:39:ea:e9 172.14.1.21 VMC4041P-D5620
fc:9c:98:3a:33:e7 172.14.1.15 VMC4041P-D686E
```

Useful command:

```bash
sudo cat /var/lib/misc/dnsmasq.leases
```

---

# 11. MediaMTX

MediaMTX is used because direct Arlo RTSP into Frigate/go2rtc was unreliable.

The pattern that worked:

```text
Arlo
→ MediaMTX on Pi
→ normal LAN
→ Frigate / HA
```

MediaMTX container name:

```text
mediamtx
```

Config path:

```text
/opt/mediamtx/mediamtx.yml
```

Desired two-camera config:

```yaml
paths:
  garage:
    source: rtsp://172.14.1.15/live
    sourceOnDemand: true
    sourceOnDemandStartTimeout: 15s
    sourceOnDemandCloseAfter: 5s
    rtspAnyPort: true

  backyard:
    source: rtsp://172.14.1.21/live
    sourceOnDemand: true
    sourceOnDemandStartTimeout: 15s
    sourceOnDemandCloseAfter: 5s
    rtspAnyPort: true
```

MediaMTX is using host networking.

Restart:

```bash
sudo docker restart mediamtx
```

LAN-facing streams:

```text
rtsp://192.168.1.79:8554/garage
rtsp://192.168.1.79:8554/backyard
```

`sourceOnDemand` is very important for battery cameras.

If there are zero readers, MediaMTX should not continuously hold the Arlo stream open.

---

# 12. Important Battery / Sleep Behavior

The Arlo Pro 4 intentionally shuts down its RTSP servers and enters low-power mode.

Camera logs showed:

```text
Server rtsp_v4 is exited
Server rtsp_v5 is exited
...
enable autoarp mode
...
set PM2 mode
...
enter sleep mode success
```

Therefore an idle Arlo may not always appear like a permanently connected ordinary IP camera.

The project goal is to avoid continuous streaming because that destroys battery life.

Desired behavior:

```text
No one viewing + no motion
→ Arlo sleeping

Home Assistant requests live view
→ MediaMTX requests Arlo RTSP
→ camera wakes
→ live stream works
→ view closes
→ MediaMTX closes source
→ camera sleeps

PIR motion
→ arlo-cam-api event
→ HA enables Frigate camera
→ Frigate consumes stream
→ detects / records / snapshots / classifies
→ motion timeout + grace period
→ HA disables Frigate camera
→ MediaMTX loses reader
→ Arlo sleeps
```

If cameras are eventually wired, continuous streaming becomes more acceptable, but current system design should remain battery-efficient.

---

# 13. Home Assistant Live View

The user already configured HA live viewing themselves.

Requirement:

No special "wake camera" button.

Desired behavior:

```text
open normal Home Assistant camera entity
→ stream automatically works
```

HA should access the Pi/MediaMTX stream, not directly reach into the Arlo camera subnet.

Examples:

```text
rtsp://192.168.1.79:8554/garage
rtsp://192.168.1.79:8554/backyard
```

Do not enable stream preloading for battery cameras because that can keep the source awake.

---

# 14. Frigate

Current Frigate version:

```text
0.17-0
```

User has multiple non-Arlo cameras.

CRITICAL USER PREFERENCE:

**Do not modify or break the Office/Living Room cameras while making Arlo changes.**

Current Frigate camera friendly names:

```text
Jared's Office
Living Room
Garage
Backyard
```

Current intended config:

```yaml
tls:
  enabled: false

mqtt:
  enabled: true
  host: 192.168.1.20
  user: frigate
  password: <PRESERVE EXISTING SECRET>

go2rtc:
  streams:
    cam_a99e26e0:
      - rtsp://admin:<PRESERVE_EXISTING_SECRET>@192.168.1.110:554/ch1/main

    cam_a99e26e1:
      - rtsp://admin:<PRESERVE_EXISTING_SECRET>@192.168.1.102:554/ch1/main

    garage:
      - rtsp://192.168.1.79:8554/garage

    backyard:
      - rtsp://192.168.1.79:8554/backyard

cameras:
  cam_a99e26e0:
    enabled: true
    friendly_name: Jared's Office

    ffmpeg:
      inputs:
        - path: rtsp://127.0.0.1:8554/cam_a99e26e0
          input_args: preset-rtsp-restream
          roles:
            - detect
            - record
            - audio

    detect:
      enabled: true
      fps: 5

    objects:
      track:
        - person
        - dog

    record:
      enabled: true

    snapshots:
      enabled: true

    live:
      streams:
        Stream 1: cam_a99e26e0

    zones:
      main:
        coordinates: 0,0,0,1,1,1,1,0
        loitering_time: 0
        friendly_name: Main

    review:
      alerts:
        required_zones:
          - main

  cam_a99e26e1:
    enabled: true
    friendly_name: Living Room

    ffmpeg:
      inputs:
        - path: rtsp://127.0.0.1:8554/cam_a99e26e1
          input_args: preset-rtsp-restream
          roles:
            - detect
            - record
            - audio

    detect:
      enabled: true
      fps: 5

    objects:
      track:
        - person
        - dog

    record:
      enabled: true

    snapshots:
      enabled: true

    live:
      streams:
        Stream 1: cam_a99e26e1

    zones:
      main:
        coordinates: 0,0,0,1,1,1,1,0
        loitering_time: 0
        friendly_name: Main

    review:
      alerts:
        required_zones:
          - main

  garage:
    enabled: true
    friendly_name: Garage

    ffmpeg:
      inputs:
        - path: rtsp://127.0.0.1:8554/garage
          input_args: preset-rtsp-restream
          roles:
            - detect
            - record

    detect:
      enabled: true
      fps: 5

    objects:
      track:
        - person

    record:
      enabled: true

    snapshots:
      enabled: true

    live:
      streams:
        Stream 1: garage

  backyard:
    enabled: true
    friendly_name: Backyard

    ffmpeg:
      inputs:
        - path: rtsp://127.0.0.1:8554/backyard
          input_args: preset-rtsp-restream
          roles:
            - detect
            - record

    detect:
      enabled: true
      fps: 5

    objects:
      track:
        - person

    record:
      enabled: true

    snapshots:
      enabled: true

    live:
      streams:
        Stream 1: backyard

semantic_search:
  enabled: true
  model_size: large

face_recognition:
  enabled: true
  model_size: large
  recognition_threshold: 0.92
  min_faces: 2

lpr:
  enabled: true

classification:
  bird:
    enabled: false

version: 0.17-0
```

The actual secrets in the user's running config should be preserved.

---

# 15. Frigate Dynamic Camera Enable / Disable

Home Assistant can already turn the Frigate camera entities on/off.

Frigate MQTT supports:

```text
frigate/garage/enabled/set
frigate/garage/enabled/state

frigate/backyard/enabled/set
frigate/backyard/enabled/state
```

Payload:

```text
ON
```

or:

```text
OFF
```

The concept is:

```text
Frigate camera remains configured
but processing can be dynamically disabled.
```

Do NOT set:

```yaml
enabled: false
```

statically in Frigate if the camera should still be available/configured.

Dynamic disable is preferred for battery saving.

---

# 16. Motion Webhook Plan

The user wants the Arlo's hardware PIR to trigger Frigate.

Desired:

```text
Arlo PIR
→ arlo-cam-api
→ Home Assistant webhook
→ turn corresponding Frigate camera ON
```

After motion timeout:

```text
arlo-cam-api
→ HA webhook
→ wait about 30 seconds
→ turn Frigate camera OFF
```

Important reason for 30-second grace period:

Avoid cutting recordings when a person briefly stops moving.

Current `arlo-cam-api` config should eventually include motion URLs to HA.

For Garage, previously proposed:

```yaml
MotionRecordingWebHookUrl: "http://192.168.1.20:8123/api/webhook/arlo_garage_motion"
MotionTimeoutWebHookUrl: "http://192.168.1.20:8123/api/webhook/arlo_garage_motion_end"

NotifyOnMotionAlert: true
NotifyOnMotionTimeoutAlert: true
```

However with multiple cameras, a better end-state is likely **one generic webhook** and route by `serial_number`, rather than unique URLs for each camera.

Important upstream webhook payload fields:

Motion:

```json
{
  "ip": "...",
  "friendly_name": "...",
  "hostname": "...",
  "serial_number": "...",
  "zone": "...",
  "file_name": "...",
  "time": ...
}
```

Motion timeout:

```json
{
  "ip": "...",
  "friendly_name": "...",
  "hostname": "...",
  "serial_number": "...",
  "time": ...
}
```

Therefore HA can map:

```text
AA382772D686E → garage
AA382772D5620 → backyard
```

and dynamically toggle the corresponding Frigate camera.

---

# 17. Status / Battery Integration Goal

This is NOT fully implemented yet.

The user wants Home Assistant to expose all useful camera state:

```text
Battery %
Charging state
Wi-Fi RSSI
Signal strength
Temperature if available
Spotlight state
IR state
Motion
Model
Firmware
IP
possibly other status fields
```

Best proposed architecture:

```text
arlo-cam-api status webhook
→ Home Assistant
→ MQTT
→ MQTT discovery entities
```

This avoids polling and unnecessarily waking battery cameras.

`arlo-cam-api` supports:

```yaml
NotifyRegisteredAndStatusUpdate: true
StatusUpdateWebHookUrl: "http://192.168.1.20:8123/api/webhook/arlo_camera_status"
```

Status webhook structure:

```json
{
  "ip": "...",
  "friendly_name": "...",
  "hostname": "...",
  "serial_number": "...",
  "status": {
    ...
  },
  "time": ...
}
```

One generic webhook can serve every camera.

Proposed HA automation:

```yaml
alias: Arlo - Publish Camera Status to MQTT

triggers:
  - trigger: webhook
    webhook_id: arlo_camera_status
    allowed_methods:
      - POST
    local_only: true

actions:
  - action: mqtt.publish
    data:
      topic: "arlo/{{ trigger.json.serial_number }}/status"
      payload: "{{ trigger.json.status | to_json }}"
      retain: false

mode: parallel
max: 10
```

Then MQTT discovery can create actual Home Assistant devices grouped by serial number.

This should become automatic in the eventual manager UI.

---

# 18. Main New Project: Arlo Base Station Manager Web UI

This is where the user wants to continue next.

The user specifically asked:

> "I want to automate the process of adding new cameras by using a webui that lets me configure what we did to add an extra one"

The proposed software should be a local management interface running on the Pi.

Suggested URL:

```text
http://192.168.1.79:8088
```

Suggested stack:

```text
Python
FastAPI
Jinja templates
HTMX
systemd
```

Avoid a heavy Node/npm stack unless there is a compelling reason.

Desired source structure:

```text
/opt/arlo-manager/
├── app.py
├── config.json
├── requirements.txt
├── templates/
│   ├── index.html
│   ├── add-camera.html
│   └── camera.html
├── static/
└── services/
    ├── arlo.py
    ├── hostapd.py
    ├── dnsmasq.py
    ├── mediamtx.py
    ├── homeassistant.py
    └── frigate.py
```

---

# 19. Web UI Dashboard Requirements

Dashboard should show base station health:

```text
Arlo Base Station
────────────────────────

Access Point
● NETGEAR07
● Channel 1

Services
● arlo-wlan
● hostapd
● dnsmasq
● Docker
● arlo-cam-api
● MediaMTX
```

Camera cards:

```text
Garage

Model:
VMC4041PB-D686E

Serial:
AA382772D686E

MAC:
fc:9c:98:3a:33:e7

Arlo IP:
172.14.1.15

Battery:
XX%

Signal:
XX dBm

Stream:
rtsp://192.168.1.79:8554/garage

[Live] [Edit] [Remove]
```

and equivalent Backyard card.

---

# 20. Add Camera Wizard

Primary workflow:

```text
[ + Add Camera ]
```

Step 1:

```text
Pair New Arlo

1. Put camera near base station.
2. Press Start Pairing.
3. Press Sync on camera.
```

Web app runs:

```bash
hostapd_cli -i wlan0 wps_cancel
hostapd_cli -i wlan0 wps_pbc
```

Before pairing, manager records current devices from:

```text
GET http://127.0.0.1:5000/device
```

Then it watches:

* `iw dev wlan0 station dump`
* `/var/lib/misc/dnsmasq.leases`
* `http://127.0.0.1:5000/device`

When a new serial appears, that is the new camera.

Example UI:

```text
Waiting for camera...

✓ Wi-Fi client detected
  fc:9c:98:xx:xx:xx

✓ DHCP address assigned
  172.14.1.xx

✓ Arlo camera registered
  AA382772DXXXX
  VMC4041PB-DXXXX
```

Then ask only for user-friendly information:

```text
Friendly Name:
[ Backyard ]

Stream ID:
[ backyard ]

IP:
[ 172.14.1.21 ]
```

Technical details should be auto-detected, not manually entered.

---

# 21. What "Finish Setup" Should Automate

## A. DHCP reservation

Modify:

```text
/etc/dnsmasq.d/arlo.conf
```

Add:

```ini
dhcp-host=<MAC>,<CURRENT-IP>
```

Do not randomly renumber an already-working camera unless necessary.

---

## B. MediaMTX

Modify:

```text
/opt/mediamtx/mediamtx.yml
```

Add:

```yaml
friendly_stream_name:
  source: rtsp://CAMERA_IP/live
  sourceOnDemand: true
  sourceOnDemandStartTimeout: 15s
  sourceOnDemandCloseAfter: 5s
  rtspAnyPort: true
```

Expose:

```text
rtsp://192.168.1.79:8554/<stream-name>
```

---

## C. Validate before applying

Run:

```bash
dnsmasq --test
```

Validate MediaMTX YAML programmatically before replacing live config.

Back up current configuration first.

---

## D. Reload services

Prefer graceful reload if supported.

Otherwise controlled restart:

```bash
systemctl restart dnsmasq
docker restart mediamtx
```

Avoid unnecessarily restarting hostapd because that disconnects every camera.

---

## E. Test source

Confirm camera has ports:

```bash
nc -vz CAMERA_IP 554
nc -vz CAMERA_IP 555
```

Test MediaMTX path.

Only mark setup successful if output stream can actually be opened.

---

# 22. Transactional Config Is Important

The manager should NOT directly mutate live files and hope for the best.

Desired workflow:

```text
read existing config
        ↓
create backup
        ↓
modify temp copy
        ↓
validate
        ↓
write atomically
        ↓
reload service
        ↓
health check
        ↓
success
```

If failure:

```text
restore backup
restart/reload
show error
```

This is especially important because the entire motivation for the manager is to eliminate fragile manual state.

Suggested patterns:

```text
/etc/dnsmasq.d/arlo.conf.tmp
/opt/mediamtx/mediamtx.yml.tmp
```

Then atomic rename only after validation.

---

# 23. Frigate Integration From Web UI

Frigate is on another system, so initial manager version should probably **generate the Frigate config instead of automatically overwriting it**.

For a new camera such as Backyard, generate:

```yaml
go2rtc:
  streams:
    backyard:
      - rtsp://192.168.1.79:8554/backyard
```

and:

```yaml
cameras:
  backyard:
    enabled: true
    friendly_name: Backyard

    ffmpeg:
      inputs:
        - path: rtsp://127.0.0.1:8554/backyard
          input_args: preset-rtsp-restream
          roles:
            - detect
            - record

    detect:
      enabled: true
      fps: 5

    objects:
      track:
        - person

    record:
      enabled: true

    snapshots:
      enabled: true

    live:
      streams:
        Stream 1: backyard
```

UI could provide:

```text
[Copy Frigate Configuration]
```

Future improvement could use the Frigate API if a safe supported configuration workflow is identified.

DO NOT overwrite existing Office or Living Room config blindly.

---

# 24. Home Assistant Auto-Provisioning From Web UI

Goal is to avoid HA YAML per camera.

Preferred:

```text
arlo-cam-api status
→ manager or HA webhook
→ MQTT
→ MQTT Discovery
```

For each serial:

```text
arlo/AA382772D686E/status
arlo/AA382772D5620/status
```

Manager should publish MQTT discovery configuration for:

```text
Battery
Charging
Wi-Fi RSSI
Signal
Spotlight
IR
Motion
Temperature if present
```

Device identity should use serial number.

Example device association concept:

```json
{
  "identifiers": ["arlo_AA382772D686E"],
  "name": "Garage",
  "manufacturer": "Arlo",
  "model": "VMC4041PB"
}
```

The manager should ideally automatically publish discovery config when a camera is added.

---

# 25. Motion → Frigate Mapping Should Also Be Automated

When adding a camera, manager knows:

```text
serial
friendly name
stream name
```

Therefore it can create a map like:

```json
{
  "AA382772D686E": {
    "name": "Garage",
    "frigate_camera": "garage"
  },
  "AA382772D5620": {
    "name": "Backyard",
    "frigate_camera": "backyard"
  }
}
```

Then one generic automation/service can do:

```text
motion serial AA382772D686E
→ enable frigate/garage

motion serial AA382772D5620
→ enable frigate/backyard
```

and timeout:

```text
wait ~30 seconds
→ disable corresponding Frigate processing
```

If another motion event happens during the shutdown delay, cancel/restart the delay.

---

# 26. Boot Reliability / Appliance Goal

A major user requirement is:

> after reboot everything should come back automatically

Desired systemd chain:

```text
kernel creates wlan0
        ↓
arlo-wlan.service
        ↓
assign 172.14.1.1/24
        ↓
hostapd
        ↓
broadcast NETGEAR07
        ↓
dnsmasq
        ↓
DHCP ready
        ↓
Docker
        ↓
arlo-cam-api
MediaMTX
        ↓
cameras automatically rejoin
```

No WPS should ever be required after normal reboot.

WPS is only for onboarding a brand-new camera.

The manager dashboard should surface unhealthy states rather than requiring shell diagnostics.

---

# 27. Suggested Health Checks

## wlan0

```bash
iw dev wlan0 info
```

Expected:

```text
ssid NETGEAR07
type AP
```

## AP status

```bash
hostapd_cli -i wlan0 status
```

Expected:

```text
state=ENABLED
```

## WLAN address

```bash
ip -4 addr show wlan0
```

Expected:

```text
172.14.1.1/24
```

## Clients

```bash
iw dev wlan0 station dump
```

## DHCP

```bash
cat /var/lib/misc/dnsmasq.leases
```

## arlo-cam-api

```bash
curl -s http://127.0.0.1:5000/device
```

## Docker

```bash
docker ps
```

## MediaMTX

Check process/container plus stream paths.

The future manager UI should perform all of these checks.

---

# 28. Security Considerations for Manager

The manager needs permission to:

```text
run hostapd_cli
edit dnsmasq config
restart dnsmasq
edit MediaMTX config
restart/reload MediaMTX
read station info
read leases
talk to Docker / arlo-cam-api
```

Do NOT simply run the entire web process as unrestricted root if avoidable.

Better options:

* dedicated `arlo-manager` Unix user
* narrow sudoers entries for specific commands
* helper daemon/service with constrained API
* manager binds only to LAN
* optional authentication

Example commands that may need privilege:

```text
/usr/sbin/hostapd_cli
/usr/bin/systemctl restart dnsmasq
/usr/bin/docker restart mediamtx
```

Files may need controlled group write permissions.

Input such as camera friendly name / stream slug must be sanitized.

Do not pass user strings directly into shell commands.

Use Python subprocess argument arrays, not `shell=True`.

---

# 29. Potential State File

Recommended manager-owned state:

```text
/opt/arlo-manager/config.json
```

Example:

```json
{
  "base_station": {
    "interface": "wlan0",
    "ssid": "NETGEAR07",
    "arlo_gateway": "172.14.1.1",
    "lan_ip": "192.168.1.79"
  },
  "cameras": {
    "AA382772D686E": {
      "name": "Garage",
      "slug": "garage",
      "mac": "fc:9c:98:3a:33:e7",
      "ip": "172.14.1.15",
      "hostname": "VMC4041PB-D686E"
    },
    "AA382772D5620": {
      "name": "Backyard",
      "slug": "backyard",
      "mac": "fc:9c:98:39:ea:e9",
      "ip": "172.14.1.21",
      "hostname": "VMC4041PB-D5620"
    }
  }
}
```

However:

**Do not let this become an independent source of truth that can silently diverge.**

Whenever possible reconcile with:

```text
arlo-cam-api
dnsmasq leases
dnsmasq reservations
MediaMTX config
```

---

# 30. Removing a Camera

Future manager should support removal carefully.

Possible flow:

```text
Select camera
→ confirm serial/name
→ stop MediaMTX source
→ remove DHCP reservation
→ remove manager metadata
→ remove MQTT discovery entities
→ optionally provide Frigate removal snippet
```

Do NOT automatically factory-reset the physical Arlo unless explicitly requested.

Do not disrupt other cameras.

---

# 31. Naming Rules

Current names:

```text
Garage
Backyard
```

Stream slugs:

```text
garage
backyard
```

Desired future behavior:

Friendly name:

```text
Side Yard Camera
```

automatically becomes safe default slug:

```text
side_yard_camera
```

Allow user override.

Slug requirements:

* lowercase
* letters/numbers/underscore
* unique
* no shell characters
* no spaces
* suitable for:

  * MediaMTX path
  * Frigate camera ID
  * MQTT topic suffixes

---

# 32. Important Things NOT To Do

Do not:

* reconnect `wlan0` to LotusBiscoff
* allow NetworkManager to manage `wlan0`
* change NETGEAR07 SSID/password casually
* restart hostapd every time a camera setting changes
* require WPS after normal reboot
* make one arlo-cam-api container per camera
* hard-code random dynamic DHCP addresses without reservation
* continuously poll battery if it wakes the camera
* make Frigate stream 24/7 on battery cameras unless user chooses that tradeoff
* modify Office/Living Room Frigate cameras while working on Arlos
* overwrite Frigate config wholesale
* repeat user passwords in responses
* expose the management UI directly to the public internet

---

# 33. Current Immediate Next Step

The next agent should focus on designing/building the **Arlo Base Station Manager web application**.

Recommended first milestone:

### Phase 1 — Read-only dashboard

Build FastAPI app that can read:

```text
systemctl states
iw wlan0
hostapd status
dnsmasq leases
arlo-cam-api /device
arlo-cam-api individual device status
MediaMTX config
```

Display current Garage and Backyard.

Do not mutate anything yet.

---

### Phase 2 — Pairing wizard

Implement:

```text
Start Pairing
→ run hostapd_cli wps_pbc
→ baseline known serial numbers
→ detect new Wi-Fi client
→ detect DHCP lease
→ detect new arlo-cam-api serial
→ correlate MAC/IP/serial
→ show discovered camera
```

---

### Phase 3 — Finish Setup

Ask:

```text
Friendly Name
Stream Slug
```

Then transactionally:

```text
create DHCP reservation
add MediaMTX path
validate
reload services
test RTSP
persist manager metadata
```

---

### Phase 4 — HA status integration

Implement generic status/motion forwarding and MQTT Discovery.

Goal:

A newly paired camera automatically appears as a Home Assistant device with:

```text
Battery
Charging
Signal
Motion
etc.
```

---

### Phase 5 — Frigate helper

Generate copyable Frigate configuration.

Later consider API-based update only if safe.

---

# 34. Useful Troubleshooting Commands

Full quick health dump:

```bash
echo "=== WLAN ==="
iw dev wlan0 info

echo
echo "=== WLAN IP ==="
ip -4 addr show wlan0

echo
echo "=== HOSTAPD ==="
sudo hostapd_cli -i wlan0 status

echo
echo "=== STATIONS ==="
iw dev wlan0 station dump

echo
echo "=== DHCP ==="
sudo cat /var/lib/misc/dnsmasq.leases

echo
echo "=== ARLO API ==="
curl -s http://127.0.0.1:5000/device | python3 -m json.tool

echo
echo "=== SERVICES ==="
systemctl is-active arlo-wlan hostapd dnsmasq docker

echo
echo "=== DOCKER ==="
sudo docker ps --format 'table {{.Names}}\t{{.Status}}'
```

Pair new camera:

```bash
sudo hostapd_cli -i wlan0 wps_cancel
sudo hostapd_cli -i wlan0 wps_pbc
sudo journalctl -u hostapd -f
```

Check dnsmasq:

```bash
sudo dnsmasq --test
sudo journalctl -u dnsmasq -n 50 --no-pager
```

Check API:

```bash
curl -s http://127.0.0.1:5000/device | python3 -m json.tool
```

Check Garage:

```bash
curl -s \
  http://127.0.0.1:5000/device/AA382772D686E \
  | python3 -m json.tool
```

Check Backyard:

```bash
curl -s \
  http://127.0.0.1:5000/device/AA382772D5620 \
  | python3 -m json.tool
```

RTSP connectivity:

```bash
nc -vz 172.14.1.15 554
nc -vz 172.14.1.15 555

nc -vz 172.14.1.21 554
nc -vz 172.14.1.21 555
```

LAN streams:

```text
rtsp://192.168.1.79:8554/garage
rtsp://192.168.1.79:8554/backyard
```

---

# 35. Final Desired User Experience

The user ultimately wants the system to work like this:

```text
Open browser
↓
Arlo Base Station Manager
↓
+ Add Camera
↓
Start Pairing
↓
Press Sync on physical Arlo
↓
Camera automatically appears
↓
Name it "Driveway"
↓
Finish
```

Behind the scenes:

```text
WPS
DHCP
IP reservation
arlo-cam-api registration
MediaMTX
HA entities
motion events
Frigate config
```

are handled automatically.

After that:

```text
Home Assistant live view
→ works automatically

Arlo detects PIR motion
→ Frigate wakes automatically
→ detects/classifies/records
→ generates snapshot
→ goes idle afterward

Battery/status
→ visible automatically in HA

Pi reboots
→ everything comes back automatically

No shell commands required for normal usage.
```

That is the target state.
