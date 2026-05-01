"""adjudicator.py — the judgment layer for AI agents, in one file.

Drop a single decorator on any tool function. Every call goes through:
  1. Cheap deterministic rules (e.g. decommissioned agent -> BLOCK, no LLM call)
  2. A Claude Haiku judge using structured tool_use output (no prose parsing)
  3. An HMAC-SHA256 signature binding the request and verdict together

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
DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_SECRET = os.environ.get("ADJUDICATOR_SECRET", "change-me").encode()


ADJUDICATOR_PROMPT = """You are the ADJUDICATION LAYER for an AI agent. For every tool call
the agent proposes, you receive:

  - SESSION INTENT:  what the human asked the agent to do, in one sentence
  - SESSION HISTORY: every action the agent has already taken this session
  - PROPOSED ACTION: the tool call the agent wants to make right now
  - AGENT IDENTITY:  the agent's id, role scope, and lifecycle status
  - CONSTRAINTS:     any hard caps or policies set for this session

Decide ONE verdict, returned via the submit_verdict tool:
  - ALLOW             action is inside session intent and constraints
  - BLOCK             action is outside intent or breaks a constraint
  - ALLOW_AS_REFUSAL  the agent is choosing not to act (e.g. won't fabricate)

Be conservative. If the action is outside intent, exceeds a constraint,
or the agent is decommissioned: BLOCK and require a human. If you cannot
tell: BLOCK and require a human. Never ALLOW on uncertainty.

Always populate evidence with 1-3 short strings citing the specific inputs
that drove your decision.
"""


VERDICT_TOOL = {
    "name": "submit_verdict",
    "description": "Submit your adjudication verdict for the proposed action.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["ALLOW", "BLOCK", "ALLOW_AS_REFUSAL"],
                "description": "The decision.",
            },
            "reason": {
                "type": "string",
                "description": "One sentence, plain English, why.",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "1-3 short strings citing the specific inputs that drove the decision.",
            },
            "human_required": {
                "type": "boolean",
                "description": "True if a human must intervene before any related action proceeds.",
            },
            "policy_id": {
                "type": "string",
                "description": "Short id of the policy applied (free text; e.g. session_scope_v1).",
            },
        },
        "required": ["verdict", "reason", "evidence", "human_required", "policy_id"],
    },
}


class BlockedAction(PermissionError):
    """Raised when the judge blocks a proposed action. Contains the receipt."""

    def __init__(self, receipt: dict[str, Any]):
        self.receipt = receipt
        super().__init__(f"BLOCKED: {receipt.get('reason', '(no reason)')}")


def _sign(verdict: dict[str, Any], request: dict[str, Any], *, secret: bytes,
          model_used: str | None) -> dict[str, Any]:
    bound = json.dumps({"req": request, "v": verdict}, sort_keys=True).encode()
    verdict["signature"]   = hmac.new(secret, bound, hashlib.sha256).hexdigest()[:16]
    verdict["signed_at"]   = datetime.now(timezone.utc).isoformat()
    verdict["judge_model"] = model_used
    return verdict


def _hard_rules(action: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any] | None:
    """Cheap deterministic checks that don't need an LLM. Return a verdict dict if any
    rule fires, otherwise None to defer to the LLM judge.

    Currently checks one universal rule: a decommissioned agent must never act.
    Project-specific hard rules (refund caps, etc.) belong in your application code,
    NOT here. Hard rules in your app fire before adjudicate() is even called.
    """
    status = identity.get("status", "active")
    if status in ("decommissioned", "disabled", "revoked"):
        return {
            "verdict": "BLOCK",
            "reason": f"Agent {identity.get('id', '<unknown>')} has lifecycle status '{status}'. Decommissioned agents must not act.",
            "evidence": [f"agent_identity.status = {status}"],
            "human_required": True,
            "policy_id": "hard_rule_lifecycle",
        }
    return None


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

    Pipeline:
      1. Hard rules (deterministic, no LLM call). If any fires, return immediately.
      2. LLM judge with tool_use structured output. Never parses prose.

    Signature is HMAC-SHA256 over the (request, verdict) pair, so neither can be
    tampered with after the fact without breaking the signature.
    """
    request = {
        "session_intent":  session_intent,
        "session_history": session_history,
        "proposed_action": proposed_action,
        "agent_identity":  agent_identity,
        "constraints":     constraints,
    }

    rule_verdict = _hard_rules(proposed_action, agent_identity)
    if rule_verdict is not None:
        return _sign(rule_verdict, request, secret=secret, model_used="hard_rules")

    msg = JUDGE.messages.create(
        model=model,
        max_tokens=500,
        system=ADJUDICATOR_PROMPT,
        tools=[VERDICT_TOOL],
        tool_choice={"type": "tool", "name": "submit_verdict"},
        messages=[{"role": "user", "content": json.dumps(request)}],
    )

    verdict = None
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_verdict":
            verdict = dict(block.input)
            break
    if verdict is None:
        raise RuntimeError(
            "Judge did not return a structured verdict. "
            "This should be impossible with tool_choice forced; check SDK version."
        )

    return _sign(verdict, request, secret=secret, model_used=model)


def protect(
    intent: str,
    identity: dict[str, Any],
    constraints: dict[str, Any],
    *,
    model: str = DEFAULT_MODEL,
    secret: bytes = DEFAULT_SECRET,
) -> Callable:
    """Decorator: every call to the wrapped tool goes through the judge."""
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


def verify_receipt(receipt: dict[str, Any], request: dict[str, Any], *,
                   secret: bytes = DEFAULT_SECRET) -> bool:
    """Verify the HMAC signature on a stored receipt against its original request.
    Use this in your audit pipeline to confirm receipts haven't been tampered with.
    """
    sig = receipt.get("signature")
    if not sig:
        return False
    verdict_only = {k: v for k, v in receipt.items()
                    if k not in ("signature", "signed_at", "judge_model")}
    bound = json.dumps({"req": request, "v": verdict_only}, sort_keys=True).encode()
    expected = hmac.new(secret, bound, hashlib.sha256).hexdigest()[:16]
    return hmac.compare_digest(sig, expected)
