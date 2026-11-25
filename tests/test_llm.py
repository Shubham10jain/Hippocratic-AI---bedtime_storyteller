"""ClaudeClient against a fake SDK client: stop-reason handling, parse retry, usage reporting."""

from types import SimpleNamespace

import pytest

from storyteller.llm import ClaudeClient, LLMError, MissingAPIKeyError, RefusalError


def response(stop_reason="end_turn", text="hello", parsed=None):
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed,
                           content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=text)],
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5))


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.kwargs = []

    def create(self, **kw):
        self.kwargs.append(kw)
        return self.replies.pop(0)

    parse = create


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def make(replies, on_usage=None):
        c = ClaudeClient(on_usage=on_usage)
        c._client = SimpleNamespace(messages=FakeMessages(replies))
        return c

    return make


def test_missing_key_fails_fast(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "  ")
    with pytest.raises(MissingAPIKeyError):
        ClaudeClient()


def test_text_returns_only_text_blocks_and_reports_usage(client):
    seen = []
    c = client([response(text="  a story ")], on_usage=seen.append)
    assert c.text("storyteller", "sys", "user") == "a story"
    assert seen[0]["role"] == "storyteller" and seen[0]["output_tokens"] == 5


def test_refusal_raises_refusal_error(client):
    with pytest.raises(RefusalError):
        client([response(stop_reason="refusal")]).text("storyteller", "sys", "user")


def test_truncation_raises(client):
    with pytest.raises(LLMError, match="ran out of room"):
        client([response(stop_reason="max_tokens")]).text("storyteller", "sys", "user")


def test_parse_retries_once_then_succeeds(client):
    c = client([response(parsed=None), response(parsed="ok")])
    assert c.parse("intake", "sys", "user", schema=object) == "ok"


def test_parse_gives_up_after_two_misses(client):
    with pytest.raises(LLMError, match="couldn't understand"):
        client([response(parsed=None), response(parsed=None)]).parse("intake", "sys", "user", schema=object)


def test_empty_system_prompt_is_not_sent(client):
    c = client([response()])
    c.text("baseline", "", "user")
    assert "system" not in c._client.messages.kwargs[0]
    assert "temperature" not in c._client.messages.kwargs[0]
