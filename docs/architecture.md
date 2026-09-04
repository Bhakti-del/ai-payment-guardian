# Architecture — AI Payment Guardian
### Track 03: AI Revenue Recovery

---

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                          USER                                │
│               (Browser — frontend/index.html)                │
└────────────────────────────┬────────────────────────────────┘
                             │ HTTP REST
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI Backend                          │
│                    (app/main.py :8000)                       │
│                                                              │
│  Cases & Events     Recovery (Track 03)    AI Agent          │
│  ───────────────    ────────────────────   ─────────────     │
│  GET  /api/cases    POST /recovery/batch   POST /agent/query │
│  GET  /cases/:id    GET  /recovery/cases   GET  /actions/... │
│  POST /simulate     GET  /recovery/metrics POST /approve     │
│  POST /resolve      GET  /recovery/audit                     │
└───┬──────────────────────┬─────────────────────┬────────────┘
    │                      │                     │
    ▼                      ▼                     ▼
┌──────────┐   ┌───────────────────────┐   ┌────────────────┐
│ SQLite   │   │ Case Engine +         │   │  AI Agent      │
│          │   │ Stopping Rules        │   │                │
│ users    │   │ (deterministic)       │   │ Groq LLM       │
│ txns     │◄──│                       │   │ gpt-oss-120b   │
│ cases    │   │ • Health score calc   │   │                │
│ events   │   │ • State transitions   │   │ Tool calling   │
│ actions  │   │ • MAX_INTERVENTIONS=3 │   │ loop (6 iter)  │
│ batches  │   │ • MAX_ESCALATIONS=1   │   │                │
│ interv.  │   │ • Channel escalation  │   │ 14 tools       │
└──────────┘   └───────────────────────┘   └───────┬────────┘
                                                   │
               ┌───────────────────────────────────┤
               ▼               ▼                   ▼
        get_transaction()  trigger_recovery()  escalate_case()
        get_order_status() mark_recovered()    prepare_dispute()
        calculate_health() get_recovery_status() log_intervention()
```

---

## Key Design Decisions

### 1. Deterministic vs AI

```
DETERMINISTIC (never touches LLM):       AI (LLM only):
────────────────────────────────         ──────────────
• Health score calculation               • Understanding questions
• Stopping rule enforcement              • Diagnosing root cause
• Channel selection (email→sms→wa)       • Explaining issues
• State transitions                      • Choosing which tools to call
• Amount arithmetic                      • Writing recovery messages
• Escalation threshold checks            • Recommending next actions
```

LLM has no direct DB access. It only receives structured data returned by tools. This prevents hallucination on financial data.

### 2. Stopping Rules (hard limits, always checked first)

```python
MAX_INTERVENTIONS_PER_CASE = 3   # never chase a customer more than 3 times
MAX_ESCALATIONS_PER_CASE   = 1   # file a dispute once only

def should_stop_recovery(db, case_id) -> {"stop": bool, "reason": str}:
    if case.status == "resolved":          → stop
    if total_interventions >= 3:           → stop, auto-escalate
    if escalations >= 1:                   → stop, no further action
    else:                                  → proceed
```

Every recovery tool calls `should_stop_recovery()` before doing anything. If the rule says stop, the tool returns a `stopped` response and logs nothing.

### 3. Channel Escalation

```
Attempt 1 → email     (professional English)
Attempt 2 → sms       (Hinglish, friendly)
Attempt 3 → whatsapp  (Hinglish, urgent)

After 3 failures → escalate to dispute (pending user approval)
```

Hinglish example (SMS/WhatsApp):
> "Arre yaar! Aapka ₹4,999 ka payment XYZ Electronics ke saath stuck hai. Ek click mein resolve karein: rzp.io/l/recovery-001"

### 4. Human-in-the-Loop

```
AI can do autonomously:               Requires user approval:
────────────────────────              ──────────────────────
• Call all 14 investigation tools     • prepare_dispute()
• Trigger recovery interventions      • escalate_case() → AgentAction
• Log interventions                   • create_support_request()
• Mark cases recovered                • Any financial submission
```

Sensitive actions are created as `AgentAction(status="pending")`. Nothing is submitted until the user explicitly clicks Approve.

---

## Recovery Workflow (Track 03)

```
                    ┌─────────────────────┐
                    │  get_cases_at_risk() │
                    │  status IN           │
                    │  (needs_attention,   │
                    │   action_required)   │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ should_stop_recovery │
                    │  ┌────────────────┐  │
                    │  │ resolved?  →stop│  │
                    │  │ attempts≥3?→stop│  │
                    │  │ escalated? →stop│  │
                    │  └────────────────┘  │
                    └──────┬──────┬────────┘
                        stop│     │proceed
                            │     │
                            ▼     ▼
                         skip  get_next_channel()
                               (email→sms→whatsapp)
                                    │
                               trigger_recovery()
                               • generate rzp payment link
                               • craft message (Hinglish if mobile)
                               • log RecoveryIntervention
                                    │
                              ┌─────▼──────────┐
                              │ attempts >= 3? │
                              └─────┬────┬─────┘
                                 yes│    │no
                                    │    └──→ wait for outcome
                                    ▼
                              escalate_case()
                              • create AgentAction(pending)
                              • log escalation intervention
                                    │
                              user approves?
                                    │
                              ┌─────▼─────┐
                              │ Dispute   │
                              │ submitted │
                              └───────────┘
