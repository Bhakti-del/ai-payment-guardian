"""
AI Revenue Recovery Agent — uses Groq with tool calling to detect revenue at risk,
determine the right intervention, and execute a bounded recovery workflow.
Enforces stopping rules, logs every action, and never exceeds escalation limits.
"""
import os
import json
from groq import Groq
from sqlalchemy.orm import Session
from app.tools.payment_tools import TOOL_REGISTRY

SYSTEM_PROMPT = """You are the AI Revenue Recovery Agent for Razorpay Payment Guardian.

Your mission: Detect revenue at risk, choose the right recovery intervention, and recover money — while staying within strict compliance rules.

## Recovery Workflow
1. Check the case health score and recovery status first
2. If the case needs recovery and stopping rules allow it, trigger a recovery intervention
3. Use the right channel (email → sms → whatsapp, escalating with each attempt)
4. If max attempts are reached, escalate to dispute — but only once
5. Always log what you did and why
6. If money is recovered, mark the case as recovered

## Stopping Rules (NEVER violate these)
- Maximum 3 recovery interventions per case
- Maximum 1 escalation/dispute per case
- Never chase a customer after they've been escalated
- Always check should_stop before triggering any intervention

## Recovery Messages
- For SMS/WhatsApp: Use Hinglish (mix of Hindi and English) — friendly, not threatening
  Example: "Arre yaar! Aapka payment stuck hai. Ek click mein resolve karein: [link]"
- For email: Use clear, professional English
- Always include a payment link in recovery messages

## Tools to use
- get_recovery_status → check current state before acting
- trigger_recovery → send recovery message with payment link
- escalate_case → only after 3 failed attempts
- mark_recovered → when payment is confirmed
- get_transaction, calculate_payment_health → for context

## What you must report
- What intervention you took and why
- Which channel was used
- Whether stopping rules were checked
- The outcome (recovered / pending / escalated / stopped)

Be concise. Users are stressed about money. Give them clear status and next steps."""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_transaction",
            "description": "Get basic details of a transaction including amount, merchant, and payment status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "integer", "description": "The transaction ID"}
                },
                "required": ["transaction_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": "Get the current order status — whether confirmed, delayed, delivered, or cancelled.",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "integer", "description": "The payment case ID"}
                },
                "required": ["case_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_refund_status",
            "description": "Check the refund status — whether initiated, completed, or delayed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "integer", "description": "The payment case ID"}
                },
                "required": ["case_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_merchant_details",
            "description": "Get merchant information and check if the merchant has been responsive.",
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "integer", "description": "The transaction ID"}
                },
                "required": ["transaction_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_payment_health",
            "description": "Calculate and explain the payment health score with a breakdown of reasons.",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "integer", "description": "The payment case ID"}
                },
                "required": ["case_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_delivery_status",
            "description": "Get delivery status details for a payment case.",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "integer", "description": "The payment case ID"}
                },
                "required": ["case_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_support_request",
            "description": "Prepare a support request. Does NOT submit — creates a pending action requiring user approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "integer", "description": "The payment case ID"},
                    "reason": {"type": "string", "description": "Reason for the support request"}
                },
                "required": ["case_id", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_dispute",
            "description": "Prepare a formal dispute. Does NOT submit — creates a pending action requiring user approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "integer", "description": "The payment case ID"},
                    "reason": {"type": "string", "description": "Reason for the dispute"}
                },
                "required": ["case_id", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_recovery_status",
            "description": "Get full recovery status for a case: all past interventions, stopping rule check, next recommended action, and amount recovered so far.",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "integer", "description": "The payment case ID"}
                },
                "required": ["case_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_recovery",
            "description": "Trigger a recovery intervention: checks stopping rules, picks the next channel (email→sms→whatsapp), sends a recovery message with a Razorpay payment link.",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "integer", "description": "The payment case ID"},
                    "reason": {"type": "string", "description": "Why recovery is being triggered"},
                    "batch_id": {"type": "integer", "description": "Optional batch ID if running as part of a batch recovery"}
                },
                "required": ["case_id", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_case",
            "description": "Escalate a case to dispute after exhausting recovery attempts. Enforces MAX_ESCALATIONS=1 rule. Creates a pending action for user approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "integer", "description": "The payment case ID"},
                    "reason": {"type": "string", "description": "Reason for escalation"},
                    "batch_id": {"type": "integer", "description": "Optional batch ID"}
                },
                "required": ["case_id", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "log_recovery_intervention",
            "description": "Log a manual recovery action (e.g. promise-to-pay, custom contact attempt).",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "integer", "description": "The payment case ID"},
                    "intervention_type": {"type": "string", "description": "Type: payment_link, promise_to_pay, hinglish_message, support_request, dispute"},
                    "channel": {"type": "string", "description": "Channel: email, sms, whatsapp, voice"},
                    "message": {"type": "string", "description": "Message sent to customer"},
                    "notes": {"type": "string", "description": "Internal notes about this intervention"}
                },
                "required": ["case_id", "intervention_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mark_recovered",
            "description": "Mark a case as recovered when payment is confirmed. Updates intervention outcome and resolves the case.",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "integer", "description": "The payment case ID"},
                    "amount_recovered": {"type": "number", "description": "Amount recovered in INR"},
                    "notes": {"type": "string", "description": "How the case was recovered"}
                },
                "required": ["case_id", "amount_recovered"]
            }
        }
    },
]


