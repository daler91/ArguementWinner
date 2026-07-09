"""Web adapter: auth, validation, the argue flow against the FakeLLMProvider,
and the usage endpoint — all through a real aiohttp test server."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from argumentwinner.adapters.web.server import MAX_MESSAGE_CHARS, build_web_app, run_web
from argumentwinner.config import Settings
from argumentwinner.container import build_app
from argumentwinner.core.ports import StructuredOutputError

TOKEN = "test-secret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def settings(**kwargs) -> Settings:
    return Settings(_env_file=None, aw_llm_provider="fake", **kwargs)


@pytest.fixture
async def harness():
    app = build_app(settings())
    client = TestClient(TestServer(build_web_app(app, TOKEN)))
    await client.start_server()
    yield client, app
    await client.close()


async def test_page_is_served_without_auth(harness):
    client, _ = harness
    response = await client.get("/")
    assert response.status == 200
    assert response.content_type == "text/html"
    assert "ArgumentWinner" in await response.text()


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
async def test_api_rejects_missing_or_wrong_token(harness, headers):
    client, _ = harness
    argue = await client.post("/api/argue", json={"message": "x"}, headers=headers)
    usage = await client.get("/api/usage", headers=headers)
    assert argue.status == 401
    assert usage.status == 401


async def test_argue_returns_candidates_and_digest(harness):
    client, _ = harness
    response = await client.post(
        "/api/argue", json={"message": "tabs are objectively better"}, headers=AUTH
    )
    assert response.status == 200
    body = await response.json()
    assert body["digest"]
    assert len(body["candidates"]) == 3
    first = body["candidates"][0]
    assert first["text"] and first["persona"] and first["risk"] and first["tactic_note"]


async def test_forced_persona_reaches_the_generation_prompt(harness):
    client, app = harness
    await client.post(
        "/api/argue", json={"message": "you are wrong", "persona": "savage"}, headers=AUTH
    )
    generation = [r for r in app.provider.requests if r.role_hint == "generation"]
    assert generation and "savage" in generation[0].messages[-1].content.lower()


async def test_auto_persona_means_unforced(harness):
    client, _ = harness
    response = await client.post(
        "/api/argue", json={"message": "you are wrong", "persona": "auto"}, headers=AUTH
    )
    assert response.status == 200


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        ({"message": ""}, "required"),
        ({"message": "   "}, "required"),
        ({}, "required"),
        ({"message": "x" * (MAX_MESSAGE_CHARS + 1)}, "too long"),
        ({"message": "x", "persona": "warlock"}, "unknown persona"),
    ],
)
async def test_bad_requests_are_400_with_reason(harness, payload, fragment):
    client, _ = harness
    response = await client.post("/api/argue", json=payload, headers=AUTH)
    assert response.status == 400
    assert fragment in (await response.json())["error"]


async def test_non_json_body_is_400(harness):
    client, _ = harness
    response = await client.post("/api/argue", data=b"not json", headers=AUTH)
    assert response.status == 400


async def test_generation_failure_is_502_not_a_crash(harness):
    client, app = harness
    # First pop degrades the analysis, second makes generation raise.
    app.provider.queue.extend([StructuredOutputError("boom"), StructuredOutputError("boom")])
    response = await client.post("/api/argue", json={"message": "beat this"}, headers=AUTH)
    assert response.status == 502
    assert "generation failed" in (await response.json())["error"]


async def test_usage_endpoint_reports_metered_calls(harness):
    client, _ = harness
    await client.post("/api/argue", json={"message": "meter me"}, headers=AUTH)
    response = await client.get("/api/usage", headers=AUTH)
    assert response.status == 200
    report = (await response.json())["report"]
    assert "fake/fake" in report and "2 call(s)" in report


def test_run_web_without_token_fails_fast():
    with pytest.raises(RuntimeError, match="AW_WEB_TOKEN"):
        run_web(build_app(settings()))
    with pytest.raises(RuntimeError, match="AW_WEB_TOKEN"):
        run_web(build_app(settings(aw_web_token="   ")))
