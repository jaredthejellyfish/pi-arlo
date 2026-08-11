#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: verify-checksum.sh CHECKSUM_FILE ARCHIVE" >&2
  exit 2
fi

checksum_file="$1"
archive="$2"
archive_name="$(basename -- "$archive")"

expected="$({
  awk -v name="$archive_name" '
    $2 == name || $2 == "*" name { print $1 }
  ' "$checksum_file"
} | head -n 2)"

if [[ ! "$expected" =~ ^[[:xdigit:]]{64}$ ]]; then
  echo "Could not find one valid SHA-256 checksum for $archive_name" >&2
  exit 1
fi

actual="$(sha256sum -- "$archive" | awk '{print $1}')"
if [[ "$actual" != "$expected" ]]; then
  echo "Checksum mismatch for $archive_name" >&2
  exit 1
fi

echo "$archive_name: OK"
