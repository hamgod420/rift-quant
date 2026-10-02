"""Shared HTTP retry/204 handling, exercised via httpx.MockTransport (no
sockets -- nothing here touches the network)."""

from __future__ import annotations

import httpx

from riftquant.http import get_json


def test_get_json_retries_on_429_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "slow down"})
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert get_json(client, "https://example.test/x") == {"ok": True}
    assert calls["n"] == 2


def test_get_json_returns_none_on_204() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(204)))
    assert get_json(client, "https://example.test/x") is None


def test_get_json_passes_params_through() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["query"] = str(request.url.params)
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    get_json(client, "https://example.test/x", params={"hl": "en-US"})
    assert "hl=en-US" in captured["query"]
