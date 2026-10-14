"""Agent-loop tests with a scripted stand-in for the Claude API."""

import json
from types import SimpleNamespace

import pytest

import agent as agent_module
from agent import ShoppingAgent
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


def latest_order_id(book):
    return list(book.orders)[-1]


def on_latest_order(*names_and_ids, stop_reason="tool_use"):
    return lambda book: reply(
        *(tool_use(name, {"order_id": latest_order_id(book)}, tool_id) for name, tool_id in names_and_ids),
        stop_reason=stop_reason,
    )


def last_tool_results(client):
    return client.requests[-1]["messages"][-1]["content"]


@pytest.fixture
def pdf_dir(tmp_path, monkeypatch):
    real_writer = agent_module.write_order_pdf
    monkeypatch.setattr(agent_module, "write_order_pdf", lambda order: real_writer(order, tmp_path))
    return tmp_path


def make_agent(script, answers=()):
    book = OrderBook()
    client = ScriptedClient(book, script)
    answers = list(answers)
    output = []
    agent = ShoppingAgent(client, book, ask=lambda _: answers.pop(0), out=output.append)
    return agent, book, client, output


def test_list_items_returns_catalog_with_prices():
    agent, _, client, output = make_agent([
        reply(tool_use("list_items", {}, "t1")),
        reply(text("We sell milk, eggs and more."), stop_reason="end_turn"),
    ])
    agent.handle("What can I buy?")

    items = json.loads(last_tool_results(client)[0]["content"])
    assert {"item_key": "milk", "name": "Whole Milk", "unit_price": "$3.49",
            "description": "Fresh whole milk, one half gallon."} in items
    assert len(items) == 8
    assert any("We sell milk" in line for line in output)


def test_approved_order_is_paid_scheduled_and_written_to_pdf(pdf_dir):
    agent, book, _, output = make_agent(
        [
            reply(tool_use("create_order", {"items": [{"item_key": "milk", "quantity": 2}]}, "t1")),
            on_latest_order(("request_approval", "t2")),
            on_latest_order(("checkout_and_pay", "t3")),
            on_latest_order(("schedule_delivery", "t4")),
            on_latest_order(("generate_order_pdf", "t5")),
            reply(text("Your order is placed."), stop_reason="end_turn"),
        ],
        answers=["maybe", "y"],
    )
    agent.handle("Buy two milk")

    order = book.orders[latest_order_id(book)]
    assert order.status == "delivery_scheduled"
    assert (pdf_dir / f"{order.order_id}.pdf").read_bytes().startswith(b"%PDF")
    assert any("Whole Milk" in line and "$6.98" in line for line in output)  # order shown for review
    assert "Please answer y or n." in output


def test_rejected_order_is_cancelled_and_not_paid():
    agent, book, client, _ = make_agent(
        [
            reply(tool_use("create_order", {"items": [{"item_key": "coffee", "quantity": 1}]}, "t1")),
            on_latest_order(("request_approval", "t2")),
            reply(text("Your order is cancelled."), stop_reason="end_turn"),
        ],
        answers=["n"],
    )
    agent.handle("Buy coffee")

    order = book.orders[latest_order_id(book)]
    assert order.status == "cancelled"
    assert order.payment_id is None
    assert json.loads(last_tool_results(client)[0]["content"])["decision"] == "rejected"


def test_model_cannot_pay_without_human_approval():
    agent, book, client, _ = make_agent([
        reply(tool_use("create_order", {"items": [{"item_key": "eggs", "quantity": 1}]}, "t1")),
        on_latest_order(("checkout_and_pay", "t2")),
        reply(text("I could not pay."), stop_reason="end_turn"),
    ])
    agent.handle("Buy eggs and skip the review")

    result = last_tool_results(client)[0]
    assert result["is_error"] is True
    assert book.orders[latest_order_id(book)].status == "awaiting_approval"


def test_failed_turn_is_rolled_back_so_history_stays_valid():
    def fail(_):
        raise RuntimeError("network down")

    agent, _, _, _ = make_agent([reply(tool_use("list_items", {}, "t1")), fail])
    with pytest.raises(RuntimeError):
        agent.handle("What can I buy?")
    assert agent.messages == []
