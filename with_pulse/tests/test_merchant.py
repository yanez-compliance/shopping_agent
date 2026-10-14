"""The merchant must pay only for a genuine, matching, fresh, unspent approval."""

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fake_yanez import CUSTOMER_YID, FakeYanez, request_id
from merchant import Merchant
from orders import OrderBook, OrderError, order_terms


@pytest.fixture
def yanez():
    return FakeYanez()


@pytest.fixture
def book():
    return OrderBook()


@pytest.fixture
def merchant(book, yanez):
    return Merchant(book, yanez.verifier(), CUSTOMER_YID)


def approved_order(book, yanez, **receipt_options):
    order = book.create([{"item_key": "milk", "quantity": 2}, {"item_key": "coffee", "quantity": 1}])
    jti = request_id()
    book.approve(order.order_id, jti, yanez.receipt(order_terms(order), jti, **receipt_options))
    return order


def assert_refused(merchant, order, message):
    with pytest.raises(OrderError, match=message):
        merchant.checkout(order.order_id)
    assert order.status == "approved"
    assert order.payment_id is None


def test_valid_approval_is_consumed_and_paid(book, yanez, merchant):
    order = approved_order(book, yanez)
    merchant.checkout(order.order_id)
    assert order.status == "paid"
    assert order.payment_id
    assert order.approver_yid == CUSTOMER_YID
    assert order.assurance_tier == "medium"
    assert yanez.consumed[order.approval_request_id] == order.consumer_token


def test_high_tier_meets_medium_floor(book, yanez, merchant):
    order = approved_order(book, yanez, tier="high")
    merchant.checkout(order.order_id)
    assert order.status == "paid"


def test_low_tier_is_refused(book, yanez, merchant):
    assert_refused(merchant, approved_order(book, yanez, tier="low"), "checkout policy")


def test_approval_by_another_yid_is_refused(book, yanez, merchant):
    assert_refused(merchant, approved_order(book, yanez, yid="f" * 32), "failed verification")


def test_receipt_signed_by_unknown_key_is_refused(book, yanez, merchant):
    order = approved_order(book, yanez, yanez_key=Ed25519PrivateKey.generate())
    assert_refused(merchant, order, "failed verification")


def test_stale_approval_is_refused(book, yanez, merchant):
    assert_refused(merchant, approved_order(book, yanez, age_seconds=1800), "checkout policy")


def test_order_changed_after_approval_is_refused(book, yanez, merchant):
    order = approved_order(book, yanez)
    order.lines[0].quantity = 20  # basket edited after the customer signed
    assert_refused(merchant, order, "failed verification")


def test_receipt_spent_elsewhere_is_refused(book, yanez, merchant):
    order = approved_order(book, yanez)
    yanez.consumed[order.approval_request_id] = "someone-else"
    assert_refused(merchant, order, "already used")


def test_lost_response_is_reconciled_with_same_token(book, yanez, merchant):
    order = approved_order(book, yanez)
    order.consumer_token = "chk-earlier-attempt"
    yanez.consumed[order.approval_request_id] = "chk-earlier-attempt"
    merchant.checkout(order.order_id)
    assert order.status == "paid"


def test_order_without_approval_is_refused(book, merchant):
    order = book.create([{"item_key": "eggs", "quantity": 1}])
    with pytest.raises(OrderError, match="no approval"):
        merchant.checkout(order.order_id)
    assert order.status == "awaiting_approval"


def test_second_checkout_does_not_pay_twice(book, yanez, merchant):
    order = approved_order(book, yanez)
    merchant.checkout(order.order_id)
    payment_id = order.payment_id
    merchant.checkout(order.order_id)
    assert order.payment_id == payment_id
