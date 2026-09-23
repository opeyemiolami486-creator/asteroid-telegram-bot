import httpx
import pytest

from bot.models import UserState, Wallet
from bot.stonkscape import StonkScapeBridgeAdapter


@pytest.mark.asyncio
async def test_stonkscape_bridge_requests_code_and_maps_state(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, method, url, json=None):
            calls.append((method, url, json))
            payload = {"play_code": "STONK-123"} if url.endswith("/play-code") else {"state": {"score": 42, "resources": {"gold": 7}, "ship": "BRONZE", "rank": 3}}
            return httpx.Response(200, json=payload, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    adapter = StonkScapeBridgeAdapter("https://bridge.test", "https://play.stonkscape.com/rs2.cgi")
    user = UserState(7, Wallet("demo", ""))
    assert await adapter.request_play_code(user) == "STONK-123"
    user.play_code = "STONK-123"
    user.session_id = "session-1"
    state = await adapter.read_state(user)
    assert state.score == 42
    assert state.resources == {"gold": 7}
    assert calls[0][0] == "POST"
