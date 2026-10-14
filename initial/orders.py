"""Orders and their lifecycle. Payment and delivery are fake, for demo use only.

Lifecycle:
    awaiting_approval -> approved -> paid -> delivery_scheduled
    awaiting_approval -> cancelled

Each step checks the current status, so the agent cannot pay for an order
the human has not approved, whatever the model decides to do.
"""

import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from catalog import CATALOG, money

MAX_QUANTITY = 99
DEMO_CUSTOMER = "Workshop Demo Customer"
DEMO_ADDRESS = "123 Demo Street, Sample City, CA 94000"
DELIVERY_WINDOW = "9:00 AM - 12:00 PM"


class OrderError(Exception):
    """An order request or status change that is not allowed."""


@dataclass
class OrderLine:
    item_key: str
    name: str
    unit_price_cents: int
    quantity: int

    @property
    def total_cents(self) -> int:
        return self.unit_price_cents * self.quantity


@dataclass
class Order:
    order_id: str
    lines: list[OrderLine]
    created_at: datetime
    status: str = "awaiting_approval"
    payment_id: str | None = None
    paid_at: datetime | None = None
    delivery_date: date | None = None
    tracking_number: str | None = None
    pdf_path: str | None = None
    customer: str = DEMO_CUSTOMER
    address: str = DEMO_ADDRESS
    delivery_window: str = DELIVERY_WINDOW

    @property
    def total_cents(self) -> int:
        return sum(line.total_cents for line in self.lines)

    def summary(self) -> dict:
        """Order facts returned to the model as a tool result."""
        return {
            "order_id": self.order_id,
            "status": self.status,
            "lines": [
                {
                    "item": line.name,
                    "quantity": line.quantity,
                    "unit_price": money(line.unit_price_cents),
                    "line_total": money(line.total_cents),
                }
                for line in self.lines
            ],
            "total": money(self.total_cents),
            "payment_id": self.payment_id,
            "delivery_date": self.delivery_date.isoformat() if self.delivery_date else None,
            "delivery_window": self.delivery_window if self.delivery_date else None,
            "tracking_number": self.tracking_number,
            "pdf_path": self.pdf_path,
        }


def format_order(order: Order) -> str:
    """Plain-text order shown to the human for review."""
    rows = [
        f"Order {order.order_id}",
        "",
        f"{'Item':<22}{'Qty':>5}{'Unit':>10}{'Total':>10}",
        "-" * 47,
    ]
    for line in order.lines:
        rows.append(
            f"{line.name:<22}{line.quantity:>5}"
            f"{money(line.unit_price_cents):>10}{money(line.total_cents):>10}"
        )
    rows += ["-" * 47, f"{'Order total':<37}{money(order.total_cents):>10}", ""]
    rows.append(f"Deliver to: {order.customer}, {order.address}")
    return "\n".join(rows)


@dataclass
class OrderBook:
    orders: dict[str, Order] = field(default_factory=dict)

    def create(self, items: list[dict]) -> Order:
        if not items:
            raise OrderError("An order needs at least one item.")
        lines: dict[str, OrderLine] = {}
        for entry in items:
            key = str(entry.get("item_key", ""))
            quantity = entry.get("quantity")
            item = CATALOG.get(key)
            if item is None:
                raise OrderError(f"'{key}' is not in the catalog.")
            if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
                raise OrderError(f"Quantity for '{key}' must be a whole number of at least 1.")
            line = lines.setdefault(key, OrderLine(key, item.name, item.unit_price_cents, 0))
            line.quantity += quantity
            if line.quantity > MAX_QUANTITY:
                raise OrderError(f"Quantity for '{key}' cannot exceed {MAX_QUANTITY}.")
        order = Order(
            order_id="ORD-" + secrets.token_hex(4).upper(),
            lines=list(lines.values()),
            created_at=datetime.now(),
        )
        self.orders[order.order_id] = order
        return order

    def get(self, order_id: str) -> Order:
        order = self.orders.get(order_id)
        if order is None:
            raise OrderError(f"Order {order_id} does not exist.")
        return order

    def _transition(self, order_id: str, expected: str, new: str) -> Order:
        order = self.get(order_id)
        if order.status != expected:
            raise OrderError(
                f"Order {order_id} is '{order.status}'; it must be '{expected}' for this step."
            )
        order.status = new
        return order

    def approve(self, order_id: str) -> Order:
        return self._transition(order_id, "awaiting_approval", "approved")

    def cancel(self, order_id: str) -> Order:
        return self._transition(order_id, "awaiting_approval", "cancelled")

    def pay(self, order_id: str) -> Order:
        """Fake payment: no card is charged."""
        order = self._transition(order_id, "approved", "paid")
        order.payment_id = "PAY-" + secrets.token_hex(6).upper()
        order.paid_at = datetime.now()
        return order

    def schedule_delivery(self, order_id: str) -> Order:
        """Fake delivery booking: two days from today, morning window."""
        order = self._transition(order_id, "paid", "delivery_scheduled")
        order.delivery_date = date.today() + timedelta(days=2)
        order.tracking_number = "TRK-" + secrets.token_hex(5).upper()
        return order
