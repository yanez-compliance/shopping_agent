# Frequently asked questions

These answers cover the shopping agent demo and Yanez Pulse, the service it uses to get a
person's approval. They are written for anyone, not only security experts.

## About the demo

### What does this demo show?

It shows one AI shopping agent built twice. You chat with it in a terminal: ask what it
sells, or tell it what to buy, and it builds an order.

In the first version, you approve the order by typing `y`. In the second version, the
order is sent to the YID app on your phone, you approve it there with a face scan, and the
store checks a signed record of your approval before it takes payment.

The point is to compare the two kinds of "yes": one the store has to take on trust, and
one the store can check for itself.

### Is any real money spent?

No. Payment and delivery are simulated. No card is charged and nothing is shipped.

### What does the AI actually do?

The AI (Claude) understands your request and chooses the items from the catalog. Ordinary
program code does everything that has to be exact: it works out prices and totals, and it
enforces the rule that an order can't be paid before it is approved. So the AI can't make
up a price or skip the approval step.

### Can this be used for things other than shopping?

Yes. Shopping is just an easy example. The same approach fits any action you wouldn't want
an AI agent to take on its own, such as sending money, changing an account or signing up
for a service.

## Approval and Yanez Pulse

### Why isn't typing "y" good enough?

In the first version, your "y" goes into the same program the agent is running in. The
store never hears from you directly; it only hears from the agent. If the agent had a bug,
or someone tricked it with cleverly written instructions, it could skip the question or
claim you said yes when you didn't. The store would have no way to tell.

Typing "y" also leaves no proof of which order you agreed to, and nothing stops the same
"yes" from being used twice.

### What is Yanez Pulse?

Yanez Pulse is a service that lets an AI agent ask a real person to approve a specific
action. The person approves or rejects it in the YID app on their phone. If they approve,
Pulse produces a receipt: a signed record of exactly what was approved, by whom and when.
The business carrying out the action checks that receipt before it acts.

### What is a YID?

A YID is your Yanez identity: the account you set up in the YID app, linked to your face.
Every receipt names the YID of the person who approved. In this demo, the store only
accepts approvals from one YID, the one in its settings.

### What do I see in the YID app?

You see the details of the order you are being asked to approve: the store, the items, the
total, the delivery address and the order number. You then approve or reject it. Either
way, you confirm with a fresh face scan.

### Can the AI agent approve on its own behalf?

No. The agent has its own key (it starts with `yak_`), and according to the Pulse
documentation that key can only ask for approval. It can't approve, and it can't act.
Only you can approve, in the app, with your face.

### What happens if I say no, or don't answer?

If you reject the order, it is cancelled and nothing is paid. If you don't answer within
5 minutes, the request expires and the order is cancelled too. The agent has no way around
a "no".

## The receipt

### What is in the receipt?

The receipt records:

- your YID
- the exact order you approved (items, total, address, order number)
- when you approved it
- how strong your face scan was (the "assurance tier", explained below)
- two digital signatures: one from Yanez and one made on your phone

It does not contain your name, your date of birth, your face or any other personal details.

### Why does the receipt have two signatures?

Each signature proves something different.

Yanez's signature shows that Yanez recorded your approval. The signature made on your
phone shows that you, using a key that only your face scan can produce, approved this
exact order. Because the store checks both, it doesn't have to rely on the AI agent, and
it doesn't have to rely on Yanez's word alone.

### Does the AI ever see the receipt?

No. The receipt is kept away from the AI, from the program's log output and from the
order PDF. Anyone who held a copy of an unused receipt could try to spend it, so it goes
only to the store.

## Signatures and keys

### What is a digital signature?

A digital signature is the online version of signing a document, but much harder to fake.

It uses a pair of keys. The private key is secret and is used to sign. The public key can
be shared with anyone and is used to check signatures. If a signature checks out against
the public key, two things are proven: it was made by whoever holds the matching private
key, and the signed content hasn't changed by even one character since it was signed.
Without the private key, nobody can produce a signature that passes the check.

### What is BLS?

BLS (Boneh–Lynn–Shacham) is a widely used, standard type of digital signature, and it's
what your phone uses to sign your approval.

### How is my signing key created?

According to the Pulse documentation, the key that signs your approval is derived on your
phone from your biometric scan, during the approval itself. How the YID app does this is
part of Yanez's own technology and isn't covered here. What matters for the store is that
it can check the resulting signature with the matching public key.

### What is the assurance tier, or "scan strength"?

It describes how strong a match your face scan achieved. There are three levels: low,
medium and high. The level is part of what your phone signs, so it can't be changed
afterwards without the signature failing.

Each business decides the lowest level it accepts, based on what's at stake. The store in
this demo requires at least medium. A genuine approval at the low level is refused.

## What the store checks

### What exactly does the store check before it pays?

Before paying, the store checks that:

1. **The signatures are genuine:** both Yanez's signature and the one from your phone.
2. **The order is the same one you approved.** The store rebuilds the order from its own
   records and compares it with what you signed. If even one item or the total changed,
   it refuses.
3. **The approval came from the right person,** meaning the YID the store expects.
4. **The face scan was strong enough,** meaning medium or higher in this demo.
5. **The approval is fresh,** meaning less than 15 minutes old.
6. **The receipt hasn't been used before.**

Only if every check passes does it take the payment.

### Does the store need to understand the cryptography?

No. Yanez provides a software library that does the cryptographic checks. The store makes
one call to it.

What the store does have to decide is its own rules: what order it expects (taken from
its own records, never from the AI agent), whose approval it accepts, the lowest scan
strength it accepts and how old an approval may be. Those are business decisions, not
cryptography.

### Can the same approval be used twice?

No. When the store accepts a receipt, it asks Yanez to mark it as used, and Yanez records
that it has been used. If anyone tries the same receipt again, Yanez reports
that it has already been used and the store refuses. If the store's own connection drops
partway through, Yanez recognises the store's retry, so the store finishes the original
payment instead of charging twice.

### Does the store check that the key really belongs to me?

The store checks that your signature is valid for the public key carried in the receipt.
That this key belongs to your YID is something Yanez vouches for, by signing the receipt
that contains it. The store in this demo trusts Yanez for that link and doesn't check it
some other way.

