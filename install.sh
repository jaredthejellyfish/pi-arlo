#!/usr/bin/env bash
set -Eeuo pipefail

readonly ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly ARLO_API_COMMIT="7aba8181362080fe17f12f3af90fc2f160dd0d34"
readonly MEDIAMTX_VERSION="1.20.0"
readonly INSTALL_ROOT="/opt/arlo-base-station"
readonly API_DATA_DIR="/opt/arlo-cam-api"
readonly MEDIAMTX_DIR="/opt/mediamtx"
readonly MANAGER_DIR="/opt/arlo-manager"
readonly BACKUP_DIR="/var/backups/arlo-manager/install-$(date +%Y%m%d-%H%M%S)"

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this installer with sudo: sudo ./install.sh" >&2
  exit 1
fi

if [[ ! -r /etc/os-release ]] || ! grep -Eq '^ID=(raspbian|debian)$' /etc/os-release; then
  echo "This installer supports Raspberry Pi OS and Debian." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
echo "Installing operating-system packages..."
apt-get update
apt-get install -y --no-install-recommends \
  avahi-daemon ca-certificates curl dnsmasq ffmpeg git hostapd iw netcat-openbsd \
  openssl python3 python3-pip python3-venv rfkill

if ! iw list 2>/dev/null | awk '/Supported interface modes:/{found=1; next} found && /\* AP$/{ok=1; exit} END{exit !ok}'; then
  echo "The wlan0 adapter does not report Wi-Fi access-point support." >&2
  exit 1
fi

install -d -m 0700 "$BACKUP_DIR"
backup_if_present() {
  local source="$1"
  if [[ -e "$source" ]]; then
    cp -a -- "$source" "$BACKUP_DIR/$(echo "$source" | tr / _)"
  fi
}

for item in \
  /etc/hostapd/hostapd.conf \
  /etc/dnsmasq.d/arlo.conf \
  /etc/NetworkManager/conf.d/arlo-ap.conf \
  "$API_DATA_DIR/config.yaml" \
  "$API_DATA_DIR/arlo.db" \
  "$MEDIAMTX_DIR/mediamtx.yml" \
  "$MANAGER_DIR/config.json"; do
  backup_if_present "$item"
done

wifi_ssid="${ARLO_WIFI_SSID:-NETGEAR07}"
wifi_country="${ARLO_COUNTRY:-US}"
wifi_password=""

if [[ -r /etc/hostapd/hostapd.conf ]]; then
  existing_ssid="$(sed -n 's/^ssid=//p' /etc/hostapd/hostapd.conf | head -n1)"
  existing_country="$(sed -n 's/^country_code=//p' /etc/hostapd/hostapd.conf | head -n1)"
  existing_password="$(sed -n 's/^wpa_passphrase=//p' /etc/hostapd/hostapd.conf | head -n1)"
  [[ -z "$existing_ssid" ]] || wifi_ssid="$existing_ssid"
  [[ -z "$existing_country" ]] || wifi_country="$existing_country"
  [[ -z "$existing_password" ]] || wifi_password="$existing_password"
fi

if [[ -z "$wifi_password" && -n "${ARLO_WIFI_PASSWORD_FILE:-}" ]]; then
  wifi_password="$(<"$ARLO_WIFI_PASSWORD_FILE")"
fi
if [[ -z "$wifi_password" ]]; then
  wifi_password="$(openssl rand -hex 16)"
  generated_wifi_password=1
else
  generated_wifi_password=0
