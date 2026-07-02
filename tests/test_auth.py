"""Tests for OAuth refresh mode: token store, refresh contract, 401 retry."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import httpx
import pytest
import respx

from clover_mcp.auth import TokenStore, refresh_access_token
from clover_mcp.client import CloverClient
from clover_mcp.config import Config
from clover_mcp.errors import CloverAPIError
from tests.conftest import TEST_MERCHANT_ID

_MERCHANT_PATH = f"/v3/merchants/{TEST_MERCHANT_ID}"
_REFRESH_PATH = "/oauth/v2/refresh"


def _oauth_config(
    token_store: Path, access_token: str = "acc_old", client_secret: str = ""
) -> Config:
    return Config(
        merchant_id=TEST_MERCHANT_ID,
        access_token=access_token,
        region="na",
        sandbox=True,
        auth_mode="oauth_refresh",
        refresh_token="rt_seed",
        oauth_client_id="APPID",
        oauth_client_secret=client_secret,
        token_store=token_store,
    )


# ── TokenStore ────────────────────────────────────────────────────────────────


def test_token_store_round_trip_and_perms(tmp_path: Path) -> None:
    """save() then load() returns the same data; file is 0600."""
    p = tmp_path / "nested" / "tokens.json"
    store = TokenStore(p)
    store.save({"access_token": "a", "refresh_token": "b"})

    assert store.load() == {"access_token": "a", "refresh_token": "b"}
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_token_store_missing_returns_empty(tmp_path: Path) -> None:
    assert TokenStore(tmp_path / "absent.json").load() == {}


# ── refresh_access_token ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_posts_json_and_persists(tmp_path: Path, mock_http: respx.Router) -> None:
    """POSTs {client_id, refresh_token} as JSON (no secret), saves the new pair."""
    store_path = tmp_path / "tokens.json"
    cfg = _oauth_config(store_path)
    route = mock_http.post(_REFRESH_PATH).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "acc_new",
                "refresh_token": "rt_new",
                "access_token_expiration": 111,
                "refresh_token_expiration": 222,
            },
        )
    )

    new = await refresh_access_token(cfg, failed_token="acc_old")

    assert new == "acc_new"
    body = json.loads(route.calls.last.request.content)
    assert body == {"client_id": "APPID", "refresh_token": "rt_seed"}
    assert "client_secret" not in body
    # Persisted pair (single-use rotation written back for next time)
    assert json.loads(store_path.read_text()) == {
        "access_token": "acc_new",
        "refresh_token": "rt_new",
    }


@pytest.mark.asyncio
async def test_refresh_uses_stored_refresh_token(tmp_path: Path, mock_http: respx.Router) -> None:
    """The latest refresh token from the store is used, not the stale env seed."""
    store_path = tmp_path / "tokens.json"
    store_path.write_text(json.dumps({"access_token": "acc_old", "refresh_token": "rt_stored"}))
    cfg = _oauth_config(store_path)
    route = mock_http.post(_REFRESH_PATH).mock(
        return_value=httpx.Response(200, json={"access_token": "acc_new", "refresh_token": "rt_x"})
    )

    await refresh_access_token(cfg, failed_token="acc_old")

    body = json.loads(route.calls.last.request.content)
    assert body["refresh_token"] == "rt_stored"


@pytest.mark.asyncio
async def test_refresh_dedup_skips_when_store_already_newer(
    tmp_path: Path, mock_http: respx.Router
) -> None:
    """If another task already refreshed, reuse its token; don't spend ours."""
    store_path = tmp_path / "tokens.json"
    store_path.write_text(json.dumps({"access_token": "acc_newer", "refresh_token": "rt_x"}))
    cfg = _oauth_config(store_path)
    route = mock_http.post(_REFRESH_PATH).mock(
        return_value=httpx.Response(200, json={"access_token": "SHOULD_NOT_BE_CALLED"})
    )

    new = await refresh_access_token(cfg, failed_token="acc_old")

    assert new == "acc_newer"
    assert not route.called


@pytest.mark.asyncio
async def test_refresh_includes_client_secret_when_set(
    tmp_path: Path, mock_http: respx.Router
) -> None:
    """An operator whose Clover app requires a secret can set it — then it's sent."""
    cfg = _oauth_config(tmp_path / "tokens.json", client_secret="csec")
    route = mock_http.post(_REFRESH_PATH).mock(
        return_value=httpx.Response(200, json={"access_token": "a", "refresh_token": "r"})
    )

    await refresh_access_token(cfg, failed_token="acc_old")

    body = json.loads(route.calls.last.request.content)
    assert body["client_secret"] == "csec"


