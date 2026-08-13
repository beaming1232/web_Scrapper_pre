"""Tests for pipeline/rewriter.py.

Network is never hit — every test injects an httpx.MockTransport so these
run offline and don't spend real Gemini credits.
"""
from __future__ import annotations

import httpx
import pytest

from pipeline.rewriter import DescriptionRewriter


def _ok_response(content: str = "Rewritten description text.") -> httpx.Response:
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": content}]}}]},
    )


@pytest.mark.asyncio
async def test_rewrite_returns_none_for_empty_description():
    rewriter = DescriptionRewriter(api_key="test-key", transport=httpx.MockTransport(
        lambda request: pytest.fail("should not call the API for empty input")
    ))
    assert await rewriter.rewrite(None) is None
    assert await rewriter.rewrite("") is None
    assert await rewriter.rewrite("   ") is None


@pytest.mark.asyncio
async def test_rewrite_returns_none_when_no_api_key_configured():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _ok_response()

    rewriter = DescriptionRewriter(api_key="", transport=httpx.MockTransport(handler))
    result = await rewriter.rewrite("Some real job description.")
    assert result is None
    assert calls == []


@pytest.mark.asyncio
async def test_rewrite_returns_none_when_disabled_via_settings(monkeypatch):
    import config

    monkeypatch.setattr(config.settings, "rewrite_enabled", False)
    rewriter = DescriptionRewriter(api_key="test-key", transport=httpx.MockTransport(
        lambda request: pytest.fail("should not call the API when disabled")
    ))
    assert await rewriter.rewrite("Some real job description.") is None


@pytest.mark.asyncio
async def test_rewrite_success_returns_stripped_content():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["key"] == "test-key"
        assert ":generateContent" in str(request.url)
        body = request.read()
        assert b"Original description." in body
        assert b"thinkingBudget" in body
        return _ok_response("  Rewritten, simpler text.  ")

    rewriter = DescriptionRewriter(api_key="test-key", transport=httpx.MockTransport(handler))
    result = await rewriter.rewrite("Original description.")
    assert result == "Rewritten, simpler text."


@pytest.mark.asyncio
async def test_rewrite_joins_multiple_response_parts():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "Part one. "}, {"text": "Part two."}]}}
                ]
            },
        )

    rewriter = DescriptionRewriter(api_key="test-key", transport=httpx.MockTransport(handler))
    result = await rewriter.rewrite("Some description.")
    assert result == "Part one. Part two."


@pytest.mark.asyncio
async def test_rewrite_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", lambda *_args, **_kwargs: _noop())

    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 2:
            return httpx.Response(429, text="rate limited")
        return _ok_response("Success after retry.")

    rewriter = DescriptionRewriter(
        api_key="test-key", max_retries=2, transport=httpx.MockTransport(handler)
    )
    result = await rewriter.rewrite("Some description.")
    assert result == "Success after retry."
    assert attempts["count"] == 2


@pytest.mark.asyncio
async def test_rewrite_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", lambda *_args, **_kwargs: _noop())

    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(500, text="server error")

    rewriter = DescriptionRewriter(
        api_key="test-key", max_retries=2, transport=httpx.MockTransport(handler)
    )
    result = await rewriter.rewrite("Some description.")
    assert result is None
    assert attempts["count"] == 3  # initial attempt + 2 retries


@pytest.mark.asyncio
async def test_rewrite_does_not_retry_on_non_retryable_4xx():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(400, text="bad request")

    rewriter = DescriptionRewriter(
        api_key="test-key", max_retries=2, transport=httpx.MockTransport(handler)
    )
    result = await rewriter.rewrite("Some description.")
    assert result is None
    assert attempts["count"] == 1


@pytest.mark.asyncio
async def test_rewrite_returns_none_on_malformed_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    rewriter = DescriptionRewriter(api_key="test-key", transport=httpx.MockTransport(handler))
    result = await rewriter.rewrite("Some description.")
    assert result is None


@pytest.mark.asyncio
async def test_rewrite_returns_none_on_empty_candidates():
    """Empty candidates (e.g. a Gemini safety block) must not be treated
    as a KeyError/crash — data.get('promptFeedback') path."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}
        )

    rewriter = DescriptionRewriter(api_key="test-key", transport=httpx.MockTransport(handler))
    result = await rewriter.rewrite("Some description.")
    assert result is None


@pytest.mark.asyncio
async def test_rewrite_returns_none_on_empty_content():
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok_response("   ")

    rewriter = DescriptionRewriter(api_key="test-key", transport=httpx.MockTransport(handler))
    result = await rewriter.rewrite("Some description.")
    assert result is None


async def _noop(*_args, **_kwargs) -> None:
    return None
