"""PulseApprover sends the exact terms with the agent key and returns the decision."""

import json

import httpx
import pytest
from yanez_authz import AuthenticationError

from approval import DECISION_WINDOW_SECONDS, PulseApprover
from fake_yanez import BASE_URL, request_id
from orders import OrderBook, order_terms

AGENT_KEY = "yak_0123456789ab_" + "A" * 43


def pulse_transport(decision: dict, seen: list):
    jti = request_id()

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST" and request.url.path == "/api/agent/authorizations":
            return httpx.Response(201, json={
                "request_id": jti, "status": "pending", "decide_by": "2026-10-13T12:05:00Z"})
        if request.method == "GET" and request.url.path == f"/api/agent/authorizations/{jti}":
            return httpx.Response(200, json={"request_id": jti, **decision})
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler), jti


def test_sends_terms_and_returns_approval():
    terms = order_terms(OrderBook().create([{"item_key": "milk", "quantity": 1}]))
    seen, sent = [], []
    transport, jti = pulse_transport({"status": "approved", "artifact": "a.b.c"}, seen)

    result = PulseApprover(BASE_URL, AGENT_KEY, transport).request(terms, sent.append)

    assert (result.status, result.artifact, result.request_id) == ("approved", "a.b.c", jti)
    assert sent == [jti]
    create = seen[0]
    assert create.headers["Authorization"] == f"Bearer {AGENT_KEY}"
    assert create.headers["Idempotency-Key"]
    body = json.loads(create.content)
    assert body == {"terms": terms, "decision_window_seconds": DECISION_WINDOW_SECONDS}


def test_rejection_is_returned_as_a_value():
    transport, _ = pulse_transport({"status": "rejected"}, [])
    result = PulseApprover(BASE_URL, AGENT_KEY, transport).request({"schema_version": 1}, lambda _: None)
    assert result.status == "rejected"
    assert result.artifact is None


def test_bad_agent_key_raises():
    async def handler(request):
        return httpx.Response(401, json={"detail": "invalid agent key"})

    approver = PulseApprover(BASE_URL, AGENT_KEY, httpx.MockTransport(handler))
    with pytest.raises(AuthenticationError):
        approver.request({"schema_version": 1}, lambda _: None)
