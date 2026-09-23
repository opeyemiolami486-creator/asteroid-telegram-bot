import pytest

from bot.game_adapter import PlanetForgeAdapter, PlanetForgeInvalidRunError, PlanetForgePreviewBranchMissingError
from bot.models import UserState, Wallet
from bot.wallet import SolanaWalletProvider


@pytest.fixture
def adapter():
    return PlanetForgeAdapter("https://planet-forge.com", SolanaWalletProvider("00" * 32).signer)


def test_economy_plan_crafts_the_cheapest_affordable_ship():
    state = {
        "inventory": [
            {"itemKind": "material", "itemId": "iron", "quantity": 250},
            {"itemKind": "material", "itemId": "silver", "quantity": 50},
            {"itemKind": "ship", "itemId": "scout", "shipVariant": "standard"},
        ]
    }
    catalog = {"ships": [
        {"id": "vulture", "name": "Vulture", "materialCost": {"iron": 150, "silver": 20}, "craftable": True},
        {"id": "corsair", "name": "Corsair", "materialCost": {"iron": 220, "silver": 80}, "craftable": True},
    ]}
    assert PlanetForgeAdapter.economy_plan(state, catalog) == {
        "kind": "craft", "itemKind": "ship", "itemId": "vulture", "shipVariant": "standard", "name": "Vulture"
    }


def test_economy_plan_recommends_buy_when_materials_are_missing():
    plan = PlanetForgeAdapter.economy_plan(
        {"inventory": [{"itemKind": "ship", "itemId": "scout", "shipVariant": "standard"}]},
        {"ships": [{"id": "vulture", "name": "Vulture", "materialCost": {"iron": 150}, "craftable": True}]},
    )
    assert plan["kind"] == "buy"
    assert plan["itemId"] == "vulture"


def test_state_maps_live_player_state_inventory_and_xp():
    state = PlanetForgeAdapter._state({
        "player": {"xp": 1234, "level": 4, "equippedShipId": "ship-blueprint"},
        "inventory": [
            {"itemKind": "material", "itemId": "iron", "quantity": 87},
            {"itemKind": "material", "itemId": "silver", "quantity": 12},
            {"itemKind": "ship", "itemId": "ship-blueprint", "id": "ship-inventory-row"},
        ],
    })
    assert state.score == 1234
    assert state.rank == 4
    assert state.resources == {"iron": 87, "silver": 12}
    assert state.ship == "ship-blueprint"


def test_state_applies_reported_cooldown_reduction():
    state = PlanetForgeAdapter._state({
        "cooldown_seconds": 4,
        "cooldownReduction": 1.5,
    })
    assert state.cooldown_seconds == 2.5


def test_state_accepts_dictionary_wrapped_numeric_values():
    state = PlanetForgeAdapter._state({
        "score": {"value": 1234},
        "rank": {"level": 4},
        "cooldown_seconds": {"seconds": 3},
        "inventory": [{"itemKind": "material", "itemId": "iron", "quantity": {"amount": 87}}],
    })
    assert state.score == 1234
    assert state.rank == 4
    assert state.cooldown_seconds == 3
    assert state.resources == {"iron": 87}


def test_economy_plan_prefers_cooldown_reduction_when_cost_is_affordable():
    plan = PlanetForgeAdapter.economy_plan(
        {"inventory": [{"itemKind": "material", "itemId": "iron", "quantity": 500}]},
        {"ships": [
            {"id": "cheap", "name": "Cheap", "materialCost": {"iron": 10}, "cooldownReduction": 0.1},
            {"id": "quick", "name": "Quick", "materialCost": {"iron": {"amount": 100}}, "cooldownReduction": 1.0},
        ]},
    )
    assert plan["itemId"] == "quick"


@pytest.mark.asyncio
async def test_restart_chooses_highest_normal_level_unlocked_by_xp(adapter, monkeypatch):
    user = UserState(1, Wallet(adapter.signer.address, "00" * 32))
    calls = []

    async def invoke(function, _user, **args):
        calls.append((function, args))
        if function == "playerState":
            return {"player": {"xp": 3000, "equippedShipId": "ship-inv"}, "inventory": [{"itemKind": "ship", "id": "ship-inv", "itemId": "ship"}]}
        if function == "catalog":
            return {"levels": [
                {"id": "one", "order": 1, "xpRequired": 0, "durationSec": 60},
                {"id": "two", "order": 2, "xpRequired": 300, "durationSec": 80},
                {"id": "three", "order": 3, "xpRequired": 3000, "durationSec": 100},
                {"id": "special", "order": 7, "xpRequired": 0, "name": "NEPHELIS", "durationSec": 90},
            ]}
        return {"runId": "run-1", "heartbeatToken": "hb"}

    monkeypatch.setattr(adapter, "_invoke", invoke)
    run_id = await adapter.start_session(user, "pilot")
    assert run_id == "run-1"
    assert [args for name, args in calls if name == "startRun"][0]["levelId"] == "three"


