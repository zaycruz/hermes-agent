"""Tests for Discord A2A broker enforcement."""

from types import SimpleNamespace

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.discord import DiscordAdapter


class FakeTextChannel:
    def __init__(self, channel_id: int = 111):
        self.id = channel_id
        self.parent_id = None


def _adapter(monkeypatch):
    monkeypatch.setenv("A2A_DISCORD_ENABLED", "true")
    monkeypatch.setenv("A2A_DISCORD_CHANNEL_ID", "111")
    monkeypatch.setenv("A2A_DISCORD_PEER_USER_ID", "222")
    monkeypatch.setenv("A2A_DISCORD_MAX_TURNS", "4")
    adapter = DiscordAdapter(PlatformConfig(enabled=True, token="fake-token"))
    adapter._client = SimpleNamespace(user=SimpleNamespace(id=999))
    return adapter


def _message(content: str, *, author_id: int = 222, channel_id: int = 111, mentions_self: bool = True, msg_id: int = 1):
    self_user = SimpleNamespace(id=999)
    return SimpleNamespace(
        id=msg_id,
        content=content,
        mentions=[self_user] if mentions_self else [],
        channel=FakeTextChannel(channel_id),
        author=SimpleNamespace(id=author_id, bot=True),
    )


def test_a2a_allows_peer_start_message(monkeypatch):
    adapter = _adapter(monkeypatch)
    adapter._client.user = _message("x").mentions[0]

    allowed = adapter._a2a_allows_bot_message(
        _message("<@999> a2a:start diagnose envoy routing", msg_id=10)
    )

    assert allowed is True


def test_a2a_terminal_marker_closes_without_model_dispatch(monkeypatch):
    adapter = _adapter(monkeypatch)
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


@pytest.mark.parametrize("content", ["noted", "copy", ".", "✅", "standing by"])
def test_a2a_ack_only_messages_close_without_dispatch(monkeypatch, content):
    adapter = _adapter(monkeypatch)
    adapter._client.user = _message("x").mentions[0]
    assert adapter._a2a_allows_bot_message(
        _message("<@999> a2a:start diagnose envoy routing", msg_id=10)
    )

    assert adapter._a2a_allows_bot_message(_message(content, msg_id=11)) is False
    assert adapter._a2a_allows_bot_message(
        _message("<@999> continue after ack", msg_id=12)
    ) is False


def test_a2a_rejects_non_peer_and_missing_mention(monkeypatch):
    adapter = _adapter(monkeypatch)
    adapter._client.user = _message("x").mentions[0]

    assert adapter._a2a_allows_bot_message(
        _message("<@999> a2a:start from stranger", author_id=333)
    ) is False
    assert adapter._a2a_allows_bot_message(
        _message("a2a:start no mention", mentions_self=False)
    ) is False


def test_a2a_requires_start_marker_for_idle_thread(monkeypatch):
    adapter = _adapter(monkeypatch)
    adapter._client.user = _message("x").mentions[0]

    assert adapter._a2a_allows_bot_message(
        _message("<@999> can you check this without a start marker?")
    ) is False
