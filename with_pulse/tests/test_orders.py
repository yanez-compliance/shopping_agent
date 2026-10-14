import pytest

from fake_yanez import FakeYanez, request_id
from order_pdf import write_order_pdf
from orders import OrderBook, OrderError, format_order, order_terms


def test_create_order_prices_lines_and_merges_duplicates():
    book = OrderBook()
    order = book.create([
        {"item_key": "milk", "quantity": 2},
        {"item_key": "coffee", "quantity": 1},
        {"item_key": "milk", "quantity": 1},
    ])
    assert [(line.item_key, line.quantity) for line in order.lines] == [("milk", 3), ("coffee", 1)]
    assert order.total_cents == 3 * 349 + 699
    assert order.status == "awaiting_approval"
    assert "$17.46" in format_order(order)


@pytest.mark.parametrize("items", [
    [],
    [{"item_key": "caviar", "quantity": 1}],
    [{"item_key": "milk", "quantity": 0}],
    [{"item_key": "milk", "quantity": 100}],
    [{"item_key": "milk", "quantity": True}],
])
def test_create_order_rejects_invalid_requests(items):
    with pytest.raises(OrderError):
        OrderBook().create(items)


def test_order_terms_follow_the_pulse_shape():
    order = OrderBook().create([{"item_key": "milk", "quantity": 2}, {"item_key": "bread", "quantity": 1}])
    terms = order_terms(order)

    assert terms["schema_version"] == 1
    for field in ("action", "approval_title", "summary", "merchant"):
        assert isinstance(terms[field], str) and terms[field].strip()
    assert terms["currency"] == "USD"
    assert terms["amount"] == {"minor_units": 2 * 349 + 329, "currency": "USD"}
    assert "$10.27" in terms["summary"]
    for row in terms["details"]:
        assert row["label"].strip() and row["value"].strip()
        assert isinstance(row["emphasized"], bool)
    assert {"label": "Order", "value": order.order_id, "emphasized": False} in terms["details"]
    assert terms["details"][-1] == {"label": "Amount", "value": "$10.27", "emphasized": True}
    assert order_terms(order) == terms  # rebuilt identically at checkout


def test_cannot_ship_unpaid_or_approve_cancelled_order():
    book = OrderBook()
    order = book.create([{"item_key": "eggs", "quantity": 1}])
    with pytest.raises(OrderError):
        book.schedule_delivery(order.order_id)
    book.cancel(order.order_id)
    with pytest.raises(OrderError):
        book.approve(order.order_id, request_id(), "receipt")


def test_pay_requires_receipt_for_this_order():
    yanez, book = FakeYanez(), OrderBook()
    first = book.create([{"item_key": "eggs", "quantity": 1}])
    second = book.create([{"item_key": "eggs", "quantity": 1}])
    jti = request_id()
    artifact = yanez.receipt(order_terms(first), jti)
    book.approve(first.order_id, jti, artifact)
    book.approve(second.order_id, request_id(), "unused")
    receipt = yanez.verifier().verify(artifact, order_terms(first), 900)
    with pytest.raises(OrderError, match="not for order"):
        book.pay(second.order_id, receipt)


def test_full_lifecycle_writes_pdf(tmp_path):
    yanez, book = FakeYanez(), OrderBook()
    order = book.create([{"item_key": "bread", "quantity": 2}])
    jti = request_id()
    artifact = yanez.receipt(order_terms(order), jti)
    book.approve(order.order_id, jti, artifact)
    book.pay(order.order_id, yanez.verifier().verify(artifact, order_terms(order), 900))
    book.schedule_delivery(order.order_id)
    assert order.status == "delivery_scheduled"

    path = write_order_pdf(order, tmp_path)
    pdf = path.read_bytes()
    assert pdf.startswith(b"%PDF")
    assert artifact.encode() not in pdf
