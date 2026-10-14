# Shopping agent (initial version)

A command-line shopping agent for the workshop. You chat with it in the terminal. It can:

- list the items it sells, with unit prices
- turn a shopping request into an order and show it to you for review
- after you approve, check out, pay and schedule delivery, then save the order as a PDF
- after you reject, cancel the order and wait for your next instruction

Payment and delivery are fake. No card is charged and nothing ships. The catalog is the same
eight groceries as the Yanez Mart demo.

The build request is in [build_prompt.md](build_prompt.md).

## Setup

You need Python 3.11 or newer and a Claude API key.

```zsh
cd initial
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Put your key in `.env` as `ANTHROPIC_API_KEY=sk-ant-...`. The agent loads `.env` from its own
folder at startup. A key you already exported in the shell takes priority over `.env`.
`.env` is listed in `.gitignore`, so the key stays out of git.

If your key is not scoped to a workspace, the API returns a 400 asking for the
`anthropic-workspace-id` header. Add `ANTHROPIC_WORKSPACE_ID=wrkspc_...` to `.env` and the
agent sends it on every request. Leave it empty if your key belongs to a workspace.

## Run

```zsh
.venv/bin/python agent.py
```

Example session:

```text
You: what can I buy?
You: buy 2 milk, a roast chicken and some caviar
Approve this order? [y/n]: y
```

The agent prints each tool it calls (lines starting with `->`), so the audience can follow its
steps. PDFs are saved to `orders/<order id>.pdf`. Type `quit` or press Ctrl+C to exit.

## How it works

Claude (`claude-opus-5-5`) runs a tool-use loop in `agent.py`. It decides which tool to call
next. The tools are:

- `list_items` returns the catalog with unit prices
- `create_order` builds a draft order from catalog item keys and quantities
- `request_approval` prints the order and asks you `y` or `n` in the terminal
- `checkout_and_pay` takes a fake payment and returns a payment ID
- `schedule_delivery` books a fake delivery two days out
- `generate_order_pdf` writes the order PDF

Claude does the matching. It reads the catalog and maps requests like "some coffee" to item
keys. Python code calculates prices and totals, so the model cannot make them up.

The approval check is in code, not in the prompt. `orders.py` only allows these status changes:

```text
awaiting_approval -> approved -> paid -> delivery_scheduled
awaiting_approval -> cancelled
```

Only your `y` at the terminal prompt moves an order to `approved`. If the model tries to pay
early, the tool returns an error.

Requests use the API's `fallbacks: "default"` option. If the model's safety filter declines a
request, the API retries it on a fallback model chosen by Anthropic.

## Tests

The tests use a scripted stand-in for Claude, so they run without an API key:

```zsh
.venv/bin/python -m pytest
```

## Files

- `agent.py` holds the system prompt, tool definitions, agent loop and terminal interface
- `catalog.py` holds the items and prices
- `orders.py` holds the order lifecycle, fake payment and fake delivery
- `order_pdf.py` renders the PDF
