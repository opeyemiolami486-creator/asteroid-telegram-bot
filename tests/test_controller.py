from bot.controller import GameController
from bot.models import GameState


def test_placeholder_policy_fires_when_ready():
    assert GameController._choose_action(GameState(cooldown_seconds=0)) == "fire"


def test_placeholder_policy_waits_during_cooldown():
    assert GameController._choose_action(GameState(cooldown_seconds=1)) == "wait"
