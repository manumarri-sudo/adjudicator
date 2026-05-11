# adjudicator

A small Python library that adds a **judgment layer** to any AI agent. One
decorator on a tool function and every call goes through:

1. **Cheap deterministic rules first** (e.g. a decommissioned agent always
   BLOCKs without an LLM call).
2. **A Claude Haiku judge using `tool_use` structured output** (no prose
   parsing: the SDK enforces the verdict schema).
3. **An HMAC-SHA256 signature binding the request and the verdict together**
   so receipts are tamper-evident and verifiable after the fact.

Out-of-scope actions raise `BlockedAction` with the signed receipt. In-scope
actions return `{"result": ..., "receipt": ...}`.

Built around the idea in [The Adjudication Gap](https://manumarri.substack.com/p/the-adjudication-gap):
most AI agent stacks have telemetry (the "camera") and identity (the "badge"),
but no third layer that asks, in the moment, whether the action *should* have
been allowed given the session. This is a starter for that third layer.

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
# {"result": {...}, "receipt": {"verdict": "ALLOW", "signature": "9d4f218b7c4a1b2e", ...}}

refund(amount=50_000, customer_id="c_X")
# raises BlockedAction with the signed BLOCK receipt
```

## Verifying receipts later

The signature binds `(request, verdict)` so neither can be tampered with after
the fact without breaking it. Re-verify any stored receipt:

```python
from adjudicator import verify_receipt

ok = verify_receipt(stored_receipt, original_request, secret=YOUR_SECRET)
# True if the receipt is intact, False if anything was modified
```

## What it does, plainly

For every tool call, the judge sees five things:

1. **Session intent**: what the human asked the agent to do, in one sentence
2. **Session history**: every action the agent has already taken in this session
3. **Proposed action**: the tool call the agent wants to make right now
4. **Agent identity**: the agent's id, role scope, and lifecycle status
5. **Constraints**: any hard caps or policies set for this session

It returns one of three verdicts via the `submit_verdict` tool (structured
output, never free prose):

- **ALLOW**: action is inside session intent and constraints
- **BLOCK**: action is outside intent or breaks a constraint
- **ALLOW_AS_REFUSAL**: the agent is choosing not to act (e.g. refusing to fabricate data)

## Why this exists

Three checks happen around any AI agent action:

1. **The camera**: did this happen? Telemetry, OpenTelemetry GenAI, audit logs.
2. **The badge**: is this agent who they say? OAuth, agent identity, role checks.
3. **The bank manager**: was *this* allowed *right now*? Session-aware adjudication.

Layers 1 and 2 are well-funded categories. Layer 3 is the gap. This library
is a small starter for layer 3, suitable for dropping into your own agent stack.

It is not a replacement for serious runtime guardrail work. For that, look at
[Meta LlamaFirewall](https://meta-llama.github.io/PurpleLlama/LlamaFirewall/),
[NVIDIA NeMo Guardrails](https://github.com/NVIDIA-NeMo/Guardrails), or
[Invariant Labs](https://github.com/invariantlabs-ai/invariant). Those are
more battle-tested than what's here.

## Limits and honest caveats

- **The judge is an LLM.** It can hallucinate, drift, or be jailbroken via
  prompt injection in the session history. The deterministic rules layer above
  it catches the universal cases (decommissioned agent), but you should add
  your own deterministic rules for high-stakes actions in your application
  code, BEFORE calling `adjudicate()`.
- **HMAC signing proves the verdict came from a process that knows your secret.**
  It does not prove the verdict came from a specific judge model. For that,
  swap to ECDSA signing with a hardware-backed key.
- **The default model (`claude-haiku-4-5`)** is the cheap fast option. For
  high-stakes flows, pin to a larger model and consider running two judges and
  requiring agreement (multi-judge consensus).
- **The `protect` decorator keeps history in memory per process.** For
  multi-process or multi-tenant deployments, replace with a session store
  (Redis, Postgres) and pass `session_history` into `adjudicate()` directly.
- **This is a starting point, not a finished system.** Read all 200 lines
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

---

Built with assistance from Claude (Anthropic).
