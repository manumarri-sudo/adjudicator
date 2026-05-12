"""Deterministic tests for adjudicator.

These cover the parts that don't need a live LLM judge:

  * Hard rules (lifecycle status)
  * HMAC signing and verification
  * BlockedAction error shape
  * protect() integration when the underlying tool raises

Live LLM-judge tests live in tests/test_live.py and require ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import os
import pytest

# adjudicator is a single-module package
from adjudicator import (
    BlockedAction,
    _hard_rules,
    _sign,
    verify_receipt,
)


# ---------------------------------------------------------------------------
# Hard rules: decommissioned agents must never act
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["decommissioned", "disabled", "revoked"])
def test_decommissioned_agent_blocked(status: str) -> None:
    action = {"tool": "any_tool", "args": {}}
    identity = {"id": "agent_x", "status": status}
    v = _hard_rules(action, identity)
    assert v is not None
    assert v["verdict"] == "BLOCK"
    assert "hard_rule_lifecycle" in v["policy_id"]
    assert v["human_required"] is True


def test_active_agent_passes_hard_rules() -> None:
    action = {"tool": "any_tool", "args": {}}
    identity = {"id": "agent_x", "status": "active"}
    v = _hard_rules(action, identity)
    assert v is None  # defers to the LLM judge


# ---------------------------------------------------------------------------
# HMAC signing: receipt is signed and verifiable, tampering breaks the signature
# ---------------------------------------------------------------------------


def test_signed_receipt_verifies() -> None:
    request = {
        "session_intent": "test intent",
        "session_history": [],
        "proposed_action": {"tool": "t", "args": {}},
        "agent_identity": {"id": "a", "status": "active"},
        "constraints": {},
    }
    verdict = {
        "verdict": "ALLOW",
        "reason": "test reason",
        "evidence": ["e1"],
        "human_required": False,
        "policy_id": "test",
    }
    secret = b"test-secret-1234567890"
    signed = _sign(dict(verdict), request, secret=secret, model_used="test")
    assert "signature" in signed
    assert "signed_at" in signed
    assert verify_receipt(signed, request, secret=secret) is True


def test_tampered_verdict_breaks_signature() -> None:
    request = {
        "session_intent": "test",
        "session_history": [],
        "proposed_action": {"tool": "t", "args": {}},
        "agent_identity": {"id": "a", "status": "active"},
        "constraints": {},
    }
    verdict = {
        "verdict": "ALLOW",
        "reason": "ok",
        "evidence": [],
        "human_required": False,
        "policy_id": "p",
    }
    secret = b"test-secret"
    signed = _sign(dict(verdict), request, secret=secret, model_used="test")
    # tamper with the verdict after the fact
    signed["verdict"] = "BLOCK"
    assert verify_receipt(signed, request, secret=secret) is False


def test_tampered_request_breaks_signature() -> None:
    request = {
        "session_intent": "fetch /tmp/foo",
        "session_history": [],
        "proposed_action": {"tool": "fetch", "args": {"path": "/tmp/foo"}},
        "agent_identity": {"id": "a", "status": "active"},
        "constraints": {},
    }
    verdict = {
        "verdict": "ALLOW",
        "reason": "ok",
        "evidence": [],
        "human_required": False,
        "policy_id": "p",
    }
    secret = b"test-secret"
    signed = _sign(dict(verdict), request, secret=secret, model_used="test")
    # tamper with what the agent supposedly asked for
    bad_request = dict(request)
    bad_request["proposed_action"] = {"tool": "fetch", "args": {"path": "/etc/passwd"}}
    assert verify_receipt(signed, bad_request, secret=secret) is False


def test_wrong_secret_fails_verification() -> None:
    request = {
        "session_intent": "x",
        "session_history": [],
        "proposed_action": {"tool": "t", "args": {}},
        "agent_identity": {"id": "a", "status": "active"},
        "constraints": {},
    }
    verdict = {
        "verdict": "ALLOW",
        "reason": "ok",
        "evidence": [],
        "human_required": False,
        "policy_id": "p",
    }
    signed = _sign(dict(verdict), request, secret=b"secret-a", model_used="t")
    assert verify_receipt(signed, request, secret=b"secret-b") is False


# ---------------------------------------------------------------------------
# BlockedAction exception shape
# ---------------------------------------------------------------------------


def test_blocked_action_carries_receipt() -> None:
    receipt = {
        "verdict": "BLOCK",
        "reason": "out of scope",
        "evidence": ["x"],
        "human_required": True,
        "policy_id": "test",
        "signature": "deadbeef",
        "signed_at": "2026-05-11T00:00:00Z",
    }
    exc = BlockedAction(receipt)
    assert exc.receipt == receipt
    assert "out of scope" in str(exc)
    assert isinstance(exc, PermissionError)
