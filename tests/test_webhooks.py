import asyncio
import json
from urllib.parse import urlencode

from starlette.requests import Request

from arlo_manager.app import webhook_payload


def request_with_body(body: bytes, content_type: str) -> Request:
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/hooks/status",
            "headers": [(b"content-type", content_type.encode())],
        },
        receive,
    )


def test_upstream_form_webhook_decodes_nested_status_json():
    body = urlencode(
        {
            "serial_number": "AA382772D686E",
            "status": json.dumps({"BatPercent": 38, "WifiRSSI": -49}),
        }
    ).encode()

    payload = asyncio.run(
        webhook_payload(request_with_body(body, "application/x-www-form-urlencoded"))
    )

    assert payload["serial_number"] == "AA382772D686E"
    assert payload["status"] == {"BatPercent": 38, "WifiRSSI": -49}


def test_json_webhook_remains_supported():
    body = json.dumps({"serial_number": "AA382772D686E", "status": {}}).encode()
    payload = asyncio.run(webhook_payload(request_with_body(body, "application/json")))

    assert payload == {"serial_number": "AA382772D686E", "status": {}}