fi
if (( ${#wifi_password} < 8 || ${#wifi_password} > 63 )); then
  echo "The Arlo Wi-Fi password must contain 8 to 63 characters." >&2
  exit 1
fi
if [[ ! "$wifi_country" =~ ^[A-Z]{2}$ ]]; then
  echo "ARLO_COUNTRY must be a two-letter uppercase country code." >&2
  exit 1
fi

echo "Configuring wlan0 as the private camera access point..."
install -d -m 0755 /etc/NetworkManager/conf.d /etc/hostapd
cat >/etc/NetworkManager/conf.d/arlo-ap.conf <<'EOF'
[keyfile]
unmanaged-devices=interface-name:wlan0
EOF

cat >/etc/hostapd/hostapd.conf <<EOF
interface=wlan0
driver=nl80211
ssid=$wifi_ssid
hw_mode=g
channel=1
country_code=$wifi_country
ieee80211n=1
wmm_enabled=1
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_passphrase=$wifi_password
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
EOF
chmod 0600 /etc/hostapd/hostapd.conf

if grep -q '^DAEMON_CONF=' /etc/default/hostapd 2>/dev/null; then
  sed -i 's|^DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd
else
  printf '%s\n' 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' >>/etc/default/hostapd
fi

install -D -m 0755 "$ROOT_DIR/system/arlo-wlan-up" /usr/local/sbin/arlo-wlan-up
install -D -m 0644 "$ROOT_DIR/system/arlo-wlan.service" /etc/systemd/system/arlo-wlan.service
install -D -m 0644 "$ROOT_DIR/system/hostapd.override.conf" /etc/systemd/system/hostapd.service.d/override.conf
install -D -m 0644 "$ROOT_DIR/system/dnsmasq.override.conf" /etc/systemd/system/dnsmasq.service.d/override.conf

rfkill unblock wifi || true
systemctl disable --now wpa_supplicant@wlan0.service 2>/dev/null || true
if command -v nmcli >/dev/null 2>&1; then
  nmcli general reload || true
  nmcli device disconnect wlan0 >/dev/null 2>&1 || true
  nmcli device set wlan0 managed no >/dev/null 2>&1 || true
fi

echo "Installing DHCP configuration..."
if [[ ! -e /etc/dnsmasq.d/arlo.conf ]]; then
  install -m 0644 "$ROOT_DIR/config/dnsmasq.conf" /etc/dnsmasq.d/arlo.conf
fi

echo "Installing the Arlo API and MediaMTX..."
install -d -m 0755 "$INSTALL_ROOT/src" "$API_DATA_DIR" "$MEDIAMTX_DIR"
if [[ ! -d "$INSTALL_ROOT/src/arlo-cam-api/.git" ]]; then
  git clone https://github.com/brianschrameck/arlo-cam-api.git "$INSTALL_ROOT/src/arlo-cam-api"
fi
git -C "$INSTALL_ROOT/src/arlo-cam-api" fetch --quiet origin
git -C "$INSTALL_ROOT/src/arlo-cam-api" checkout --quiet --detach "$ARLO_API_COMMIT"
python3 -m venv "$INSTALL_ROOT/arlo-api-venv"
"$INSTALL_ROOT/arlo-api-venv/bin/pip" install --disable-pip-version-check --quiet --upgrade pip
"$INSTALL_ROOT/arlo-api-venv/bin/pip" install --disable-pip-version-check --quiet -r "$INSTALL_ROOT/src/arlo-cam-api/requirements.txt"

case "$(uname -m)" in
  aarch64|arm64) mediamtx_arch=arm64 ;;
  armv7l) mediamtx_arch=armv7 ;;
  armv6l) mediamtx_arch=armv6 ;;
  x86_64|amd64) mediamtx_arch=amd64 ;;
  *) echo "Unsupported processor architecture: $(uname -m)" >&2; exit 1 ;;
esac
media_tmp="$(mktemp -d /tmp/pi-arlo-mediamtx.XXXXXX)"
trap 'rm -rf -- "$media_tmp"' EXIT
media_base="https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}"
media_archive="mediamtx_v${MEDIAMTX_VERSION}_linux_${mediamtx_arch}.tar.gz"
curl -fL --retry 3 -o "$media_tmp/$media_archive" "$media_base/$media_archive"
curl -fL --retry 3 -o "$media_tmp/checksums.sha256" "$media_base/checksums.sha256"
"$ROOT_DIR/scripts/verify-checksum.sh" "$media_tmp/checksums.sha256" "$media_tmp/$media_archive"
tar -xzf "$media_tmp/$media_archive" -C "$media_tmp" mediamtx
install -m 0755 "$media_tmp/mediamtx" /usr/local/bin/mediamtx

