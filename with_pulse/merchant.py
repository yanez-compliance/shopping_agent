"""Merchant checkout: the relying party that turns a Pulse receipt into a payment.

The agent only carries the receipt. Payment happens here, and only after the receipt
passes every check below. The checks follow the Pulse action-enforcement contract.
"""

import secrets

from yanez_authz import (
    AlreadyConsumedError,
    ConsentPolicyError,
    ReceiptVerificationError,
    ReceiptVerifier,
    ReservationHeldError,
    TransportError,
    YanezAuthzError,
)

from orders import Order, OrderBook, OrderError, order_terms

MAX_APPROVAL_AGE_SECONDS = 900
MIN_ASSURANCE_TIER = "medium"


class Merchant:
    def __init__(self, book: OrderBook, verifier: ReceiptVerifier, expected_yid: str) -> None:
        self.book = book
        self.verifier = verifier
        self.expected_yid = expected_yid

    def checkout(self, order_id: str) -> Order:
        order = self.book.get(order_id)
        if order.status == "paid" or order.status == "delivery_scheduled":
            return order  # already checked out; never spend a second approval
        if order.status != "approved" or not order.receipt:
            raise OrderError(f"Order {order_id} has no approval from the YID app.")

        # One token per checkout attempt, kept on the order so a retry after a lost
        # response reuses it. (A real merchant stores it durably before this call.)
        if order.consumer_token is None:
            order.consumer_token = "chk-" + secrets.token_hex(16)

        try:
            receipt = self.verifier.authorize_action(
                order.receipt,
                order_terms(order),  # rebuilt from our own order, not taken from the agent
                max_age_seconds=MAX_APPROVAL_AGE_SECONDS,
                consume=True,
                consumer_token=order.consumer_token,
                expected_sub=self.expected_yid,
                min_assurance_tier=MIN_ASSURANCE_TIER,
            )
        except ReservationHeldError as exc:
            # An earlier attempt of ours consumed the receipt but its response was lost.
            # This demo's payment happens in memory right after consuming, so finish it.
            return self.book.pay(order_id, exc.receipt)
        except AlreadyConsumedError:
            raise OrderError("This approval was already used. Ask the customer to approve again.")
        except ConsentPolicyError as exc:
            raise OrderError(f"The approval does not meet checkout policy: {exc}. Ask the customer to approve again.")
        except ReceiptVerificationError as exc:  # includes UserSignatureError
            raise OrderError(f"The approval receipt failed verification: {exc}. Payment refused.")
        except TransportError:
            raise OrderError("Could not reach Yanez to confirm the approval. Try checkout again.")
        except YanezAuthzError as exc:
            raise OrderError(f"Yanez rejected the checkout check: {exc}")
        return self.book.pay(order_id, receipt)
