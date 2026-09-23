import pytest

from bot.game_adapter import DemoGameAdapter
from bot.models import UserState, Wallet


@pytest.mark.asyncio
async def test_demo_session_mines_ore_and_updates_score():
    adapter = DemoGameAdapter()
    user = UserState(telegram_user_id=7, wallet=Wallet("test", "secret"))
    user.play_code = await adapter.request_play_code(user)
    user.session_id = await adapter.start_session(user, user.play_code)

    before = await adapter.read_state(user)
    before_score = before.score
    before_ore = before.resources["ore"]
    after = await adapter.submit_action(user, "fire")

    assert user.play_code.startswith("DEMO-")
    assert after.score > before_score
    assert after.resources["ore"] > before_ore
    assert after.resources["metal"] > 0
    assert after.cooldown_seconds == 1.0


@pytest.mark.asyncio
async def test_demo_upgrade_forges_a_better_ship():
    adapter = DemoGameAdapter()
    user = UserState(telegram_user_id=8, wallet=Wallet("test", "secret"))
    user.play_code = await adapter.request_play_code(user)
    user.session_id = await adapter.start_session(user, user.play_code)
    state = adapter.sessions[user.session_id].state
    state.resources["metal"] = 100

    upgraded = await adapter.upgrade(user)

    assert upgraded.ship == "FORGE-02"
    assert upgraded.upgrades["mining"] == 2
    assert upgraded.resources["metal"] == 0
    assert upgraded.score == 100
