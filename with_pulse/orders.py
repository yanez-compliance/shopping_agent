"""Orders, their lifecycle, and the Pulse terms the customer approves.

Payment and delivery are fake, for demo use only.

Lifecycle:
    awaiting_approval -> approved -> paid -> delivery_scheduled
    awaiting_approval -> cancelled

"approved" only means Yanez Pulse reported an approval and the agent holds a receipt.
Payment needs a receipt that the merchant has verified and consumed (see merchant.py).
"""

import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from yanez_authz import VerifiedReceipt

from catalog import CATALOG, money

MAX_QUANTITY = 99
MERCHANT = "Yanez Mart"
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
    approval_request_id: str | None = None
    # The signed receipt is bearer proof: it never goes to the model, logs, or the PDF.
    receipt: str | None = field(default=None, repr=False)
    consumer_token: str | None = None
    approver_yid: str | None = None
    assurance_tier: str | None = None
    approved_at: datetime | None = None
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
            "approval_request_id": self.approval_request_id,
            "assurance_tier": self.assurance_tier,
            "payment_id": self.payment_id,
            "delivery_date": self.delivery_date.isoformat() if self.delivery_date else None,
            "delivery_window": self.delivery_window if self.delivery_date else None,
            "tracking_number": self.tracking_number,
            "pdf_path": self.pdf_path,
        }


def order_terms(order: Order) -> dict:
    """The exact terms shown in the YID app and signed by the customer.

    Built only from the order, so the merchant can rebuild the same object at checkout
    and compare it with the signed copy in the receipt.
    """
    return {
        "schema_version": 1,
        "action": "purchase",
        "approval_title": "Approve grocery order",
        "summary": f"Buy {len(order.lines)} grocery item(s) for {money(order.total_cents)} at {MERCHANT}",
        "merchant": MERCHANT,
        "agent_name": "Yanez Mart shopping agent",
        "currency": "USD",
        "amount": {"minor_units": order.total_cents, "currency": "USD"},
        "details": [
            {"label": "Order", "value": order.order_id, "emphasized": False},
            *[
                {
                    "label": f"{line.name} x {line.quantity}",
                    "value": money(line.total_cents),
                    "emphasized": False,
                }
                for line in order.lines
            ],
            {"label": "Deliver to", "value": f"{order.customer}, {order.address}", "emphasized": False},
            {"label": "Amount", "value": money(order.total_cents), "emphasized": True},
        ],
    }


def format_order(order: Order) -> str:
    """Plain-text order shown in the terminal while the customer decides."""
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

    def approve(self, order_id: str, request_id: str, receipt: str) -> Order:
        """Record that Pulse reported an approval. The receipt is checked at checkout."""
        order = self._transition(order_id, "awaiting_approval", "approved")
        order.approval_request_id = request_id
        order.receipt = receipt
        return order

    def cancel(self, order_id: str) -> Order:
        return self._transition(order_id, "awaiting_approval", "cancelled")

    def pay(self, order_id: str, receipt: VerifiedReceipt) -> Order:
        """Fake payment: no card is charged. Needs a receipt the merchant verified."""
        order = self.get(order_id)
        if receipt.jti != order.approval_request_id:
            raise OrderError(f"The verified receipt is not for order {order_id}.")
        order = self._transition(order_id, "approved", "paid")
        order.approver_yid = receipt.sub
        order.assurance_tier = receipt.assurance_tier
        order.approved_at = datetime.fromtimestamp(receipt.decided_at)
        order.payment_id = "PAY-" + secrets.token_hex(6).upper()
        order.paid_at = datetime.now()
        return order

    def schedule_delivery(self, order_id: str) -> Order:
        """Fake delivery booking: two days from today, morning window."""
        order = self._transition(order_id, "paid", "delivery_scheduled")
        order.delivery_date = date.today() + timedelta(days=2)
        order.tracking_number = "TRK-" + secrets.token_hex(5).upper()
        return order
