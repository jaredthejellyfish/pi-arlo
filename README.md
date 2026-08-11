# Pi Arlo Local Base Station

This repository turns a Raspberry Pi 3B+ (or newer Pi with Ethernet and Wi-Fi) into a reboot-safe, fully local Arlo base station:

```text
Arlo cameras -- private wlan0 AP --> Pi -- ordinary eth0 DHCP --> LAN
                                      |-- isolated arlo-cam-api service
                                      |-- on-demand MediaMTX streams
                                      `-- browser-based camera manager
```

The installer does **not** assign an Ethernet address, change a default route, create a bridge, enable forwarding, add NAT/firewall rules, or make NetworkManager ignore Ethernet. `eth0` remains an ordinary DHCP client, so the finished Pi can be plugged into another network and receive an address there. Only `wlan0` is reserved for the private camera network.

## Install on a Pi

Start with a current Raspberry Pi OS Lite installation, connect Ethernet, and enable SSH. Do not configure the Pi's Wi-Fi for household access; it becomes the camera access point.

```bash
git clone <this-repository-url> pi-arlo
cd pi-arlo
sudo ./install.sh
```

The installer is idempotent and safe to run again after pulling an update. It:

- installs hostapd, dnsmasq, the official MediaMTX ARM binary, Avahi/mDNS, and the Python manager;
- makes only `wlan0` unmanaged by NetworkManager;
- assigns `172.14.1.1/24` only to `wlan0` and creates the private `NETGEAR07` AP;
- preserves an existing hostapd SSID/password, `/opt/arlo-cam-api/arlo.db`, API config, DHCP config, MediaMTX config, and manager camera registry;
- pins `arlo-cam-api` commit `7aba818` in its own Python environment, and pins MediaMTX `1.20.0`;
- enables every component at boot with deterministic systemd ordering;
- validates dnsmasq before starting it and checks every live service afterward; and
- prints the manager URL and first-run login at the end.

Open `http://<pi-hostname>.local:8088`. The dashboard shows AP/service health and the Garage/Backyard camera definitions from the project handoff. An offline camera is shown as sleeping/offline rather than treated as an appliance failure.

The two preloaded LAN stream paths use the Pi's stable mDNS hostname:

```text
rtsp://<pi-hostname>.local:8554/garage
rtsp://<pi-hostname>.local:8554/backyard
```

The dashboard also shows the current DHCP address, but it never writes that address into the Pi's networking configuration. If a Frigate host cannot resolve mDNS, set `ARLO_ADVERTISED_HOST` in `/etc/arlo-manager/environment` to a LAN DNS name or the current address; this changes generated URLs only.

## Existing cameras and replacement Pis

On the current base-station Pi, rerunning the installer automatically preserves the AP password and Arlo database in their established paths. Already-paired cameras should reconnect after reboot without WPS.

On a different Pi, paired cameras can reconnect only if it has the same SSID, WPA password, and Arlo database. Those secrets are intentionally not committed here. Put the existing WPA password in a root-readable file and point the installer at it:

```bash
sudo sh -c 'umask 077; read -r -s password; printf "%s" "$password" > /root/arlo-wifi-password'
sudo ARLO_WIFI_PASSWORD_FILE=/root/arlo-wifi-password ./install.sh
```

Restore the old `/opt/arlo-cam-api/arlo.db` before installing if it is available. Without those two pieces, install normally and pair each physical camera again through the manager.

You can set the regulatory domain without editing files:

```bash
sudo ARLO_COUNTRY=US ./install.sh
```

## Add a camera

In the manager, choose **Add camera**, start pairing, then press Sync on the physical Arlo. The manager watches Wi-Fi association, DHCP leases, and the local Arlo API. Once registration completes, enter only a friendly name and stream ID.

Finish Setup performs one transaction:

1. add/update the DHCP reservation;
2. add the MediaMTX on-demand path;
3. validate a temporary dnsmasq configuration and the YAML structure;
4. atomically install both files;
5. restart only dnsmasq and MediaMTX (never hostapd);
6. open the resulting RTSP stream with `ffprobe`; and
7. save manager state only after the stream works.

If any step fails, both live files are restored and the manager shows an error. Backups live under `/var/backups/arlo-manager/`.

## Home Assistant status and motion-driven Frigate

MQTT is optional because broker credentials cannot be assumed. To enable it during installation, supply the broker address and, when needed, credentials. Prefer a root-only file for the MQTT password:

```bash
sudo sh -c 'umask 077; read -r -s password; printf "%s" "$password" > /root/arlo-mqtt-password'
sudo ARLO_MQTT_HOST=homeassistant.local \
  ARLO_MQTT_USERNAME=frigate \
  ARLO_MQTT_PASSWORD_FILE=/root/arlo-mqtt-password \
  ./install.sh
```

The manager then:

- receives local-only status and motion webhooks from `arlo-cam-api`;
- publishes retained Home Assistant MQTT Discovery entities for battery, charging, RSSI/signal, temperature, spotlight, infrared, and motion when those fields are available;
- publishes `ON` to `frigate/<stream-id>/enabled/set` immediately on PIR motion; and
- waits 30 seconds after motion timeout before publishing `OFF`, cancelling that shutdown if motion resumes.

Each camera details page produces a merge-only Frigate snippet. It does not connect to or overwrite the Frigate configuration, so unrelated Office/Living Room cameras are left alone.

To change MQTT later, edit `/etc/arlo-manager/environment` as root, put any password in the root-only file named by `ARLO_MQTT_PASSWORD_FILE`, and restart `arlo-manager`. The environment and secret files are mode `0600`.

## Operations

Run a concise appliance check:

```bash
sudo ./scripts/health-check.sh
```

Useful logs:

```bash
sudo journalctl -u arlo-manager -f
sudo journalctl -u arlo-cam-api -f
sudo journalctl -u mediamtx -f
sudo journalctl -u hostapd -f
```

All services start automatically. Normal reboots never invoke WPS; WPS is used only for a new camera.

## Security and limits

- The manager uses HTTP Basic authentication with a generated first-run password and binds to the LAN. Do not expose port 8088 or the RTSP/HLS ports to the public internet.
- Arlo's local RTSP traffic is not encrypted and has no camera-level authentication. Keep it on networks you control.
- The management service runs as root because it must atomically replace root-owned service files and restart two tightly scoped services. Its systemd unit applies filesystem/kernel hardening and the UI requires authentication.
- Docker is neither installed nor required, so a fresh appliance gets no Docker bridge, IP-forwarding change, or Docker firewall rules. If exact legacy containers named `arlo-cam-api` or `mediamtx` exist, the installer disables their automatic restart and stops them after preserving their mounted data.
- A battery camera intentionally sleeps. MediaMTX opens its source only while a viewer/Frigate reader exists and closes it five seconds after the last reader leaves.

## Development checks

On any Python 3 machine:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check arlo_manager tests
.venv/bin/pytest -q
```

The test suite covers input safety, transactional apply/rollback, preservation of unrelated MediaMTX paths, atomic state, and a guard that prevents future installer changes from touching Ethernet, routing, NAT, or bridges.
