"""Command-line shopping agent for the workshop, with approval through Yanez Pulse.

Run:  .venv/bin/python agent.py
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

import anthropic
from dotenv import load_dotenv
from yanez_authz import ReceiptVerifier, YanezAuthzError

from approval import DECISION_WINDOW_SECONDS, PulseApprover
from catalog import CATALOG, money
from merchant import Merchant
from order_pdf import write_order_pdf
from orders import OrderBook, OrderError, format_order, order_terms

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """\
You are the shopping agent for Yanez Mart, a small grocery store, helping one customer in a terminal.

The customer asks for one of two things:
1. What is available. Call list_items and show every item with its unit price.
2. To buy items. Map each request to catalog items (call list_items first if you have not), then call \
create_order. Use quantity 1 unless the customer gives one. If something they asked for is not sold here, \
say so; if nothing matches, do not create an order. Then call request_approval, which sends the order to \
the customer's YID app and waits while they approve or reject it there with a face scan. Don't ask for \
approval in chat.
   - Approved: call checkout_and_pay, then schedule_delivery, then generate_order_pdf. Then confirm the \
order with its total, delivery date and the PDF path.
   - Rejected, expired, or no answer: tell the customer the order is cancelled and ask what they would \
like to do next.
   - If checkout refuses the approval, explain why and do not try to pay another way.

