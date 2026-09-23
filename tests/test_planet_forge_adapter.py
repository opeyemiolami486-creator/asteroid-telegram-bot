import pytest

from bot.game_adapter import PlanetForgeAdapter
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
