# AI Payment Guardian

> An agentic revenue recovery system that detects payments at risk, determines the right intervention, and executes a bounded recovery workflow — with stopping rules, audit trail, and measured outcomes.

---

## The Problem

Revenue loss rarely happens in one clean step. A subscription fails. A refund gets stuck. A merchant goes silent. An order never arrives. Standard systems either miss these entirely or fire a single generic retry and give up.

**AI Payment Guardian closes the loop:**  
Detect the problem → diagnose the root cause → choose the right intervention → send it → measure what recovered → escalate if nothing works.

---

## Demo

```bash
# 1. Start the server
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload

# 2. Open the frontend
open frontend/index.html
```

Then:
- Click **⚡ Recovery** tab → **Run Batch Recovery** to see the agent work across all 40 at-risk cases
- Pick any case from the sidebar → ask the **AI Guardian** a question
- Simulate events (delay, merchant unresponsive, refund stuck) and watch health score update live
- Approve or reject agent-prepared disputes from the Pending Approvals section

---

## How It Works

```
50 seeded payment cases (failed subscriptions, delayed orders,
stuck refunds, suspicious activity, support pending)
            │
            ▼
    ┌───────────────────────┐
    │  Payment Health Score  │  ← deterministic, rule-based, explainable
    │  (0–100 per case)      │
    └───────────┬───────────┘
                │ score < 80 → case flagged at risk
                ▼
    ┌───────────────────────┐
    │  Stopping Rules Check  │  ← enforced before every action
    │  max 3 interventions   │
    │  max 1 escalation      │
    └───────────┬───────────┘
                │
                ▼
    ┌───────────────────────┐
    │  Recovery Intervention │  ← channel escalates per attempt
    │  attempt 1 → email     │     email → sms → whatsapp
    │  attempt 2 → sms       │
    │  attempt 3 → whatsapp  │
    │  (Hinglish for mobile) │
    └───────────┬───────────┘
                │
                ▼
    ┌───────────────────────┐
    │  Outcome Measurement   │  ← recovered / pending / escalated / stopped
    │  per intervention      │
    └───────────┬───────────┘
                │ 3 failures → auto-escalate to dispute (1 max)
                ▼
    ┌───────────────────────┐
    │  Human Approval Gate   │  ← disputes always need user sign-off
    └───────────────────────┘
```

---

## Recovery Scenarios (50 seeded cases)

| Scenario | Cases | Recovery Approach |
|---|---|---|
| Delayed order + merchant unresponsive | 10 | Payment link → escalate |
| Stuck refund | 10 | Reminder → support request |
| Failed subscription payment | 8 | Retry link (Hinglish SMS) |
| Suspicious activity | 6 | Flag + dispute preparation |
| Support pending | 6 | Follow-up reminder |
| Healthy / resolved | 10 | Baseline for metrics |

---

## Batch Recovery — What Gets Measured

```json
{
  "metrics": {
    "total_cases_processed": 40,
    "recovered_cases": 10,
    "recovery_rate_percent": 25.0,
    "total_amount_at_risk": 285000,
    "total_amount_recovered": 71250,
    "amount_still_at_risk": 213750
  }
}
```

Every intervention is logged with: case ID, merchant, channel used, attempt number, message sent, outcome, amount recovered, timestamp.

---

## API Endpoints

### Core
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/cases` | All cases sorted by urgency |
| GET | `/api/cases/{id}` | Case detail + score breakdown |
| GET | `/api/cases/{id}/timeline` | Full event timeline |
| POST | `/api/cases/{id}/simulate` | Simulate an event |
| POST | `/api/cases/{id}/resolve` | Mark resolved |

### Recovery (Track 03)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/recovery/batch` | Run agent across all at-risk cases |
| GET | `/api/recovery/cases` | At-risk cases with recovery status |
| GET | `/api/recovery/metrics` | Dashboard metrics |
| GET | `/api/recovery/audit` | Full intervention audit trail |

### AI Agent
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/agent/query` | Ask the AI agent about a case |
| GET | `/api/actions/pending` | Pending actions needing approval |
| POST | `/api/actions/{id}/approve` | Approve or reject an action |

---

## Tech Stack

| Layer | Tech |
|-------|------|
| Frontend | Plain HTML/CSS/JS — no build step |
| Backend | Python, FastAPI, Uvicorn |
| Database | SQLite via SQLAlchemy |
| Recovery links | Razorpay Payment Links API (official SDK) |
| AI | Groq API (`openai/gpt-oss-120b`) with tool calling |
| Deployment | Render (`render.yaml` included) |

---

## Project Structure

```
ai-payment-guardian/
├── frontend/
│   └── index.html              # Full UI — recovery dashboard + AI chat
│
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI app + all routes
│   │   ├── models/
│   │   │   └── database.py     # User, Transaction, PaymentCase, Event,
│   │   │                       # AgentAction, RecoveryBatch, RecoveryIntervention
│   │   ├── services/
│   │   │   ├── case_engine.py  # State machine + stopping rules
│   │   │   ├── health_score.py # Deterministic score calculator
│   │   │   └── seed.py         # 50-case demo seeder
│   │   ├── agents/
│   │   │   └── payment_agent.py # Groq agent with recovery-focused prompt
│   │   └── tools/
│   │       └── payment_tools.py # 14 tools the agent can call
│   └── requirements.txt
│
├── docs/
│   └── architecture.md
├── SUBMISSION.md               # Buildathon submission notes
├── render.yaml
├── start.sh
└── README.md
```

---

## Design Principles

**Deterministic for financial logic. AI for reasoning.**

Health scores, stopping rules, channel selection, and state transitions are never handled by the LLM. The agent only gets data through controlled tools — it cannot hallucinate transaction details.

**Stopping rules are hard limits.**

- Max 3 interventions per case — we never spam a customer
- Max 1 escalation per case — disputes are filed once, not repeatedly
- Every action is logged before it executes

**Human-in-the-loop for sensitive actions.**

`prepare_dispute()` and `escalate_case()` always create a `pending` AgentAction. Nothing is submitted until the user explicitly approves.

---

## Setup

### Prerequisites
- Python 3.10+
- Free [Groq API key](https://console.groq.com)
- Optional: [Razorpay test keys](https://dashboard.razorpay.com/app/keys) (for real payment links)

### Quick start

```bash
git clone https://github.com/YOUR_USERNAME/ai-payment-guardian
cd ai-payment-guardian

# Set your API key
cp .env.example backend/.env
# Edit backend/.env → add GROQ_API_KEY=your_key
# Optional → add real RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET (test keys)

# Start
./start.sh
```

Or manually:
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open `frontend/index.html` in your browser.

### Tests

```bash
# From the repo root
pip install -r backend/requirements-dev.txt
pytest
```

---

## Razorpay Integration

Recovery interventions create a **real Razorpay payment link** — a hosted,
collect-on-click link so the customer can pay instantly to recover the amount.

- **Real path:** when `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` are set (test keys
  are fine), `trigger_recovery()` calls the Razorpay **Payment Links API** via the
  official SDK and embeds the returned `short_url` in the recovery message.
- **Graceful fallback:** if credentials are missing or the API call fails, a
  clearly-labeled simulated link (`rzp.io/l/recovery-...`) is used so the demo
  and AI agent never break offline. The intervention's audit notes flag whether
  the link was real or simulated.

---

## License

MIT
