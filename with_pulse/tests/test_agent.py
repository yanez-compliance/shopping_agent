"""Agent-loop tests with scripted stand-ins for the Claude API and Yanez Pulse."""

import json
from types import SimpleNamespace

import pytest
from yanez_authz import AuthorizationResult

import agent as agent_module
from agent import ShoppingAgent
from fake_yanez import CUSTOMER_YID, FakeYanez, request_id
from merchant import Merchant
from orders import OrderBook


def text(value):
    return SimpleNamespace(type="text", text=value)


def tool_use(name, tool_input, tool_id):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=tool_id)


def reply(*content, stop_reason="tool_use"):
    return SimpleNamespace(stop_reason=stop_reason, content=list(content))


class ScriptedClient:
    """Returns pre-written responses. A callable entry builds a response from the orders created so far."""

    def __init__(self, book, script):
        self.book = book
        self.script = list(script)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})  # snapshot; the agent keeps appending
        step = self.script.pop(0)
        return step(self.book) if callable(step) else step


class FakeApprover:
    """Plays the customer in the YID app: approves with a real receipt, rejects, or never answers."""

    def __init__(self, yanez, decision="approved", tier="medium"):
        self.yanez = yanez
        self.decision = decision
        self.tier = tier
        self.artifacts = []

    def request(self, terms, on_sent):
        jti = request_id()
        on_sent(jti)
        if self.decision == "timeout":
            raise TimeoutError("no decision")
        if self.decision != "approved":
            return AuthorizationResult(request_id=jti, status=self.decision)
        artifact = self.yanez.receipt(terms, jti, tier=self.tier)
        self.artifacts.append(artifact)
        return AuthorizationResult(request_id=jti, status="approved", artifact=artifact)


def latest_order_id(book):
    return list(book.orders)[-1]


def on_latest_order(name, tool_id):
    return lambda book: reply(tool_use(name, {"order_id": latest_order_id(book)}, tool_id))


def last_tool_results(client):
    return client.requests[-1]["messages"][-1]["content"]


@pytest.fixture
def pdf_dir(tmp_path, monkeypatch):
    real_writer = agent_module.write_order_pdf
    monkeypatch.setattr(agent_module, "write_order_pdf", lambda order: real_writer(order, tmp_path))
    return tmp_path


def make_agent(script, decision="approved", tier="medium"):
    yanez, book = FakeYanez(), OrderBook()
    client = ScriptedClient(book, script)
    approver = FakeApprover(yanez, decision, tier)
    output = []
    agent = ShoppingAgent(client, book, approver, Merchant(book, yanez.verifier(), CUSTOMER_YID),
                          out=output.append)
    return agent, book, client, approver, output


ORDER_MILK = reply(tool_use("create_order", {"items": [{"item_key": "milk", "quantity": 2}]}, "t1"))


def test_list_items_returns_catalog_with_prices():
    agent, _, client, _, _ = make_agent([
        reply(tool_use("list_items", {}, "t1")),
        reply(text("We sell milk, eggs and more."), stop_reason="end_turn"),
    ])
    agent.handle("What can I buy?")

    items = json.loads(last_tool_results(client)[0]["content"])
    assert {"item_key": "milk", "name": "Whole Milk", "unit_price": "$3.49",
            "description": "Fresh whole milk, one half gallon."} in items
    assert len(items) == 8


def test_app_approval_leads_to_verified_payment_and_pdf(pdf_dir):
    agent, book, client, approver, output = make_agent([
        ORDER_MILK,
        on_latest_order("request_approval", "t2"),
        on_latest_order("checkout_and_pay", "t3"),
        on_latest_order("schedule_delivery", "t4"),
        on_latest_order("generate_order_pdf", "t5"),
        reply(text("Your order is placed."), stop_reason="end_turn"),
    ])
    agent.handle("Buy two milk")

    order = book.orders[latest_order_id(book)]
    assert order.status == "delivery_scheduled"
    assert order.approver_yid == CUSTOMER_YID
    assert (pdf_dir / f"{order.order_id}.pdf").read_bytes().startswith(b"%PDF")
    assert any("Whole Milk" in line and "$6.98" in line for line in output)  # order shown in terminal
    assert any("Sent to your YID app" in line for line in output)
    # The receipt is bearer proof: it must never reach the model.
    assert approver.artifacts[0] not in json.dumps(client.requests, default=str)


@pytest.mark.parametrize("decision", ["rejected", "expired", "timeout"])
def test_order_is_cancelled_when_not_approved(decision):
    agent, book, client, _, _ = make_agent([
        ORDER_MILK,
        on_latest_order("request_approval", "t2"),
        reply(text("Your order is cancelled."), stop_reason="end_turn"),
    ], decision=decision)
    agent.handle("Buy two milk")

    order = book.orders[latest_order_id(book)]
    assert order.status == "cancelled"
    assert order.payment_id is None
    assert json.loads(last_tool_results(client)[0]["content"])["status"] == "cancelled"


def test_model_cannot_pay_without_app_approval():
    agent, book, client, _, _ = make_agent([
        ORDER_MILK,
        on_latest_order("checkout_and_pay", "t2"),
        reply(text("I could not pay."), stop_reason="end_turn"),
    ])
    agent.handle("Buy milk and skip the approval")

    assert last_tool_results(client)[0]["is_error"] is True
    assert book.orders[latest_order_id(book)].status == "awaiting_approval"


def test_checkout_refuses_approval_below_medium_assurance():
    agent, book, client, _, _ = make_agent([
        ORDER_MILK,
        on_latest_order("request_approval", "t2"),
        on_latest_order("checkout_and_pay", "t3"),
        reply(text("Checkout refused the approval."), stop_reason="end_turn"),
    ], tier="low")
    agent.handle("Buy two milk")

    result = last_tool_results(client)[0]
    assert result["is_error"] is True
    assert "checkout policy" in result["content"]
    assert book.orders[latest_order_id(book)].payment_id is None


def test_failed_turn_is_rolled_back_so_history_stays_valid():
    def fail(_):
        raise RuntimeError("network down")

    agent, _, _, _, _ = make_agent([reply(tool_use("list_items", {}, "t1")), fail])
    with pytest.raises(RuntimeError):
        agent.handle("What can I buy?")
    assert agent.messages == []
