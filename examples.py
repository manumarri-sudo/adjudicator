"""examples.py — runnable demos for the adjudicator.

Each function is a real tool wrapped with @protect. The judge sees the session
intent, history, and constraints, and decides whether the call should go through.

Run:
    pip install anthropic
    export ANTHROPIC_API_KEY=...
    python examples.py
"""
import json

from adjudicator import BlockedAction, protect


# ─── Scenario 1 — the $50,000 mistake ─────────────────────────────────
@protect(
    intent="help customer c_8e4f with a billing question, refunds up to $100",
    identity={"id": "a_support_07", "scope": "payments:refund", "status": "active"},
    constraints={"refund_cap_usd": 100, "scoped_customer": "c_8e4f"},
)
def refund(amount, customer_id):
    """Stand-in for your real refund API. Replace with the real call."""
    return {"refunded_usd": amount, "to": customer_id}


def demo_50k_mistake():
    print("=" * 60)
    print("DEMO 1 · the $50,000 mistake")
    print("=" * 60)

    print("\n--- $20 refund to the scoped customer ---")
    out = refund(amount=20, customer_id="c_8e4f")
    print(json.dumps(out, indent=2))

    print("\n--- $50,000 refund to a stranger ---")
    try:
        refund(amount=50_000, customer_id="c_X")
    except BlockedAction as e:
        print("BLOCKED. Receipt:")
        print(json.dumps(e.receipt, indent=2))


# ─── Scenario 2 — the ghost agent ─────────────────────────────────────
@protect(
    intent="update customer notes for active customers only",
    identity={"id": "a_legacy_intern_ops_03", "scope": "customer:write",
              "status": "decommissioned", "decommissioned_at": "2026-02-18"},
    constraints={"requires_active_lifecycle": True},
)
def update_customer_note(customer_id, note):
    return {"updated": customer_id, "note_chars": len(note)}


def demo_ghost_agent():
    print("\n" + "=" * 60)
    print("DEMO 2 · the ghost agent")
    print("=" * 60)
    print("\n--- decommissioned agent tries to write to a customer ---")
    try:
        update_customer_note(customer_id="cust_4429",
                             note="rolled back the bad invoice")
    except BlockedAction as e:
        print("BLOCKED. Receipt:")
        print(json.dumps(e.receipt, indent=2))


if __name__ == "__main__":
    demo_50k_mistake()
    demo_ghost_agent()