```

---

## Data Models

```
User
 └── Transaction (razorpay_payment_id, amount, merchant, status)
      └── PaymentCase (health_score, status, risk_level, case_type)
           ├── Event[] (event_type, event_data, timestamp)
           ├── AgentAction[] (action, reason, status, approved_by_user)
           └── RecoveryIntervention[] (type, channel, attempt, outcome, amount_recovered)
                └── RecoveryBatch (total_cases, recovered_cases, amount_at_risk, amount_recovered)
```

---

## Health Score Formula

```
Base: 100

Deductions:
  payment_failed          -50   suspicious_activity     -55
  delivery_delayed        -25   order_cancelled         -25
  refund_delayed          -35   merchant_unresponsive   -15
  dispute_opened          -10

Bonuses:
  order_confirmed         +5    delivery_completed      +10
  refund_completed        +15   dispute_resolved        +10
  support_contacted       +2

Clamped to [0, 100]

Thresholds:
  80–100 → Healthy       (status: monitoring,       risk: low)
  50–79  → Needs Attention (status: needs_attention, risk: medium)
  0–49   → Action Required (status: action_required, risk: high)
```

Every deduction has a human-readable reason string — the score is never an unexplained number.

---

## Batch Recovery Flow

```
POST /api/recovery/batch
        │
        ▼
  Create RecoveryBatch record (status: running)
        │
        ▼
  get_cases_at_risk() → all needs_attention + action_required
        │
        ├── for each case:
        │     ├── should_stop_recovery() → skip if stopped
        │     ├── get_intervention_count()
        │     │     ├── count >= 2 → escalate_case()
        │     │     └── count < 2  → trigger_recovery()
        │     └── simulate outcome (25% recovery rate for demo)
        │           └── recovered → mark_recovered() → case resolved
        │
        ▼
  Update RecoveryBatch (status: completed, metrics)
        │
        ▼
  Return: {batch_id, metrics{cases, recovered, rate, amounts}, results[]}
```

---

## Tool Registry (14 tools)

| Tool | Category | Description |
|------|----------|-------------|
| `get_transaction` | Lookup | Transaction details |
| `get_order_status` | Lookup | Order confirmed/delayed/delivered |
| `get_refund_status` | Lookup | Refund initiated/delayed/completed |
| `get_merchant_details` | Lookup | Merchant responsiveness |
| `get_delivery_status` | Lookup | Delivery tracking |
| `calculate_payment_health` | Analysis | Score + breakdown |
| `get_recovery_status` | Recovery | All interventions + stop check |
| `trigger_recovery` | Recovery | Send payment link via next channel |
| `escalate_case` | Recovery | Prepare dispute (pending approval) |
| `log_recovery_intervention` | Recovery | Log manual intervention |
| `mark_recovered` | Recovery | Mark case resolved + log outcome |
| `create_support_request` | Action | Create support ticket (pending) |
| `prepare_dispute` | Action | Prepare dispute (pending) |
| `get_recurring_payments` | Lookup | Subscription data |

---

## Engineering Notes

**Python 3.14 compatibility** — `pydantic>=2.10.0` needed for pre-built wheel; pinned older versions fail.

**Groq model availability** — `llama-3.3-70b-versatile` not available on free tier; using `openai/gpt-oss-120b`.

**Batch recovery performance** — original design called LLM per case (timed out at 120s for 27 cases). Redesigned as rule-based with LLM only for single-case investigation queries. Batch now completes in ~1s.

**SQLite concurrency** — `check_same_thread=False` required for FastAPI's async request handling.
