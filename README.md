# adjudicator

A 100-line Python library that adds a **judgment layer** to any AI agent.
One decorator on a tool function and every call goes through an LLM judge
that reads the session intent, history, and constraints, and decides whether
the action should be allowed. Out-of-scope actions raise `BlockedAction`
with a tamper-evident signed receipt.

Built around the idea in [The Adjudication Gap](https://manumarri.substack.com/p/the-adjudication-gap):
most AI agent stacks have telemetry (the "camera") and identity (the "badge"),
but no third layer that asks, in the moment, whether the action *should* have
been allowed given the session. That third layer is what this is.

## Install and run

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
git clone https://github.com/<your-username>/adjudicator
cd adjudicator
python examples.py
```

## Usage

```python
from adjudicator import protect, BlockedAction

@protect(
    intent="help customer c_8e4f with a billing question, refunds up to $100",
    identity={"id": "a_support_07", "scope": "payments:refund", "status": "active"},
    constraints={"refund_cap_usd": 100, "scoped_customer": "c_8e4f"},
)
def refund(amount, customer_id):
    return your_real_refund_api(amount, customer_id)

refund(amount=20, customer_id="c_8e4f")
# {"result": {"refunded_usd": 20, "to": "c_8e4f"},
#  "receipt": {"verdict": "ALLOW", "reason": "...",
#              "signature": "9d4f218b7c...", "signed_at": "..."}}

refund(amount=50_000, customer_id="c_X")
# raises BlockedAction with the signed BLOCK receipt
```

## What it does, plainly

For every tool call, the judge sees five things:

1. **Session intent** — what the human asked the agent to do, in one sentence
2. **Session history** — every action the agent has already taken in this session
3. **Proposed action** — the tool call the agent wants to make right now
4. **Agent identity** — the agent's id, role scope, and lifecycle status
5. **Constraints** — any hard caps or policies set for this session

It returns one of three verdicts:

- **ALLOW** — action is inside session intent and constraints
- **BLOCK** — action is outside intent or breaks a constraint
- **ALLOW_AS_REFUSAL** — the agent is choosing not to act (e.g. refusing to fabricate data)

The receipt is signed with HMAC-SHA256 over the *(request, verdict)* pair, so
neither can be tampered with after the fact without breaking the signature.

## Why this exists

Three checks happen around any AI agent action:

1. **The camera** — did this happen? Telemetry, OpenTelemetry GenAI, audit logs.
2. **The badge** — is this agent who they say? OAuth, agent identity, role checks.
3. **The bank manager** — was *this* allowed *right now*? Session-aware adjudication.

Layers 1 and 2 are well-funded categories. Layer 3 is the gap. This library is
a 100-line answer to layer 3, suitable for dropping into your own agent stack.

It is not a replacement for real governance tooling (Credo AI, Trustible,
ModelOp, etc.). It is the smallest credible thing you can run in production
*today*, while you decide what your real governance posture looks like.

## What this gets you on paper

- **EU AI Act, Article 14** (real human oversight, enforceable from August 2, 2026):
  every BLOCKED action routes to a human, with a tamper-evident receipt.
- **EU AI Act, Article 12** (logging): the receipt *is* the log.
- **NIST AI RMF, GV-1.4 / MS-2.5**: oversight policy that runs at the moment of
  action, not just on paper.
- **SOC 2 Trust Services, CC7.2**: anomaly detection that fires before damage,
  not after.

It does **not** replace your overall risk register, your model cards, your
red-team work, or your incident response plan. It plugs the specific gap
between "tool was called" and "tool should have been called."

## Limits and honest caveats

- The judge is an LLM. It can be fooled by adversarial inputs in the session
  history. Treat it like any classifier in front of high-stakes actions.
- HMAC signing proves the verdict came from a process that knows your secret.
  It does not prove the verdict came from a specific judge model. If you need
  that, swap to ECDSA signing with a hardware-backed key.
- The default model (`claude-haiku-4-5`) is the cheap fast option. For
  high-stakes flows (large dollar amounts, irreversible actions), pin to a
  larger model and add a second-judge confirmation.
- The `protect` decorator keeps history in memory per process. For real
  multi-process deployments, replace with a session store (Redis, Postgres)
  and pass `session_history` into `adjudicate()` directly.
- This is a starting point, not a finished system. Read the 100 lines of code
  before you ship it.

## License

MIT. Use it. Fork it. Ship it.

## Citing

If this helps you understand the layer or you want to point your team at the
underlying argument, the post is here:
[The Adjudication Gap](https://manumarri.substack.com/p/the-adjudication-gap).

---

Maintained by [Manu Marri](https://manumarri.substack.com) · part of
[Loomiq](https://loomiq.com)'s open work on AI agent trust infrastructure.
