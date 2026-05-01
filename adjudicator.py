"""adjudicator.py — the judgment layer for AI agents, in one file.

Drop a single decorator on any tool function. Every call goes through a
judge LLM that reads session intent, history, agent identity, and constraints,
then returns ALLOW / BLOCK / ALLOW_AS_REFUSAL with a tamper-evident receipt.

Quickstart:
    pip install anthropic
    export ANTHROPIC_API_KEY=...
    python examples.py
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any, Callable

from anthropic import Anthropic

JUDGE = Anthropic()
DEFAULT_MODEL = "claude-haiku-4-5"   # ~50ms / ~$0.001 per verdict
DEFAULT_SECRET = os.environ.get("ADJUDICATOR_SECRET", "change-me").encode()


ADJUDICATOR_PROMPT = """You are the ADJUDICATION LAYER for an AI agent. For every tool call
the agent proposes, you receive:

  - SESSION INTENT:  what the human asked the agent to do, in one sentence
  - SESSION HISTORY: every action the agent has already taken this session
  - PROPOSED ACTION: the tool call the agent wants to make right now
  - AGENT IDENTITY:  the agent's id, role scope, and lifecycle status
  - CONSTRAINTS:     any hard caps or policies set for this session

Decide ONE verdict:
  - ALLOW             action is inside session intent and constraints
  - BLOCK             action is outside intent or breaks a constraint
  - ALLOW_AS_REFUSAL  the agent is choosing not to act (e.g. won't fabricate)

Respond with ONLY a JSON object, no prose, no markdown fence:

{
  "verdict": "ALLOW" | "BLOCK" | "ALLOW_AS_REFUSAL",
  "reason": "<one sentence, plain English>",
  "evidence": ["<short string>", ...],
  "human_required": true | false,
  "policy_id": "<short id>"
}

Be conservative. If the action is outside intent, exceeds a constraint,
or the agent is decommissioned: BLOCK and require a human. If you cannot
tell: BLOCK and require a human. Never ALLOW on uncertainty.
"""


class BlockedAction(PermissionError):
    """Raised when the judge blocks a proposed action. Contains the receipt."""

    def __init__(self, receipt: dict[str, Any]):
        self.receipt = receipt
        super().__init__(f"BLOCKED: {receipt.get('reason', '(no reason)')}")


def adjudicate(
    session_intent: str,
    session_history: list[dict[str, Any]],
    proposed_action: dict[str, Any],
    agent_identity: dict[str, Any],
    constraints: dict[str, Any],
    *,
    model: str = DEFAULT_MODEL,
    secret: bytes = DEFAULT_SECRET,
) -> dict[str, Any]:
    """Run one verdict. Returns a signed verdict dict.

    The signature is an HMAC-SHA256 over the (request, verdict) pair, so neither
    can be tampered with after the fact without breaking the signature.
    """
    request = {
        "session_intent":  session_intent,
        "session_history": session_history,
        "proposed_action": proposed_action,
        "agent_identity":  agent_identity,
        "constraints":     constraints,
    }
    msg = JUDGE.messages.create(
        model=model,
        max_tokens=500,
        system=ADJUDICATOR_PROMPT,
        messages=[{"role": "user", "content": json.dumps(request)}],
    )
    text = msg.content[0].text.strip()
    if text.startswith("```"):                      # tolerate a markdown fence
        text = text.split("```", 2)[1].lstrip("json").strip()
    verdict = json.loads(text)

    bound = json.dumps({"req": request, "v": verdict}, sort_keys=True).encode()
    verdict["signature"]   = hmac.new(secret, bound, hashlib.sha256).hexdigest()[:16]
    verdict["signed_at"]   = datetime.now(timezone.utc).isoformat()
    verdict["judge_model"] = model
    return verdict


def protect(
    intent: str,
    identity: dict[str, Any],
    constraints: dict[str, Any],
    *,
    model: str = DEFAULT_MODEL,
    secret: bytes = DEFAULT_SECRET,
) -> Callable:
    """Decorator: every call to the wrapped tool goes through the judge.

    Usage:
        @protect(
            intent="help customer c_8e4f, refunds up to $100",
            identity={"id": "a_support_07", "scope": "payments:refund", "status": "active"},
            constraints={"refund_cap_usd": 100, "scoped_customer": "c_8e4f"},
        )
        def refund(amount, customer_id):
            return your_real_refund_api(amount, customer_id)

        refund(amount=20, customer_id="c_8e4f")     # ALLOW + receipt
        refund(amount=50_000, customer_id="c_X")    # raises BlockedAction
    """
    history: list[dict[str, Any]] = []

    def decorator(fn: Callable) -> Callable:
        def wrapper(**kwargs):
            action = {"tool": fn.__name__, "args": kwargs}
            v = adjudicate(intent, history, action, identity, constraints,
                           model=model, secret=secret)
            history.append({"action": action, "verdict": v["verdict"]})
            if v["verdict"] == "BLOCK":
                raise BlockedAction(v)
            if v["verdict"] == "ALLOW_AS_REFUSAL":
                return {"refused": True, "receipt": v}
            return {"result": fn(**kwargs), "receipt": v}
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper

    return decorator
