"""Shared HTTP plumbing: one client shape, retry/backoff on 429/5xx.

Every connector builds its own httpx.Client (different auth headers) via
`new_client`, then calls `get_json` for all requests so retry behavior is
identical everywhere. A 204 (used by livestats for a game that never played)
is treated as a normal "no data" result, not an error.
"""

from __future__ import annotations

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from riftquant import config


class RetryableStatus(Exception):
    """Internal signal: response status warrants a retry (429 or 5xx)."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        super().__init__(f"retryable status {response.status_code} for {response.url}")


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (RetryableStatus, httpx.TransportError))


def new_client(user_agent: str, timeout: float = config.HTTP_TIMEOUT_SECS) -> httpx.Client:
    return httpx.Client(headers={"User-Agent": user_agent}, timeout=timeout)


@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=10),
    retry=retry_if_exception(_is_retryable),
)
def get_json(
    client: httpx.Client,
    url: str,
    *,
    params: dict | None = None,
) -> dict | None:
    """GET `url` and decode JSON, retrying on 429/5xx and transport errors.

    Returns None for HTTP 204 No Content.
    """
    resp = client.get(url, params=params)
    if resp.status_code == 204:
        return None
    if resp.status_code == 429 or resp.status_code >= 500:
        raise RetryableStatus(resp)
    resp.raise_for_status()
    return resp.json()
