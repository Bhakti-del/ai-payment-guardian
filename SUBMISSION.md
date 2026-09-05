# Submission — AI Payment Guardian
### Razorpay AI Buildathon 2026 · Track 03: AI Revenue Recovery

---

## What I Built

**AI Payment Guardian** is a production-ready agentic revenue recovery system that:

1. **Detects** payments at risk using a deterministic health scoring engine (50 seeded cases across 6 real failure scenarios)
2. **Diagnoses** root cause via an AI agent with tool calling — never guessing, only using real data
3. **Executes** a bounded recovery workflow: email → SMS → WhatsApp (Hinglish for mobile), with a **real Razorpay payment link** every time (via the Payment Links API — falls back to a clearly-labeled simulated link only when test keys are absent)
4. **Enforces** hard stopping rules — max 3 interventions per case, max 1 escalation, never chasing after a dispute is filed
5. **Measures** outcomes — money recovered, recovery rate, full intervention audit trail per batch run

---

## The Problem I'm Solving

Every payment platform tells you if a payment succeeded. Nobody tells you what happened after.

- Subscription fails silently → merchant loses the revenue, customer churns
- Refund gets stuck → customer contacts support, raises disputes, leaves bad reviews
- Delivery goes overdue → merchant unresponsive → customer has no recourse

These failures compound. A single delayed delivery + unresponsive merchant + stuck refund = a lost customer and a potential chargeback. **The window to recover is small — usually 3–7 days — and every hour of inaction loses money.**

---

## Why AI, Not Just Rules

The recovery workflow itself is rule-based (deterministic stopping rules, channel order, health scoring). The AI handles what rules can't:

- **Natural language diagnosis** — "Why hasn't my refund arrived?" gets a real answer with actual data, not a template
- **Context-aware messaging** — the agent crafts recovery messages appropriate to the case type, amount, and merchant history
- **Tool-calling investigation** — the agent calls up to 6 tools per query to build a complete picture before responding
- **Human-readable explanations** — every health score deduction has a plain English reason

---

## Live Demo Script (5 minutes)

**Minute 1 — The problem**
- Open the frontend, go to **⚡ Recovery** tab
- Show the metrics: X cases at risk, ₹Y at risk
- Point to the **Action Required** group in the sidebar (Unknown Merchant suspicious transactions)
- Click one — show the health score breakdown (score 45: suspicious activity -55, payment success +10)

**Minute 2 — The AI agent**
- Click a delayed order case (score 65, Needs Attention)
- Type: *"What happened with this payment and what should I do?"*
- Watch the agent call tools in real time (get_transaction → get_order_status → calculate_payment_health)
- Show the response: plain language explanation + recommended action

**Minute 3 — Recovery intervention**
- Click *"What to do?"* quick button
- Agent calls `trigger_recovery()` — show the Hinglish SMS message + payment link generated
- Show the audit entry in the Recovery tab

**Minute 4 — Stopping rules**
- Ask the agent: *"Prepare a dispute request for this case"*
- Show `escalate_case()` creates a **Pending Action** — not auto-submitted
- Approve it → show status changes to approved
- Try asking again → agent is stopped (MAX_ESCALATIONS=1 rule blocks it)

**Minute 5 — Batch recovery + metrics**
- Go to **⚡ Recovery** tab
- Click **Run Batch Recovery** — completes in ~1 second
- Show the banner: X cases processed, Y recovered, ₹Z recovered, W% rate
- Scroll to audit trail — every intervention logged with channel, message, outcome

---

## The Bar (Track 03 Requirements)

| Requirement | How I met it |
|---|---|
| Detect revenue at risk | Health score engine flags all cases < 80 as at-risk |
| Determine right intervention | Agent diagnoses case type, picks channel, crafts message |
| Execute bounded recovery workflow | trigger_recovery() → escalate_case() → pending approval |
| Payment failures | 8 seeded failed subscription cases |
| Checkout abandonment | Razorpay order creation → monitoring starts immediately |
| Overdue receivables | 10 delayed order + 10 stuck refund cases |
| Measured money recovered across a batch | /api/recovery/batch returns exact metrics per run |
| Compliant escalation | email → sms → whatsapp order, 1 escalation max |
| Stopping rules | MAX_INTERVENTIONS=3, MAX_ESCALATIONS=1, enforced before every action |
| Audit trail | RecoveryIntervention table, /api/recovery/audit endpoint |

---

## Architecture (30-second version)

```
50 cases → health score → at-risk flagged
                                │
                         stopping rules check
                                │
                    trigger_recovery() → payment link + message
                         (email→sms→whatsapp, Hinglish on mobile)
                                │
                         log RecoveryIntervention
                                │
                    3 failures? → escalate_case() → pending approval
                                │
                         measure: recovered / rate / audit
```

Full architecture: [docs/architecture.md](docs/architecture.md)

---

## What I'd Do Next (with more time)

- **Real Razorpay webhook integration** — replace simulated events with live `payment.failed`, `refund.created` webhooks
- **Real checkout flow** — wire `/api/razorpay/create-order` to a live Razorpay Order/Checkout (it currently simulates a successful payment)
- **Mandate retry sequencer** — intelligent retry timing for subscription failures (not just immediate retry)
- **Promise-to-pay tracker** — if customer says "I'll pay by Friday", schedule a follow-up
- **Voice recovery** — Hinglish voice call for high-value cases using a TTS API
- **A/B test recovery messages** — track which message variants convert better across channels

---

## Repo

[github.com/YOUR_USERNAME/ai-payment-guardian](https://github.com/YOUR_USERNAME/ai-payment-guardian)

---

## Contact

Built by Bhakti for the Razorpay AI Buildathon 2026.