if [[ ! -e "$API_DATA_DIR/config.yaml" ]]; then
  install -m 0600 "$ROOT_DIR/config/arlo-api.yaml" "$API_DATA_DIR/config.yaml"
fi
touch "$API_DATA_DIR/arlo.db"
if ! getent passwd arlo-api >/dev/null; then
  useradd --system --home-dir "$API_DATA_DIR" --shell /usr/sbin/nologin arlo-api
fi
chown root:arlo-api "$API_DATA_DIR"
chmod 0770 "$API_DATA_DIR"
chown root:arlo-api "$API_DATA_DIR/config.yaml" "$API_DATA_DIR/arlo.db"
chmod 0640 "$API_DATA_DIR/config.yaml"
chmod 0660 "$API_DATA_DIR/arlo.db"
if [[ ! -e "$MEDIAMTX_DIR/mediamtx.yml" ]]; then
  install -m 0644 "$ROOT_DIR/config/mediamtx.yml" "$MEDIAMTX_DIR/mediamtx.yml"
fi
# MediaMTX 1.20 enables Media over QUIC by default and tries to persist an
# automatically generated TLS keypair. This appliance does not use MoQ and the
# service intentionally has a read-only filesystem, so explicitly disable it.
if ! grep -Eq '^[[:space:]]*moq:' "$MEDIAMTX_DIR/mediamtx.yml"; then
  printf '\nmoq: false\n' >>"$MEDIAMTX_DIR/mediamtx.yml"
fi
if ! getent passwd mediamtx >/dev/null; then
  useradd --system --home-dir "$MEDIAMTX_DIR" --shell /usr/sbin/nologin mediamtx
fi
chown root:mediamtx "$MEDIAMTX_DIR/mediamtx.yml"
chmod 0640 "$MEDIAMTX_DIR/mediamtx.yml"

if command -v docker >/dev/null 2>&1; then
  for old_container in arlo-cam-api mediamtx; do
    if docker inspect "$old_container" >/dev/null 2>&1; then
      docker update --restart=no "$old_container" >/dev/null
      docker stop "$old_container" >/dev/null || true
    fi
  done
fi

echo "Installing the management application..."
install -d -m 0755 "$MANAGER_DIR" /etc/arlo-manager /var/backups/arlo-manager
rm -rf "$MANAGER_DIR/arlo_manager" "$MANAGER_DIR/templates" "$MANAGER_DIR/static"
cp -a "$ROOT_DIR/arlo_manager" "$ROOT_DIR/templates" "$ROOT_DIR/static" "$MANAGER_DIR/"
install -m 0644 "$ROOT_DIR/requirements.txt" "$MANAGER_DIR/requirements.txt"
if [[ ! -e "$MANAGER_DIR/config.json" ]]; then
  install -m 0600 "$ROOT_DIR/config/cameras.json" "$MANAGER_DIR/config.json"
fi

python3 -m venv "$MANAGER_DIR/.venv"
"$MANAGER_DIR/.venv/bin/pip" install --disable-pip-version-check --quiet --upgrade pip
"$MANAGER_DIR/.venv/bin/pip" install --disable-pip-version-check --quiet -r "$MANAGER_DIR/requirements.txt"

"$MANAGER_DIR/.venv/bin/python" - "$API_DATA_DIR/config.yaml" "$wifi_country" <<'PY'
import pathlib
import sys
import tempfile
import yaml

