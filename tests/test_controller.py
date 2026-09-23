from bot.controller import GameController
from bot.models import GameState, UserState, Wallet


def test_placeholder_policy_fires_when_ready():
    assert GameController._choose_action(GameState(cooldown_seconds=0)) == "fire"


def test_placeholder_policy_waits_during_cooldown():
    assert GameController._choose_action(GameState(cooldown_seconds=1)) == "wait"


def test_target_aware_policy_turns_toward_target_then_fires():
    controller = GameController(None, None, None, 1)  # policy-only test
    user = UserState(1, Wallet("address", "key"))
    assert controller._next_action(user, GameState(raw={"targetBearing": 25})) == "rotate_right"
    assert controller._next_action(user, GameState(raw={"targetBearing": -4})) == "fire"
