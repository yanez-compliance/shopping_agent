"""Agent side of Yanez Pulse: ask the customer to approve terms in the YID app."""

import asyncio
from typing import Callable

import httpx
from yanez_authz import AuthorizationClient, AuthorizationResult

DECISION_WINDOW_SECONDS = 300


class PulseApprover:
    def __init__(self, base_url: str, agent_api_key: str,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url
        self._agent_api_key = agent_api_key  # from configuration only, never from the model
        self._transport = transport

    def request(self, terms: dict, on_sent: Callable[[str], None]) -> AuthorizationResult:
        """Send the terms to the YID app and wait for approved, rejected, or expired.

        Raises TimeoutError if no decision arrives a little after the decision window.
        """
        return asyncio.run(self._request(terms, on_sent))

    async def _request(self, terms: dict, on_sent: Callable[[str], None]) -> AuthorizationResult:
        async with AuthorizationClient(
            self.base_url, self._agent_api_key, transport=self._transport
        ) as client:
            pending = await client.request_authorization(
                terms, decision_window_seconds=DECISION_WINDOW_SECONDS
            )
            on_sent(pending.request_id)
            return await client.wait_for_authorization(
                pending.request_id, DECISION_WINDOW_SECONDS + 30
            )