path = pathlib.Path(sys.argv[1])
config = yaml.safe_load(path.read_text()) or {}
config.setdefault("WifiCountryCode", sys.argv[2])
config.update({
    "NotifyRegisteredAndStatusUpdate": True,
    "NotifyOnMotionAlert": True,
    "NotifyOnMotionTimeoutAlert": True,
    "MotionRecordingWebHookUrl": "http://127.0.0.1:8088/api/hooks/motion",
    "MotionTimeoutWebHookUrl": "http://127.0.0.1:8088/api/hooks/motion-timeout",
    "StatusUpdateWebHookUrl": "http://127.0.0.1:8088/api/hooks/status",
    "RegistrationWebHookUrl": "http://127.0.0.1:8088/api/hooks/registration",
})
with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
    yaml.safe_dump(config, handle, sort_keys=False)
    temporary = pathlib.Path(handle.name)
temporary.chmod(0o600)
temporary.replace(path)
PY
chown root:arlo-api "$API_DATA_DIR/config.yaml"
chmod 0640 "$API_DATA_DIR/config.yaml"

if [[ ! -e /etc/arlo-manager/environment ]]; then
  if [[ -n "${ARLO_MANAGER_PASSWORD_FILE:-}" ]]; then
    manager_password="$(<"$ARLO_MANAGER_PASSWORD_FILE")"
    generated_manager_password=0
  else
    manager_password="$(openssl rand -hex 12)"
    generated_manager_password=1
  fi
  printf '%s' "$manager_password" >/etc/arlo-manager/admin-password
  chmod 0600 /etc/arlo-manager/admin-password
  mqtt_password="${ARLO_MQTT_PASSWORD:-}"
  if [[ -n "${ARLO_MQTT_PASSWORD_FILE:-}" ]]; then
    mqtt_password="$(<"$ARLO_MQTT_PASSWORD_FILE")"
  fi
  if [[ -n "$mqtt_password" ]]; then
    printf '%s' "$mqtt_password" >/etc/arlo-manager/mqtt-password
    chmod 0600 /etc/arlo-manager/mqtt-password
    mqtt_password_file=/etc/arlo-manager/mqtt-password
  else
    mqtt_password_file=
  fi
  cat >/etc/arlo-manager/environment <<EOF
ARLO_MANAGER_USERNAME=admin
ARLO_MANAGER_PASSWORD_FILE=/etc/arlo-manager/admin-password
ARLO_ADVERTISED_HOST=${ARLO_ADVERTISED_HOST:-}
ARLO_MQTT_HOST=${ARLO_MQTT_HOST:-}
ARLO_MQTT_PORT=${ARLO_MQTT_PORT:-1883}
ARLO_MQTT_USERNAME=${ARLO_MQTT_USERNAME:-}
ARLO_MQTT_PASSWORD_FILE=$mqtt_password_file
ARLO_MOTION_OFF_DELAY=${ARLO_MOTION_OFF_DELAY:-30}
EOF
  chmod 0600 /etc/arlo-manager/environment
else
  generated_manager_password=0
fi

install -m 0644 "$ROOT_DIR/system/arlo-cam-api.service" /etc/systemd/system/arlo-cam-api.service
install -m 0644 "$ROOT_DIR/system/mediamtx.service" /etc/systemd/system/mediamtx.service
install -m 0644 "$ROOT_DIR/system/arlo-manager.service" /etc/systemd/system/arlo-manager.service

echo "Validating and starting services..."
systemctl daemon-reload
systemctl unmask hostapd
systemctl enable avahi-daemon arlo-wlan hostapd dnsmasq arlo-cam-api mediamtx arlo-manager
systemctl restart arlo-wlan
dnsmasq --test
systemctl restart hostapd dnsmasq arlo-cam-api mediamtx arlo-manager

sleep 3
"$ROOT_DIR/scripts/health-check.sh" || true

host_name="$(hostname -s).local"
echo
echo "Arlo Base Station Manager is installed: http://$host_name:8088"
echo "Ethernet was left on its existing DHCP configuration."
echo "Backups from this run are in $BACKUP_DIR"
if (( generated_manager_password )); then
  echo "Manager username: admin"
  echo "Manager password: $manager_password"
fi
if (( generated_wifi_password )); then
  echo "A new private camera Wi-Fi password was generated."
  echo "It is stored root-only in /etc/hostapd/hostapd.conf and is not needed for WPS pairing."
fi
