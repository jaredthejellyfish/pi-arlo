#!/usr/bin/env bash
set -u

failed=0
check_service() {
  local service="$1"
  if systemctl is-active --quiet "$service"; then
    printf 'OK   %s\n' "$service"
  else
    printf 'FAIL %s\n' "$service"
    failed=1
  fi
}

for service in arlo-wlan hostapd dnsmasq arlo-cam-api mediamtx arlo-manager; do
  check_service "$service"
done

if ip -4 -o addr show dev wlan0 | grep -q '172\.14\.1\.1/24'; then
  echo "OK   wlan0 private address"
else
  echo "FAIL wlan0 private address"
  failed=1
fi

if hostapd_cli -i wlan0 status 2>/dev/null | grep -q '^state=ENABLED$'; then
  echo "OK   private Wi-Fi access point"
else
  echo "FAIL private Wi-Fi access point"
  failed=1
fi

if curl -fsS --max-time 3 http://127.0.0.1:5000/device >/dev/null; then
  echo "OK   Arlo API"
else
  echo "FAIL Arlo API"
  failed=1
fi

if curl -fsS --max-time 3 http://127.0.0.1:9997/v3/config/global/get >/dev/null; then
  echo "OK   MediaMTX API"
else
  echo "FAIL MediaMTX API"
  failed=1
fi

exit "$failed"
