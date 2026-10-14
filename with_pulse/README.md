# Shopping agent with Yanez Pulse

This is the second version of the workshop shopping agent. It works like the
[initial version](../initial/README.md), with one change: you approve the order in the
**YID app**, not with `y` or `n` in the terminal.

Yanez Pulse is the Yanez service that lets an AI agent ask a person to approve an exact
action. The person approves in the YID app with a face scan and signs the decision with
their own key. The approval produces a **receipt** signed twice, once by Yanez and once by
the approver. The merchant checks that receipt before it takes payment.

The build request is in [prompt.md](prompt.md). Payment and delivery are still fake.

## What happens when you buy something

1. Claude matches your request to the catalog and creates a draft order.
2. The agent prints the order in the terminal and sends the same order to your YID app
   through Pulse. It then waits up to 5 minutes.
3. You approve or reject in the YID app.
4. If you reject, or nobody answers in time, the order is cancelled.
5. If you approve, the agent asks the merchant to check out. The merchant checks the
   receipt before paying (details below).
6. After payment, the agent schedules the fake delivery and writes the order PDF to
   `orders/<order id>.pdf`. The PDF records who approved and the approval request ID.

## Who checks what

There are three roles in this demo, all in one process:

- **The agent** (Claude plus the tool loop, in `agent.py`) can't pay. It can only ask for
  approval and carry the receipt.
- **The Pulse client**, the agent's side (`approval.py`), can't pay. It sends the terms and
  waits for the decision.
- **The merchant checkout**, called the "relying party" because it relies on the receipt
  (`merchant.py`), can pay, but only after the receipt passes every check.

At checkout, `merchant.py` calls the SDK's `authorize_action`, which:

- verifies Yanez's signature and the approver's own signature
- compares the signed terms with terms the merchant rebuilds from its own order record.
  If the basket changed after approval, checkout is refused.
- checks the approver is the YID in `YANEZ_EXPECTED_YID`
- refuses approvals older than 15 minutes
- refuses approvals below the **medium** assurance tier, which is the strength of the
  face scan the app reports
- consumes the receipt with Yanez, so the same approval can't be used twice

The receipt never goes to Claude, the logs, or the PDF. Anyone holding a receipt could
try to spend it.

## Setup

You need Python 3.11 or newer, a Claude API key, and the YID app on your phone.

If you don't have a YID yet, get the YID app and register:

1. Open https://pulse.yanez.ai on a computer and scan the QR code with your phone's camera.
2. If the YID app isn't installed, install it from the
   [App Store](https://apps.apple.com/app/yanezyid/id6784028862) (iPhone) or
   [Google Play](https://play.google.com/store/apps/details?id=ai.yanez.yid) (Android).
3. Scan the QR code again. This registers you with the Yanez YID registry.

Then, in the YID app:

1. Find your YID under **Settings**.
2. Create an agent key. It starts with `yak_`. According to the Pulse docs, the key can only
   ask for approval, not approve or act.

Then:

```zsh
cd with_pulse
python3 -m venv .venv
.venv/bin/pip install --pre -r requirements.txt
cp .env.example .env
```

Fill in `.env`:

- `ANTHROPIC_API_KEY`: your Claude API key
- `ANTHROPIC_WORKSPACE_ID`: only if your Claude key is not scoped to a workspace
- `YANEZ_AGENT_API_KEY`: the `yak_` agent key from the YID app
- `YANEZ_BASE_URL`: `https://ptest.yanez.ai` for Test, `https://yid.yanez.ai` for Production
- `YANEZ_EXPECTED_ISSUER`: the receipt issuer. Today it is the same as the base URL.
- `YANEZ_EXPECTED_YID`: your YID. Checkout accepts approvals only from it.

Use the YID app build that matches the environment you picked.

## Run

```zsh
.venv/bin/python agent.py
```

```text
You: buy 2 milk and a coffee
  -> create_order(...)
  -> request_approval(...)
Sent to your YID app (request azr_...). Approve or reject it there; waiting up to 5 minutes...
```

Type `quit` or press Ctrl+C to exit.

## Tests

The tests run offline. A fake Yanez mints receipts with real Ed25519 and BLS signatures,
so the real SDK verifier runs unchanged:

```zsh
.venv/bin/python -m pytest
```

They cover the approve, reject, expire and timeout paths. They also cover the checks
that must stop payment: wrong approver, unknown signing key, stale approval, low
assurance tier, basket edited after approval, receipt already spent, and paying without
an approval.

## Files

- `agent.py` holds the system prompt, tools, agent loop and terminal interface
- `approval.py` holds the Pulse request on the agent's side
- `merchant.py` holds the checkout that verifies and consumes the receipt
- `orders.py` holds the order lifecycle and the terms shown in the YID app
- `catalog.py` holds the items and prices, unchanged from `initial`
- `order_pdf.py` renders the PDF
