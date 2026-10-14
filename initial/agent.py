"""Command-line shopping agent for the workshop.

Run:  .venv/bin/python agent.py
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

import anthropic
from dotenv import load_dotenv

from catalog import CATALOG, money
from order_pdf import write_order_pdf
from orders import OrderBook, OrderError, format_order

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """\
You are the shopping agent for Yanez Mart, a small grocery store, helping one customer in a terminal.

The customer asks for one of two things:
1. What is available. Call list_items and show every item with its unit price.
2. To buy items. Map each request to catalog items (call list_items first if you have not), then call \
create_order. Use quantity 1 unless the customer gives one. If something they asked for is not sold here, \
say so; if nothing matches, do not create an order. Then call request_approval. The customer reviews and \
answers inside that tool, so don't ask for approval in chat.
   - Approved: call checkout_and_pay, then schedule_delivery, then generate_order_pdf. Then confirm the \
order with its total, delivery date and the PDF path.
   - Rejected: tell the customer the order is cancelled and ask what they would like to do next.

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
        "Show the draft order to the customer in the terminal and wait for them to approve or reject it. "
        "Returns the decision.",
        _ORDER_ID_SCHEMA,
    ),
    _tool("checkout_and_pay", "Check out and pay for an approved order (simulated payment).", _ORDER_ID_SCHEMA),
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
        ask: Callable[[str], str] = input,
        out: Callable[[str], None] = print,
    ) -> None:
        self.client = client
        self.book = book
        self.ask = ask
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
            self.out("\n" + format_order(order) + "\n")
            if self._customer_approves():
                self.book.approve(order.order_id)
                return json.dumps({"order_id": order.order_id, "decision": "approved"})
            self.book.cancel(order.order_id)
            return json.dumps({"order_id": order.order_id, "decision": "rejected", "status": "cancelled"})
        if name == "checkout_and_pay":
            return json.dumps(self.book.pay(order.order_id).summary())
        if name == "schedule_delivery":
            return json.dumps(self.book.schedule_delivery(order.order_id).summary())
        if name == "generate_order_pdf":
            if order.status != "delivery_scheduled":
                raise OrderError(f"Order {order.order_id} is '{order.status}'; schedule delivery first.")
            order.pdf_path = str(write_order_pdf(order))
            return json.dumps({"order_id": order.order_id, "pdf_path": order.pdf_path})
        raise OrderError(f"Unknown tool '{name}'.")

    def _customer_approves(self) -> bool:
        while True:
            answer = self.ask("Approve this order? [y/n]: ").strip().lower()
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            self.out("Please answer y or n.")


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY in initial/.env, for example: ANTHROPIC_API_KEY=sk-ant-...")
    # Keys that are not scoped to a workspace must name one on every request.
    workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
    client = anthropic.Anthropic(
        default_headers={"anthropic-workspace-id": workspace_id} if workspace_id else None
    )
    agent = ShoppingAgent(client, OrderBook())
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
