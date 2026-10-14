# Shopping agent workshop

This project shows one AI shopping agent built twice:

1. **`initial/`**: the agent asks you to approve each order with `y` or `n` in the terminal.
2. **`with_pulse/`**: the same agent asks you to approve in the **YID app** on your phone,
   using **Yanez Pulse**. The merchant then checks a signed receipt of your approval
   before it takes payment.

Comparing the two shows what changes when a human approval becomes something a merchant
can verify, rather than something it has to take on trust.

Both versions sell the same eight sample groceries. Payment and delivery are fake: no
card is charged and nothing ships.

## Part 1: the initial shopping agent

### What it does

You chat with the agent in the terminal. It understands two kinds of request:

- **"What can I buy?"** It lists the catalog with unit prices.
- **"Buy 2 milk and a roast chicken."** It matches your words to catalog items and builds
  an order. Then it shows you the order and asks you to approve it.
  - If you approve, it checks out, takes a fake payment, schedules a fake delivery, and
    saves the order as a PDF in `initial/orders/`.
  - If you reject, it cancels the order and waits for your next request.

The agent is Claude (model `claude-opus-5-5`), with six tools it can call: list items,
create order, request approval, check out and pay, schedule delivery, and generate the
PDF. Python code works out every price and total, so the model can't invent amounts.
The order rules are also in code: an order can't be paid until you have approved it,
whatever the model decides.

### Configuration

Create `initial/.env` with your Claude API key:

```
ANTHROPIC_API_KEY=sk-ant-...
# Only if your Claude key is not scoped to a workspace:
ANTHROPIC_WORKSPACE_ID=wrkspc_...
```

A Claude API key "scoped to a workspace" belongs to one workspace in the Claude Console.
If yours isn't, the API asks for the workspace ID on every request. You can find the ID
under Settings, then Workspaces, in the Claude Console.

### Run

```zsh
cd initial
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python agent.py
```

Lines starting with `->` are the tools the agent calls. They are printed so you can
follow each step. Claude's own replies (lines starting with `Agent:`) will be worded
differently each time.

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

If you answer `n`, the agent replies that the order is cancelled and waits for your next
request.

### Test

```zsh
.venv/bin/python -m pytest
```

The tests use a scripted stand-in for Claude, so they need no API key.

## Part 2: the shopping agent with Yanez Pulse

### Why use Pulse

In the initial version, approval is a `y` typed into the same program the agent runs in.
That works for a demo, but the merchant has nothing to check:

- Anyone at the keyboard can type `y`.
- An agent that is buggy or has been manipulated can skip the question or report a
  false answer, and the merchant has no way to know.
- Nothing proves which basket was approved, so a changed basket looks the same as the
  approved one.
- Nothing stops one approval from being used twice.
- After the fact, there is no evidence of who approved what and when.

**Yanez Pulse** lets an AI agent ask a real person to approve an exact action, and gives
the business that carries out the action (here, the merchant) proof it can check itself.

### What Pulse provides

- **Approval on the person's own device.** The order appears in the YID app on your
  phone. You approve or reject behind a fresh face scan.
- **Exact terms.** The app shows the same order the merchant will charge for: the items,
  the total, the delivery address and the order ID.
- **A receipt signed twice.** An approval produces a receipt signed by Yanez and also by
  your own key on your device. The merchant checks both signatures, so it doesn't have to
  trust the agent or take Yanez's word alone.
- **A tie to the right person.** The receipt names the approver's YID (their Yanez
  identity). The merchant accepts approvals only from the YID set in its configuration.
- **Scan strength.** The receipt records an assurance tier (`low`, `medium` or `high`),
  which says how strong the face scan was. This merchant requires at least `medium`.
- **Single use.** At checkout the merchant marks the receipt as used with Yanez, so the
  same approval can't pay twice.
- **Freshness.** The merchant refuses approvals older than 15 minutes.
- **A limited agent key.** According to the Pulse docs, the agent's `yak_` key can only
  ask for approval, not approve or act.
- **A record.** The order PDF shows who approved, the approval request ID, when they
  approved, and the assurance tier.

### How the parts fit together

All three roles run in one process for the workshop, but each lives in its own file:

- **The agent** (`agent.py`, with Claude) builds the order and asks for approval. It
  never gets to pay.
- **The Pulse request** (`approval.py`) sends the order to the YID app and waits for the
  decision. The receipt it receives is kept away from Claude, the logs and the PDF,
  because anyone holding a receipt could try to spend it.
- **The merchant checkout** (`merchant.py`) is the only code that can take payment. It
  rebuilds the expected terms from its own order record, verifies the receipt against
  them, and pays only when every check passes.

### Configuration

Before you start, in the YID app:

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
YANEZ_BASE_URL=https://ptest.yanez.ai
YANEZ_EXPECTED_ISSUER=https://ptest.yanez.ai
YANEZ_EXPECTED_YID=<your YID>
```

- `YANEZ_BASE_URL` is where approval requests go. Use `https://ptest.yanez.ai` for Test
  or `https://yid.yanez.ai` for Production.
- `YANEZ_EXPECTED_ISSUER` is the issuer every receipt must name. Today it is the same as
  the base URL.
- `YANEZ_EXPECTED_YID` is the only YID whose approvals checkout accepts.

The agent stops at startup and names any setting that is missing.

### Run

```zsh
python3 -m venv .venv
.venv/bin/pip install --pre -r requirements.txt
.venv/bin/python agent.py
```

The Pulse SDK is a pre-release, hence `--pre`. In the session below, the order appears
in the terminal and in the YID app at the same time:

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

If the approval doesn't pass the merchant's checks, for example because the face scan
only reached the `low` tier, checkout refuses to pay:

```text
Approved in the YID app.
  -> checkout_and_pay({"order_id": "ORD-86A07457"})

Agent: Checkout refused the approval: it was low assurance and this store requires
medium. The order was not paid. You can place it again and approve with a fresh scan.
```

### Test

```zsh
.venv/bin/python -m pytest
```

The tests run offline. A stand-in for Yanez creates receipts with real signatures, so
the real Pulse verifier runs unchanged. The tests cover:

- approve, reject, expire and no-answer
- checks that must stop payment: approval from a different YID, a receipt signed by an
  unknown key, an approval older than 15 minutes, a scan below `medium`, a basket edited
  after approval, a receipt already used, and an attempt to pay with no approval
- the receipt never being sent to Claude

To try it end to end, run the agent with your real settings and approve one order in the
YID app. Then run it again and reject an order.

### Demo limits

Orders live in memory and are lost when the agent exits. A real merchant would store
orders, and the token it uses to mark a receipt as used, in a database before checkout,
so it can recover safely after a crash.

## License

MIT. See [LICENSE](LICENSE).
