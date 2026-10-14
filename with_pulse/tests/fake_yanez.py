"""A stand-in for Yanez Pulse that mints real, verifiable receipts for tests.

Receipts carry both signatures the SDK checks: Yanez's Ed25519 JWS and the approver's
BLS signature over the decision envelope. The mock transport serves the public-key and
introspect routes, so the real ReceiptVerifier runs unchanged.
"""

import base64
import json
import secrets
import time

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_ecc.bls.ciphersuites import G2Basic
from yanez_authz import ENVELOPE_ACTION, ENVELOPE_VERSION, USER_SIG_ALG, ReceiptVerifier

BASE_URL = ISSUER = "https://yid.yanez.ai"
CUSTOMER_YID = "0123456789abcdef0123456789abcdef"
KID = "test-key-1"


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def request_id() -> str:
    return "azr_" + secrets.token_hex(16)


class FakeYanez:
    def __init__(self) -> None:
        self.yanez_key = Ed25519PrivateKey.generate()
        self.user_secret = G2Basic.KeyGen(secrets.token_bytes(32))
        self.user_public = G2Basic.SkToPk(self.user_secret)
        self.consumed: dict[str, str] = {}  # jti -> consumer_token that spent it

    def receipt(self, terms: dict, jti: str, *, yid: str = CUSTOMER_YID, tier: str = "medium",
                age_seconds: int = 0, yanez_key: Ed25519PrivateKey | None = None) -> str:
        decided_at = int(time.time()) - age_seconds
        envelope = {
            "action": ENVELOPE_ACTION, "assurance_tier": tier, "authorization_request_id": jti,
            "consent_not_after": None, "decision": "approve", "issuer": ISSUER,
            "signed_at": decided_at, "terms": terms, "version": ENVELOPE_VERSION, "yid": yid,
        }
        signed = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
        claims = {
            "iss": ISSUER, "sub": yid, "jti": jti, "iat": decided_at,
            "yanez_agent_key_id": "yak_0123456789ab", "yanez_decision": "approved",
            "yanez_decided_at": decided_at, "yanez_match_overlap": 5, "yanez_terms": terms,
            "yanez_assurance_tier": tier,
            "yanez_user_public_key": "0x" + self.user_public.hex(),
            "yanez_user_signature": "0x" + G2Basic.Sign(self.user_secret, signed).hex(),
            "yanez_signed_message": b64url(signed),
            "yanez_user_sig_alg": USER_SIG_ALG,
        }
        return jwt.encode(claims, yanez_key or self.yanez_key, algorithm="EdDSA", headers={"kid": KID})

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/authz/public-keys":
            raw = self.yanez_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
            return httpx.Response(200, json={"keys": [
                {"kty": "OKP", "crv": "Ed25519", "alg": "EdDSA", "kid": KID, "x": b64url(raw)}]})
        if request.url.path == "/api/authz/introspect":
            body = json.loads(request.content)
            jti = jwt.decode(body["artifact"], options={"verify_signature": False})["jti"]
            spent_by = self.consumed.get(jti)
            if spent_by is None:
                self.consumed[jti] = body["consumer_token"]
                return httpx.Response(200, json={"valid": True, "consumed_now": True, "jti": jti})
            reason = "reservation_held" if spent_by == body["consumer_token"] else "already_consumed"
            return httpx.Response(200, json={"valid": True, "consumed_now": False, "reason": reason})
        return httpx.Response(404, json={"detail": "not found"})

    def verifier(self) -> ReceiptVerifier:
        return ReceiptVerifier(BASE_URL, ISSUER, transport=httpx.MockTransport(self._handle))
