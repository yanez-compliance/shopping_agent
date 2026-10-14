import pytest

from order_pdf import write_order_pdf
from orders import OrderBook, OrderError, format_order


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


def test_cannot_pay_or_ship_before_approval():
    book = OrderBook()
    order = book.create([{"item_key": "eggs", "quantity": 1}])
    with pytest.raises(OrderError):
        book.pay(order.order_id)
    with pytest.raises(OrderError):
        book.schedule_delivery(order.order_id)


def test_cancelled_order_cannot_be_approved_or_paid():
    book = OrderBook()
    order = book.create([{"item_key": "eggs", "quantity": 1}])
    book.cancel(order.order_id)
    with pytest.raises(OrderError):
        book.approve(order.order_id)
    with pytest.raises(OrderError):
        book.pay(order.order_id)


def test_full_lifecycle_writes_pdf(tmp_path):
    book = OrderBook()
    order = book.create([{"item_key": "bread", "quantity": 2}])
    book.approve(order.order_id)
    book.pay(order.order_id)
    book.schedule_delivery(order.order_id)
    assert order.status == "delivery_scheduled"
    assert order.payment_id and order.tracking_number and order.delivery_date

    path = write_order_pdf(order, tmp_path)
    assert path.name == f"{order.order_id}.pdf"
    assert path.read_bytes().startswith(b"%PDF")