@pytest.mark.asyncio
async def test_invalid_heartbeat_restarts_run_and_keeps_tick_alive(adapter, monkeypatch):
    user = UserState(2, Wallet(adapter.signer.address, "00" * 32), play_code="pilot")
    adapter._runs[user.telegram_user_id] = {
        "run_id": "expired-run",
        "heartbeat_token": "expired-token",
        "level_id": "one",
        "ship_inv_id": "ship-inv",
        "started_at": 0.0,
        "duration": 90.0,
        "kills": 0,
        "inputs": 0,
        "last_heartbeat": 0.0,
        "completed": False,
    }
    calls = []

    async def invoke(function, _user, **args):
        calls.append((function, args))
        if function == "runHeartbeat":
            raise PlanetForgeInvalidRunError("Planet Forge run is no longer valid")
        if function == "playerState":
            return {"player": {"xp": 10, "equippedShipId": "ship-inv"}, "inventory": [{"itemKind": "ship", "id": "ship-inv", "itemId": "ship"}]}
        if function == "catalog":
            return {"levels": [{"id": "one", "order": 1, "xpRequired": 0, "durationSec": 90}]}
        return {"runId": "fresh-run", "heartbeatToken": "fresh-token"}

    monkeypatch.setattr(adapter, "_invoke", invoke)

    state = await adapter.submit_action(user, "fire")

    assert state.alive
    assert user.session_id == "fresh-run"
    assert adapter._runs[user.telegram_user_id]["run_id"] == "fresh-run"
    assert [name for name, _ in calls] == ["runHeartbeat", "playerState", "catalog", "startRun", "playerState"]


@pytest.mark.asyncio
async def test_daily_reward_is_optional_and_throttled(adapter, monkeypatch):
    user = UserState(3, Wallet(adapter.signer.address, "00" * 32))
    calls = []

    async def invoke(function, _user, **args):
        calls.append(function)
        return {"claimed": True, "reward": {"metal": 25}}

    monkeypatch.setattr(adapter, "_invoke", invoke)

    assert await adapter.claim_daily_reward(user) == "daily reward claimed: {'metal': 25}"
    assert await adapter.claim_daily_reward(user) is None
    assert calls == ["claimDailyReward"]


@pytest.mark.asyncio
async def test_missing_preview_branch_completes_as_recoverable_run(adapter, monkeypatch):
    user = UserState(4, Wallet(adapter.signer.address, "00" * 32))
    adapter._runs[user.telegram_user_id] = {
        "run_id": "preview-run", "heartbeat_token": "hb", "level_id": "one",
        "ship_inv_id": "ship-inv", "started_at": 0.0, "duration": 0.0,
        "kills": 3, "inputs": 4, "last_heartbeat": 0.0, "completed": False,
    }

    async def invoke(function, _user, **args):
        if function == "completeLevel":
            raise PlanetForgePreviewBranchMissingError("preview branch not found")
        return {"score": 42}

    monkeypatch.setattr(adapter, "_invoke", invoke)
    state = await adapter.read_state(user)

    assert state.game_over
    assert adapter._runs[user.telegram_user_id]["completed"]


@pytest.mark.asyncio
async def test_heartbeat_includes_shot_hit_and_accuracy_telemetry(adapter, monkeypatch):
    user = UserState(5, Wallet(adapter.signer.address, "00" * 32))
    adapter._runs[user.telegram_user_id] = {
        "run_id": "run", "heartbeat_token": "hb", "level_id": "one",
        "ship_inv_id": "ship-inv", "started_at": 9999999999.0, "duration": 90.0,
        "kills": 0, "inputs": 0, "last_heartbeat": 0.0, "completed": False,
    }
    calls = []

    async def invoke(function, _user, **args):
        calls.append((function, args))
        return {"score": 10}

    monkeypatch.setattr(adapter, "_invoke", invoke)
    await adapter.submit_action(user, "fire")

    assert calls[0][0] == "runHeartbeat"
    assert calls[0][1]["shots"] == 1
    assert calls[0][1]["hits"] == 1
    assert calls[0][1]["accuracy"] == 1.0
