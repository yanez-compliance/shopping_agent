# Human approval for AI agents: a Yanez Pulse example

This repository is a worked example of how to add **human approval** to an AI agent with
**[Yanez Pulse](https://docs.yanez.ai/pulse/)**, so the agent can't carry out a sensitive
action until a real person has approved it.

The sensitive action here is paying for a grocery order. The same pattern fits any action
you wouldn't want an agent to take on its own, such as a payment, a transfer or a change
to someone's account.

The example is a small shopping agent built twice, so you can compare the two:

1. **`initial/`**: the agent asks you to approve each order by typing `y` or `n` in the
   terminal. This is the starting point.
2. **`with_pulse/`**: the same agent sends the order to the **YID app** on your phone
   through Pulse. You approve it there, and the merchant checks a signed receipt of
   your approval before it takes payment.

Both versions sell the same eight sample groceries. Payment and delivery are simulated:
no card is charged and nothing ships.

## Why a "yes" in the chat isn't enough

In the initial version, approval is a `y` typed into the same program the agent runs in.
The business that carries out the action (here, the merchant) has nothing it can check:

- Anyone at the keyboard can type `y`.
- An agent that is buggy, or that has been manipulated by a malicious prompt, can skip
  the question or report a false answer.
- Nothing proves which order was approved, so a changed basket looks the same as the
  approved one.
- Nothing stops one approval from being used twice.
- Afterwards, there is no evidence of who approved what, and when.

Pulse turns the approval into proof the merchant can verify for itself, instead of a
claim it has to take on trust.

## What Pulse adds

- **Approval on the person's own device.** The order appears in the YID app on your
  phone, and you approve or reject it with a face scan. YID is your Yanez identity.
- **Exact terms.** The app shows the order the merchant will charge for: the items, the
  total, the delivery address and the order ID.
- **A receipt signed twice.** Approving produces a receipt signed by Yanez and also by
  your own key on your phone. The merchant checks both signatures, so it doesn't have to
  trust the agent or rely on Yanez alone.
- **The right person.** The receipt names the approver's YID, and the merchant accepts
  approvals only from the YID in its settings.
- **Scan strength.** The receipt records an assurance tier (`low`, `medium` or `high`)
  that says how strong the face scan was. This merchant requires at least `medium`.
- **Single use.** At checkout the merchant marks the receipt as used ("consumes" it) with
  Yanez, so one approval can't pay twice.
- **Freshness.** The merchant refuses approvals older than 15 minutes.
- **A limited agent key.** According to the Pulse docs, the agent's `yak_` key can only
  ask for approval. It can't approve or act.
- **A record.** The order PDF shows who approved, the approval request ID, when they
  approved and the assurance tier.

## How the integration works

The example has three roles. They run in one process here, but each lives in its own
file, as they would be separate services in a real system:

- **The agent** (`agent.py`, with Claude) builds the order and asks for approval. It has
  no way to pay.
- **The approval request** (`approval.py`) sends the order to the YID app and waits for
  the decision. The receipt it gets back never goes to Claude, the logs or the PDF,
  because anyone holding a receipt could try to spend it.
- **The merchant checkout** (`merchant.py`) is the only code that can take payment. In
  Pulse terms it is the "relying party": the service that relies on the receipt before it
  acts. It rebuilds the expected terms from its own order record, verifies the receipt
  against them, and pays only when every check passes.

An approved purchase goes through these steps:

1. Claude matches your request to the catalog and creates a draft order.
2. The agent turns the order into Pulse "terms" (the exact details you will see in the
   app) and sends them with the `yak_` key. It then waits up to 5 minutes.
3. You approve in the YID app. Pulse returns a signed receipt to the agent.
4. The agent asks the merchant to check out. The merchant verifies and consumes the
   receipt, then takes the simulated payment.
5. The agent schedules the simulated delivery and writes the order PDF.

If you reject, or nobody answers in time, the order is cancelled and nothing is paid.

## Using the pattern in your own agent

These are the pieces to copy. Each one points to where this example does it.

1. **Describe the action as terms.** Build the terms from your own record of the action,
   not from text the model wrote. See `order_terms` in `with_pulse/orders.py`.
2. **Ask for approval with an agent key.** Send the terms with `AuthorizationClient`
   from the Pulse SDK and wait for the decision. See `with_pulse/approval.py`. Load the
   `yak_` key from configuration, never from the model.
3. **Keep the receipt away from the model.** Store it with your record of the action and
   pass only the decision back to the model. See `_request_approval` in
   `with_pulse/agent.py`.
4. **Verify where the action happens.** The service that carries out the action calls
   `ReceiptVerifier.authorize_action` with terms rebuilt from its own record, the
   expected approver, a minimum assurance tier, a maximum age, and `consume=True`. See
   `with_pulse/merchant.py`.
5. **Refuse on any failure.** Treat every verification error as "do not act". The one
   exception is a receipt your own earlier attempt already consumed, where the merchant
   finishes the payment that attempt started. See the error handling in
   `with_pulse/merchant.py`.

The Pulse SDK is the Python package `yanez-agent-authorization` (imported as
`yanez_authz`).

## Try it

You need Python 3.11 or newer and a Claude API key. For the Pulse version you also need
the YID app on your phone.

### Part 1: the initial agent

Create `initial/.env` with your Claude API key:

```
ANTHROPIC_API_KEY=sk-ant-...
# Only if your Claude key is not scoped to a workspace:
ANTHROPIC_WORKSPACE_ID=wrkspc_...
```

A Claude API key "scoped to a workspace" belongs to one workspace in the Claude Console.
If yours isn't, the API asks for the workspace ID on every request. You can find the ID
under Settings, then Workspaces, in the Claude Console.

Then run:

```zsh
cd initial
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python agent.py
```

Lines starting with `->` are the tools the agent calls, printed so you can follow each
step. Claude's replies (lines starting with `Agent:`) are worded differently each time.

```text
Yanez Mart shopping agent. Ask what is available, or tell me what to buy. Type 'quit' to exit.

You: buy 2 milk and a roast chicken
  -> list_items()
  -> create_order({"items": [{"item_key": "milk", "quantity": 2}, {"item_key": "chicken", "quantity": 1}]})
  -> request_approval({"order_id": "ORD-86A07457"})

Order ORD-86A07457

Item                    Qty      Unit     Total
-----------------------------------------------
Whole Milk                2     $3.49     $6.98
Roast Chicken             1     $7.99     $7.99
-----------------------------------------------
Order total                              $14.97

Deliver to: Workshop Demo Customer, 123 Demo Street, Sample City, CA 94000

Approve this order? [y/n]: y
  -> checkout_and_pay({"order_id": "ORD-86A07457"})
  -> schedule_delivery({"order_id": "ORD-86A07457"})
  -> generate_order_pdf({"order_id": "ORD-86A07457"})

Agent: Your order is placed. Total $14.97, delivery on Thursday, October 15 between
9:00 AM and 12:00 PM. Order PDF: initial/orders/ORD-86A07457.pdf
```

If you answer `n`, the agent tells you the order is cancelled and waits for your next
request.

Claude (model `claude-opus-5-5`) decides which of six tools to call: list items, create
order, request approval, check out and pay, schedule delivery, and generate the PDF.
Python code works out every price and total, so the model can't invent amounts. The order
rules are in code too: an order can't be paid until it has been approved, whatever the
model decides.

### Part 2: the agent with Pulse

If you don't have a YID yet, get the YID app and register:

1. Open https://pulse.yanez.ai on a computer and scan the QR code with your phone's camera.
2. If the YID app isn't installed, install it from the
   [App Store](https://apps.apple.com/app/yanezyid/id6784028862) (iPhone) or
   [Google Play](https://play.google.com/store/apps/details?id=ai.yanez.yid) (Android).
3. Scan the QR code again. This registers you with the Yanez YID registry.

Then, in the YID app:

1. Find your YID under **Settings**.
2. Create an agent key. It starts with `yak_`.

Use the YID app build that matches the environment you point at: Test or Production.

Copy the example settings file and fill it in:

```zsh
cd with_pulse
cp .env.example .env
```

```
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_WORKSPACE_ID=            # only if your Claude key needs it

YANEZ_AGENT_API_KEY=yak_...        # agent key from the YID app; keep it secret
YANEZ_BASE_URL=https://yid.yanez.ai
YANEZ_EXPECTED_ISSUER=https://yid.yanez.ai
YANEZ_EXPECTED_YID=<your YID>
```

- `YANEZ_BASE_URL` is where approval requests go: `https://ptest.yanez.ai` for Test or
  `https://yid.yanez.ai` for Production.
- `YANEZ_EXPECTED_ISSUER` is the issuer every receipt must name. Today it is the same as
  the base URL.
- `YANEZ_EXPECTED_YID` is the only YID whose approvals checkout accepts.

The agent stops at startup and names any setting that is missing.

Then run:

```zsh
python3 -m venv .venv
.venv/bin/pip install --pre -r requirements.txt
.venv/bin/python agent.py
```

The Pulse SDK is a pre-release, hence `--pre`. In this session the order appears in the
terminal and in the YID app at the same time:

```text
Yanez Mart shopping agent. Ask what is available, or tell me what to buy. Type 'quit' to exit.

You: buy 2 milk and a roast chicken
  -> list_items()
  -> create_order({"items": [{"item_key": "milk", "quantity": 2}, {"item_key": "chicken", "quantity": 1}]})
  -> request_approval({"order_id": "ORD-86A07457"})

Order ORD-86A07457

Item                    Qty      Unit     Total
-----------------------------------------------
Whole Milk                2     $3.49     $6.98
Roast Chicken             1     $7.99     $7.99
-----------------------------------------------
Order total                              $14.97

Deliver to: Workshop Demo Customer, 123 Demo Street, Sample City, CA 94000

Sent to your YID app (request azr_3f9c...). Approve or reject it there; waiting up to 5 minutes...

Approved in the YID app.
  -> checkout_and_pay({"order_id": "ORD-86A07457"})
  -> schedule_delivery({"order_id": "ORD-86A07457"})
  -> generate_order_pdf({"order_id": "ORD-86A07457"})

Agent: Your order is placed and paid. Total $14.97, delivery on Thursday, October 15
between 9:00 AM and 12:00 PM. Order PDF: with_pulse/orders/ORD-86A07457.pdf
```

If you reject in the app, or don't answer within 5 minutes, the order is cancelled:

```text
Sent to your YID app (request azr_7d21...). Approve or reject it there; waiting up to 5 minutes...

Not approved (rejected).

Agent: Your order ORD-86A07457 has been cancelled. What would you like to do next?
```

If the approval fails one of the merchant's checks, for example because the face scan
only reached the `low` tier, checkout refuses to pay:

```text
Approved in the YID app.
  -> checkout_and_pay({"order_id": "ORD-86A07457"})

Agent: Checkout refused the approval: it was low assurance and this store requires
medium. The order was not paid. You can place it again and approve with a fresh scan.
```

## Tests

Run the tests in either folder:

```zsh
.venv/bin/python -m pytest
```

Both test suites run offline and need no API keys. The initial version uses a scripted
stand-in for Claude. The Pulse version also uses a stand-in for Yanez that creates
receipts with real signatures, so the real Pulse verifier runs unchanged. Its tests
cover:

- approve, reject, expire and no answer
- checks that must stop payment: an approval from a different YID, a receipt signed by
  an unknown key, an approval older than 15 minutes, a scan below `medium`, a basket
  changed after approval, a receipt already used, and an attempt to pay with no approval
- the receipt never being sent to Claude

To try it end to end, run the Pulse agent with your real settings and approve one order
in the YID app. Then run it again and reject an order.

## Limits of this example

Orders live in memory and are lost when the agent exits. A real merchant would save the
order, and the token it uses to consume the receipt, in a database before checkout, so it
can recover safely after a crash.

## Learn more

- Yanez Pulse documentation: https://docs.yanez.ai/pulse/
- More detail on each version: [initial/README.md](initial/README.md) and
  [with_pulse/README.md](with_pulse/README.md)

## License

MIT. See [LICENSE](LICENSE).