@pytest.mark.asyncio
async def test_refresh_failure_raises_clover_error(tmp_path: Path, mock_http: respx.Router) -> None:
    """A failed refresh surfaces as CloverAPIError, not a raw httpx.HTTPStatusError."""
    cfg = _oauth_config(tmp_path / "tokens.json")
    mock_http.post(_REFRESH_PATH).mock(
        return_value=httpx.Response(400, json={"message": "invalid_grant"})
    )

    with pytest.raises(CloverAPIError) as exc:
        await refresh_access_token(cfg, failed_token="acc_old")

    assert exc.value.status_code == 400


def test_401_message_is_auth_mode_aware() -> None:
    """The 401 remediation hint points at the refresh grant in oauth_refresh mode,
    not at CLOVER_ACCESS_TOKEN (wrong advice there)."""
    from clover_mcp.errors import raise_for_status

    resp = httpx.Response(401, json={"message": "expired"})
    with pytest.raises(CloverAPIError) as exc:
        raise_for_status(resp, auth_mode="oauth_refresh")
    assert "refresh" in exc.value.message.lower()
    assert "CLOVER_ACCESS_TOKEN" not in exc.value.message


@pytest.mark.asyncio
async def test_concurrent_refresh_spends_token_once(
    tmp_path: Path, mock_http: respx.Router
) -> None:
    """Two refreshes racing on the same store must POST once — the loser reuses
    the winner's token rather than spending the single-use refresh token again.
    Guards the in-process lock and the cross-process file-lock re-read path."""
    import asyncio

    store_path = tmp_path / "tokens.json"
    cfg = _oauth_config(store_path)
    route = mock_http.post(_REFRESH_PATH).mock(
        return_value=httpx.Response(
            200, json={"access_token": "acc_new", "refresh_token": "rt_new"}
        )
    )

    results = await asyncio.gather(
        refresh_access_token(cfg, failed_token="acc_old"),
        refresh_access_token(cfg, failed_token="acc_old"),
    )

    assert results == ["acc_new", "acc_new"]
    assert route.call_count == 1


# ── Client 401 → refresh → retry ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_401_refreshes_and_retries(tmp_path: Path, mock_http: respx.Router) -> None:
    """In oauth_refresh mode, a 401 triggers a refresh and a retry with the new token."""
    cfg = _oauth_config(tmp_path / "tokens.json")
    client = CloverClient(cfg)

    mock_http.post(_REFRESH_PATH).mock(
        return_value=httpx.Response(
            200, json={"access_token": "acc_new", "refresh_token": "rt_new"}
        )
    )
    route = mock_http.get(_MERCHANT_PATH).mock(
        side_effect=[
            httpx.Response(401, json={"message": "expired"}),
            httpx.Response(200, json={"id": TEST_MERCHANT_ID, "name": "Café"}),
        ]
    )

    result = await client.get(_MERCHANT_PATH)

    assert result["id"] == TEST_MERCHANT_ID
    # The retry carried the refreshed token
    assert route.calls.last.request.headers["Authorization"] == "Bearer acc_new"
    await client.close()


@pytest.mark.asyncio
async def test_client_bootstraps_when_no_access_token(
    tmp_path: Path, mock_http: respx.Router
) -> None:
    """oauth_refresh starting with an empty access token (only a refresh token)
    must refresh BEFORE the first request — an empty `Bearer ` header is rejected
    before it can even be sent, so there'd be no 401 to react to."""
    cfg = _oauth_config(tmp_path / "tokens.json", access_token="")
    client = CloverClient(cfg)

    mock_http.post(_REFRESH_PATH).mock(
        return_value=httpx.Response(200, json={"access_token": "acc_boot", "refresh_token": "rt2"})
    )
    route = mock_http.get(_MERCHANT_PATH).mock(
        return_value=httpx.Response(200, json={"id": TEST_MERCHANT_ID, "name": "Café"})
    )

    result = await client.get(_MERCHANT_PATH)

    assert result["id"] == TEST_MERCHANT_ID
    assert route.calls.last.request.headers["Authorization"] == "Bearer acc_boot"
    await client.close()


@pytest.mark.asyncio
async def test_client_token_mode_does_not_refresh(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """In token mode a 401 surfaces directly — no refresh attempt."""
    refresh_route = mock_http.post(_REFRESH_PATH).mock(
        return_value=httpx.Response(200, json={"access_token": "x"})
    )
    mock_http.get(_MERCHANT_PATH).mock(return_value=httpx.Response(401, json={"message": "bad"}))

    with pytest.raises(CloverAPIError) as exc:
        await client.get(_MERCHANT_PATH)

    assert exc.value.status_code == 401
    assert not refresh_route.called