Payment and delivery are simulated for this demo. Keep replies short. Write plain text, because the \
terminal does not render Markdown."""

_ORDER_ID_SCHEMA = {
    "type": "object",
    "properties": {"order_id": {"type": "string", "description": "Order ID returned by create_order."}},
    "required": ["order_id"],
    "additionalProperties": False,
}


def _tool(name: str, description: str, schema: dict) -> dict:
    return {"name": name, "description": description, "input_schema": schema, "strict": True}


TOOLS = [
    _tool(
        "list_items",
        "List every item in the Yanez Mart catalog with its key, name, unit price and description.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    _tool(
        "create_order",
        "Create a draft order from catalog items and return it with line totals and the order total. "
        "The order cannot be paid until the customer approves it through request_approval.",
        {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_key": {"type": "string", "enum": list(CATALOG)},
                            "quantity": {"type": "integer", "description": "Number of units, 1 to 99."},
                        },
                        "required": ["item_key", "quantity"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["items"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "request_approval",
        "Send the draft order to the customer's YID app through Yanez Pulse and wait up to "
        f"{DECISION_WINDOW_SECONDS // 60} minutes for them to approve or reject it. Returns the decision.",
        _ORDER_ID_SCHEMA,
    ),
    _tool(
        "checkout_and_pay",
        "Check out and pay for an approved order (simulated payment). The merchant verifies the "
        "customer's signed approval first and refuses payment if it does not check out.",
        _ORDER_ID_SCHEMA,
    ),
    _tool("schedule_delivery", "Schedule delivery for a paid order (simulated shipping).", _ORDER_ID_SCHEMA),
    _tool(
        "generate_order_pdf",
        "Write the completed order to a PDF file and return its path. Needs a scheduled delivery.",
        _ORDER_ID_SCHEMA,
    ),
]


class ShoppingAgent:
    def __init__(
        self,
        client: anthropic.Anthropic,
        book: OrderBook,
        approver: PulseApprover,
        merchant: Merchant,
        out: Callable[[str], None] = print,
    ) -> None:
        self.client = client
        self.book = book
        self.approver = approver
        self.merchant = merchant
        self.out = out
        self.messages: list[dict[str, Any]] = []

    def handle(self, user_text: str) -> None:
        """Run one customer turn: call Claude and its tools until it replies in text."""
        start = len(self.messages)
        self.messages.append({"role": "user", "content": user_text})
        try:
            while True:
                response = self.client.beta.messages.create(
                    model=MODEL,
                    max_tokens=16000,
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
                    messages=self.messages,
                    output_config={"effort": "medium"},
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
                if response.stop_reason == "refusal":
                    del self.messages[start:]
                    self.out("\nAgent: Sorry, I can't help with that request.\n")
                    return
                self.messages.append({"role": "assistant", "content": response.content})
                text = "".join(block.text for block in response.content if block.type == "text").strip()
                if text:
                    self.out(f"\nAgent: {text}\n")
                if response.stop_reason != "tool_use":
                    if response.stop_reason == "max_tokens":
                        self.out("(The reply was cut off.)")
                    return
                results = [
                    self._tool_result(block) for block in response.content if block.type == "tool_use"
                ]
                self.messages.append({"role": "user", "content": results})
        except BaseException:
            # Keep the history valid (every tool_use answered) if the turn fails part-way.
            del self.messages[start:]
            raise

    def _tool_result(self, block: Any) -> dict[str, Any]:
        self.out(f"  -> {block.name}({json.dumps(block.input) if block.input else ''})")
        try:
            content, is_error = self.run_tool(block.name, block.input), False
        except OrderError as exc:
            content, is_error = f"Error: {exc}", True
        return {"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error}

    def run_tool(self, name: str, args: dict[str, Any]) -> str:
        if name == "list_items":
            return json.dumps([
                {
                    "item_key": item.key,
                    "name": item.name,
                    "unit_price": money(item.unit_price_cents),
                    "description": item.description,
                }
                for item in CATALOG.values()
            ])
        if name == "create_order":
            return json.dumps(self.book.create(args["items"]).summary())

        order = self.book.get(args["order_id"])
        if name == "request_approval":
            if order.status != "awaiting_approval":
                raise OrderError(f"Order {order.order_id} is '{order.status}' and cannot be reviewed again.")
            return json.dumps(self._request_approval(order.order_id))
        if name == "checkout_and_pay":
            return json.dumps(self.merchant.checkout(order.order_id).summary())
        if name == "schedule_delivery":
            return json.dumps(self.book.schedule_delivery(order.order_id).summary())
        if name == "generate_order_pdf":
            if order.status != "delivery_scheduled":
                raise OrderError(f"Order {order.order_id} is '{order.status}'; schedule delivery first.")
            order.pdf_path = str(write_order_pdf(order))
            return json.dumps({"order_id": order.order_id, "pdf_path": order.pdf_path})
        raise OrderError(f"Unknown tool '{name}'.")

    def _request_approval(self, order_id: str) -> dict[str, Any]:
        order = self.book.get(order_id)
        self.out("\n" + format_order(order) + "\n")

        def on_sent(request_id: str) -> None:
            self.out(
                f"Sent to your YID app (request {request_id}). Approve or reject it there; "
                f"waiting up to {DECISION_WINDOW_SECONDS // 60} minutes...\n"
            )

        try:
            result = self.approver.request(order_terms(order), on_sent)
        except TimeoutError:
            self.book.cancel(order_id)
            return {"order_id": order_id, "decision": "no_answer", "status": "cancelled"}
        except YanezAuthzError as exc:
            raise OrderError(f"Could not send the approval request to Yanez Pulse: {type(exc).__name__}: {exc}")

        if result.status == "approved" and result.artifact:
            self.book.approve(order_id, result.request_id, result.artifact)
            self.out("Approved in the YID app.")
            return {"order_id": order_id, "decision": "approved", "approval_request_id": result.request_id}
        self.book.cancel(order_id)
        self.out(f"Not approved ({result.status}).")
        return {"order_id": order_id, "decision": result.status, "status": "cancelled"}


def _required(name: str, hint: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"Set {name} in with_pulse/.env ({hint}).")
    return value


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    _required("ANTHROPIC_API_KEY", "your Claude API key")
    agent_key = _required("YANEZ_AGENT_API_KEY", "the yak_ agent key created in the YID app")
    if not agent_key.startswith("yak_"):
        sys.exit("YANEZ_AGENT_API_KEY must be a yak_ agent key created in the YID app.")
    base_url = _required("YANEZ_BASE_URL", "for example https://ptest.yanez.ai")
    issuer = _required("YANEZ_EXPECTED_ISSUER", "the receipt issuer for that environment")
    expected_yid = _required("YANEZ_EXPECTED_YID", "your YID, shown in the YID app under Settings").lower()

    # Keys that are not scoped to a workspace must name one on every request.
    workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
    client = anthropic.Anthropic(
        default_headers={"anthropic-workspace-id": workspace_id} if workspace_id else None
    )
    book = OrderBook()
    agent = ShoppingAgent(
        client,
        book,
        PulseApprover(base_url, agent_key),
        Merchant(book, ReceiptVerifier(base_url, issuer), expected_yid),
    )
    print("Yanez Mart shopping agent. Ask what is available, or tell me what to buy. Type 'quit' to exit.\n")
    while True:
        try:
            text = input("You: ").strip()
            if not text:
                continue
            if text.lower() in ("quit", "exit"):
                break
            agent.handle(text)
        except (EOFError, KeyboardInterrupt):
            print()
            break
        except anthropic.AuthenticationError:
            print("Error: Claude API credentials are missing or invalid. Set ANTHROPIC_API_KEY and try again.")
            break
        except anthropic.RateLimitError:
            print("Error: rate limited by the Claude API. Wait a moment and try again.")
        except anthropic.APIConnectionError:
            print("Error: could not reach the Claude API. Check your network and try again.")
        except anthropic.APIStatusError as exc:
            print(f"Error: Claude API returned {exc.status_code}: {exc.message}")
    print("Goodbye.")


if __name__ == "__main__":
    main()
