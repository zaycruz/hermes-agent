"""Tests for Discord A2A broker enforcement."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gateway.config import PlatformConfig


def _ensure_discord_mock():
    if "discord" in sys.modules and hasattr(sys.modules["discord"], "__file__"):
        return

    discord_mod = MagicMock()
    discord_mod.Intents.default.return_value = MagicMock()
    discord_mod.DMChannel = type("DMChannel", (), {})
    discord_mod.Thread = type("Thread", (), {})
    discord_mod.ForumChannel = type("ForumChannel", (), {})
    discord_mod.Interaction = object
    discord_mod.app_commands = SimpleNamespace(
        describe=lambda **kwargs: (lambda fn: fn),
        choices=lambda **kwargs: (lambda fn: fn),
        Choice=lambda **kwargs: SimpleNamespace(**kwargs),
    )

    ext_mod = MagicMock()
    commands_mod = MagicMock()
    commands_mod.Bot = MagicMock
    ext_mod.commands = commands_mod

    sys.modules.setdefault("discord", discord_mod)
    sys.modules.setdefault("discord.ext", ext_mod)
    sys.modules.setdefault("discord.ext.commands", commands_mod)


# This module sorts ahead of the other Discord test modules, so it must install
# the shared discord stub before importing the adapter; otherwise the real
# discord package lands in sys.modules and the later suites cannot mock it.
_ensure_discord_mock()

from gateway.platforms.discord import DiscordAdapter  # noqa: E402


class FakeTextChannel:
    def __init__(self, channel_id: int = 111):
        self.id = channel_id
        self.parent_id = None


@pytest.fixture
def adapter(monkeypatch, _isolate_hermes_home):
    monkeypatch.setenv("A2A_DISCORD_ENABLED", "true")
    monkeypatch.setenv("A2A_DISCORD_CHANNEL_ID", "111")
    monkeypatch.setenv("A2A_DISCORD_PEER_USER_ID", "222")
    monkeypatch.setenv("A2A_DISCORD_MAX_TURNS", "4")
    adapter = DiscordAdapter(PlatformConfig(enabled=True, token="fake-token"))  # noqa: S106  # nosec B106: test-only token
    adapter._client = SimpleNamespace(user=SimpleNamespace(id=999))
    return adapter


def _message(content: str, *, author_id: int = 222, channel_id: int = 111, mentions_self: bool = True, msg_id: int = 1):
    self_user = SimpleNamespace(id=999)
    if mentions_self and f"<@{self_user.id}>" not in content and f"<@!{self_user.id}>" not in content:
        content = f"<@{self_user.id}> {content}".strip()
    return SimpleNamespace(
        id=msg_id,
        content=content,
        mentions=[self_user] if mentions_self else [],
        channel=FakeTextChannel(channel_id),
        author=SimpleNamespace(id=author_id, bot=True),
    )


def test_a2a_allows_peer_start_message(adapter):
    adapter._client.user = _message("x").mentions[0]

    allowed = adapter._a2a_allows_bot_message(
        _message("<@999> a2a:start diagnose envoy routing", msg_id=10)
    )

    assert allowed is True


def test_a2a_terminal_marker_closes_without_model_dispatch(adapter):
    adapter._client.user = _message("x").mentions[0]
    assert adapter._a2a_allows_bot_message(
        _message("<@999> a2a:start diagnose envoy routing", msg_id=10)
    )

    terminal_allowed = adapter._a2a_allows_bot_message(
        _message("<@999> a2a:done confirmed", msg_id=11)
    )
    followup_allowed = adapter._a2a_allows_bot_message(
        _message("<@999> anything else?", msg_id=12)
    )

    assert terminal_allowed is False
    assert followup_allowed is False
    assert adapter._load_a2a_state()["111"]["state"] == "done"


def test_a2a_stop_marker_records_stopped_state(adapter):
    adapter._client.user = _message("x").mentions[0]
    assert adapter._a2a_allows_bot_message(
        _message("a2a:start diagnose envoy routing", msg_id=10)
    )

    assert adapter._a2a_allows_bot_message(_message("a2a:stop pause here", msg_id=11)) is False

    assert adapter._load_a2a_state()["111"]["state"] == "stopped"


def test_a2a_start_reopens_terminal_conversation(adapter):
    adapter._client.user = _message("x").mentions[0]
    assert adapter._a2a_allows_bot_message(
        _message("a2a:start first pass", msg_id=10)
    )
    assert adapter._a2a_allows_bot_message(_message("a2a:done first pass", msg_id=11)) is False

    assert adapter._a2a_allows_bot_message(_message("a2a:start second pass", msg_id=12)) is True

    record = adapter._load_a2a_state()["111"]
    assert record["state"] == "open"
    assert record["turn_count"] == 1
    assert record["last_message_id"] == "12"


@pytest.mark.parametrize("content", ["noted", "copy", ".", "✅", "standing by"])
def test_a2a_ack_only_messages_close_without_dispatch(adapter, content):
    adapter._client.user = _message("x").mentions[0]
    assert adapter._a2a_allows_bot_message(
        _message("<@999> a2a:start diagnose envoy routing", msg_id=10)
    )

    assert adapter._a2a_allows_bot_message(_message(content, msg_id=11)) is False
    assert adapter._a2a_allows_bot_message(
        _message("<@999> continue after ack", msg_id=12)
    ) is False


def test_a2a_rejects_non_peer_and_missing_mention(adapter):
    adapter._client.user = _message("x").mentions[0]

    assert adapter._a2a_allows_bot_message(
        _message("<@999> a2a:start from stranger", author_id=333)
    ) is False
    assert adapter._a2a_allows_bot_message(
        _message("a2a:start no mention", mentions_self=False)
    ) is False


def test_a2a_requires_start_marker_for_idle_thread(adapter):
    adapter._client.user = _message("x").mentions[0]

    assert adapter._a2a_allows_bot_message(
        _message("<@999> can you check this without a start marker?")
    ) is False
