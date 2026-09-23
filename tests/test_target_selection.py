import pytest

from bot.game_adapter import normalize_target


def test_normalize_target_accepts_demo_aliases_and_urls():
    assert normalize_target("demo") == "demo"
    assert normalize_target(" offline ") == "demo"
    assert normalize_target("https://example.test/") == "https://example.test"


@pytest.mark.parametrize(
    "value",
    ["", "example.test", "ftp://example.test", "https://user:pass@example.test"],
)
def test_normalize_target_rejects_unsafe_or_invalid_values(value):
    with pytest.raises(ValueError):
        normalize_target(value)