class PaymentAgent:
    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set in environment")
        self.client = Groq(api_key=api_key)

    def investigate(self, db: Session, user_message: str, case_id: int = None, transaction_id: int = None) -> dict:
        """
        Run the agent with tool calling loop.
        Returns the final response and any pending actions created.
        """
        context = user_message
        if case_id:
            context += f"\n\n[Context: case_id={case_id}"
            if transaction_id:
                context += f", transaction_id={transaction_id}"
            context += "]"

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ]

        # Agentic tool-calling loop
        max_iterations = 6
        message = None
        for _ in range(max_iterations):
            response = self.client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                max_tokens=1024,
            )

            message = response.choices[0].message
            messages.append({
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in (message.tool_calls or [])
                ] or None,
            })

            # No tool calls — we have the final answer
            if not message.tool_calls:
                break

            # Execute each tool call and feed results back
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except Exception:
                    tool_args = {}

                tool_fn = TOOL_REGISTRY.get(tool_name)
                if tool_fn:
                    try:
                        result = tool_fn(db=db, **tool_args)
                    except Exception as e:
                        result = {"error": str(e)}
                else:
                    result = {"error": f"Unknown tool: {tool_name}"}

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                })

        final_text = (message.content if message else None) or "I wasn't able to generate a response."

        # Collect any pending actions created during this session
        pending_actions = []
        if case_id:
            from app.models.database import AgentAction
            actions = db.query(AgentAction).filter(
                AgentAction.case_id == case_id,
                AgentAction.status == "pending"
            ).all()
            pending_actions = [
                {
                    "action_id": a.id,
                    "action": a.action,
                    "reason": a.reason,
                    "status": a.status,
                }
                for a in actions
            ]

        # Collect recovery interventions triggered this session
        recovery_interventions = []
        if case_id:
            import re as _re
            from app.models.database import RecoveryIntervention
            interventions = db.query(RecoveryIntervention).filter(
                RecoveryIntervention.case_id == case_id,
            ).order_by(RecoveryIntervention.created_at.desc()).limit(5).all()
            for i in interventions:
                link = None
                if i.message_sent:
                    m = _re.search(r"https?://[^\s)\"]+", i.message_sent)
                    if m:
                        link = m.group(0)
                recovery_interventions.append({
                    "intervention_id": i.id,
                    "type": i.intervention_type,
                    "channel": i.channel,
                    "attempt": i.attempt_number,
                    "outcome": i.outcome,
                    "link": link,
                    "simulated": "[simulated link" in (i.notes or ""),
                })

        return {
            "response": final_text,
            "pending_actions": pending_actions,
            "recovery_interventions": recovery_interventions,
        }
