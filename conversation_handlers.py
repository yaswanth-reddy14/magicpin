"""
conversation_handlers.py — Multi-turn conversation state machine for Vera-Next.
This is the optional bonus module. Implements the full conversation flow including:
- Auto-reply detection + graceful exit
- Intent transition (accept → immediate action, no re-qualifying)
- Multi-turn cadence planning
- Language detection per turn
- Graceful exit after 3 unanswered nudges or 5 turns
"""

from typing import Optional
from dataclasses import dataclass, field
from enum import Enum
import re

# ── Import the respond function from bot.py ──
from bot import respond


class Intent(Enum):
    ACCEPT = "accept"
    DECLINE = "decline"
    AUTO_REPLY = "auto_reply"
    QUESTION = "question"
    WAIT = "wait"
    COMPLAINT = "complaint"
    CURVEBALL = "curveball"
    INTENT_TRANSITION = "intent_transition"


@dataclass
class ConversationState:
    """
    Full conversation state passed between turns.
    """
    conversation_id: str
    merchant_id: str
    merchant: dict
    category: dict
    trigger: dict
    customer: Optional[dict] = None

    # Conversation tracking
    conversation_history: list = field(default_factory=list)
    turn_number: int = 0
    auto_reply_count: int = 0
    unanswered_nudges: int = 0
    intent_detected: Optional[str] = None
    language_detected: str = "hi-en"  # default
    status: str = "active"  # active | waiting | ended


# ── Local intent detection (fast, no API call needed for clear cases) ──

ACCEPT_PATTERNS = [
    r"\b(yes|haan|ha|okay|ok|sure|chalega|chal|theek hai|kar do|start karo|go ahead|done|bhej|bhejdo|proceed|ready|karo|karein)\b",
    r"\b(let['']?s? do it|sounds good|great|perfect|absolutely|definitely|of course)\b",
]

DECLINE_PATTERNS = [
    r"\b(no|nahi|nope|not interested|band karo|stop|unsubscribe|mat karo|rehne do|nahi chahiye|not now)\b",
    r"\b(don['']?t|do not|please stop)\b",
]

INTENT_TRANSITION_PATTERNS = [
    r"\b(join|judrna|judna|signup|register|join karna|magicpin join|membership lena|subscribe)\b",
    r"\b(let['']?s? start|abhi shuru|start karo aaj|haan karo|haan chal)\b",
]

WAIT_PATTERNS = [
    r"\b(baad mein|later|kal|agle hafte|next week|busy hoon|abhi nahi|thodi der mein|give me time|will call you)\b",
]

AUTO_REPLY_PHRASES = [
    "thank you for contacting",
    "i am not available",
    "i am away",
    "automated response",
    "our team will get back",
    "will get back to you",
    "aapki jaankari ke liye",
    "bahut-bahut shukriya",
    "main ek automated",
    "this is an automated",
    "i'll get back",
    "i will get back",
    "please leave a message",
    "currently unavailable",
]


def detect_intent(message: str) -> Intent:
    """Fast local intent detection for clear-cut cases."""
    msg_lower = message.lower().strip()

    # Auto-reply check first (most important)
    if any(phrase in msg_lower for phrase in AUTO_REPLY_PHRASES):
        return Intent.AUTO_REPLY

    # Intent transition (highest priority after auto-reply)
    for pattern in INTENT_TRANSITION_PATTERNS:
        if re.search(pattern, msg_lower):
            return Intent.INTENT_TRANSITION

    # Accept
    for pattern in ACCEPT_PATTERNS:
        if re.search(pattern, msg_lower):
            return Intent.ACCEPT

    # Decline
    for pattern in DECLINE_PATTERNS:
        if re.search(pattern, msg_lower):
            return Intent.DECLINE

    # Wait
    for pattern in WAIT_PATTERNS:
        if re.search(pattern, msg_lower):
            return Intent.WAIT

    return Intent.CURVEBALL


def detect_language(message: str) -> str:
    """Detect if message is predominantly Hindi, English, or mixed."""
    # Simple heuristic: count Devanagari chars vs Latin chars
    devanagari = sum(1 for c in message if '\u0900' <= c <= '\u097f')
    latin = sum(1 for c in message if c.isascii() and c.isalpha())
    total = devanagari + latin
    if total == 0:
        return "hi-en"
    ratio = devanagari / total
    if ratio > 0.7:
        return "hi"
    elif ratio < 0.2:
        return "en"
    return "hi-en"


def handle_turn(state: ConversationState, merchant_message: str) -> dict:
    """
    Main entry point for multi-turn handling.
    Returns a response dict: {action, body?, cta?, wait_seconds?, rationale}

    This function:
    1. Detects intent locally for fast routing
    2. Handles clear-cut cases (double auto-reply, accept, decline) directly
    3. Falls through to LLM for ambiguous cases (questions, complaints, curveballs)
    """
    state.turn_number += 1
    state.conversation_history.append({"from": "merchant", "body": merchant_message})
    state.language_detected = detect_language(merchant_message)

    intent = detect_intent(merchant_message)
    state.intent_detected = intent.value

    # ── Hard exits ──
    if state.status == "ended":
        return {"action": "end", "rationale": "Conversation already ended."}

    if state.turn_number > 5:
        state.status = "ended"
        return {
            "action": "end",
            "rationale": "5-turn limit reached. Gracefully exiting.",
        }

    # ── Auto-reply detection ──
    if intent == Intent.AUTO_REPLY:
        state.auto_reply_count += 1
        if state.auto_reply_count >= 2:
            state.status = "ended"
            return {
                "action": "end",
                "rationale": "Second auto-reply detected. Exiting to avoid wasting turns.",
            }
        # First auto-reply: try to pierce once
        merchant_name = state.merchant.get("identity", {}).get("owner_first_name", "")
        merchant_biz = state.merchant.get("identity", {}).get("name", "")
        pierce_body = f"Samajh gayi — yeh response automated lag raha hai. {merchant_name} ji ya koi aur team member hai jo 2 min mein dekh sake {merchant_biz} ke baare mein ek quick update ke liye?"
        state.conversation_history.append({"from": "vera", "body": pierce_body})
        return {
            "action": "send",
            "body": pierce_body,
            "cta": "open_ended",
            "rationale": "First auto-reply detected. Attempting single pierce to reach real person.",
        }

    # ── Decline ──
    if intent == Intent.DECLINE:
        state.status = "ended"
        cat = state.category.get("slug", "")
        if cat == "dentists":
            exit_body = "Bilkul samajh gayi, Doc. Koi baat nahi — aapki practice kaafi strong hai. Kisi cheez mein help chahiye toh batayein. Best wishes! 🙂"
        elif cat == "salons":
            exit_body = "Theek hai, koi problem nahi! Studio ki team achhi kaam kar rahi hai. Kabhi zaroorat ho toh hum yahan hain. 🙂"
        else:
            exit_body = "Understood, koi baat nahi. Kabhi zaroorat ho toh hum available hain. Best wishes! 🙂"
        state.conversation_history.append({"from": "vera", "body": exit_body})
        return {
            "action": "end",
            "rationale": "Merchant declined. Graceful category-appropriate exit.",
        }

    # ── Wait ──
    if intent == Intent.WAIT:
        state.conversation_history.append({"from": "vera", "body": ""})
        return {
            "action": "wait",
            "wait_seconds": 3600,
            "rationale": "Merchant asked for time. Backing off 1 hour.",
        }

    # ── Intent transition: merchant wants to join / take action ──
    if intent == Intent.INTENT_TRANSITION:
        cat = state.category.get("slug", "")
        name = state.merchant.get("identity", {}).get("owner_first_name", "")
        transition_body = f"{name} ji, perfect — let's get started right away! Main aapke liye onboarding steps taiyaar kar raha hoon. Pehla step: aapka phone number confirm karna aur Google Business Profile link karna. Ek second..."
        state.conversation_history.append({"from": "vera", "body": transition_body})
        state.intent_detected = "intent_transition_actioned"
        return {
            "action": "send",
            "body": transition_body,
            "cta": "none",
            "rationale": "Intent transition detected. Skipped qualification, moved directly to onboarding action.",
        }

    # ── Accept ──
    if intent == Intent.ACCEPT:
        # Call LLM to honor the accept and do the actual work
        result = respond(state.__dict__, merchant_message)
        if result.get("action") == "send" and result.get("body"):
            state.conversation_history.append({"from": "vera", "body": result["body"]})
        state.unanswered_nudges = 0
        return result

    # ── All other cases (question, complaint, curveball) → LLM ──
    result = respond(state.__dict__, merchant_message)
    if result.get("action") == "send" and result.get("body"):
        state.conversation_history.append({"from": "vera", "body": result["body"]})
    if result.get("action") == "end":
        state.status = "ended"

    # Track unanswered nudges
    if result.get("action") == "send":
        state.unanswered_nudges += 1
    else:
        state.unanswered_nudges = 0

    if state.unanswered_nudges >= 3:
        state.status = "ended"
        return {
            "action": "end",
            "rationale": "3 unanswered nudges. Gracefully exiting to avoid spam.",
        }

    return result


# ── Example usage / quick test ──
if __name__ == "__main__":
    import json

    # Simulate a conversation
    state = ConversationState(
        conversation_id="conv_test_001",
        merchant_id="m_001_drmeera_dentist_delhi",
        merchant={
            "identity": {"name": "Dr. Meera's Dental Clinic", "owner_first_name": "Meera", "city": "Delhi", "languages": ["en", "hi"]},
            "subscription": {"status": "active", "days_remaining": 82},
            "performance": {"views": 2410, "calls": 18, "ctr": 0.021},
            "offers": [{"title": "Dental Cleaning @ ₹299", "status": "active"}],
            "signals": ["stale_posts:22d", "ctr_below_peer_median"],
        },
        category={"slug": "dentists", "voice": {"tone": "peer_clinical"}},
        trigger={"kind": "research_digest", "urgency": 2},
        conversation_history=[
            {"from": "vera", "body": "Dr. Meera, JIDA Oct issue aaya — 2,100-patient trial shows 3-month fluoride recall cuts caries 38% better. Want me to draft a patient-ed WhatsApp?"}
        ],
        turn_number=1,
    )

    # Test: Accept
    resp = handle_turn(state, "Yes please, do it!")
    print(f"Turn {state.turn_number} (accept): action={resp['action']}")
    if resp.get("body"):
        print(f"  Body: {resp['body'][:100]}...")

    # Test: Auto-reply
    state2 = ConversationState(
        conversation_id="conv_test_002",
        merchant_id="m_003_studio11_salon_hyderabad",
        merchant={"identity": {"name": "Studio11", "owner_first_name": "Lakshmi", "city": "Hyderabad", "languages": ["en", "hi", "te"]}, "offers": [], "signals": [], "performance": {}},
        category={"slug": "salons"},
        trigger={"kind": "festival_upcoming"},
        conversation_history=[{"from": "vera", "body": "Diwali ke liye campaign draft karoon?"}],
        turn_number=1,
    )
    resp2 = handle_turn(state2, "Aapki jaankari ke liye bahut-bahut shukriya. Main aapki yeh sabhi baatein team tak pahuncha dungi.")
    print(f"\nTurn {state2.turn_number} (auto-reply 1): action={resp2['action']}")
    if resp2.get("body"):
        print(f"  Body: {resp2['body'][:100]}...")

    resp3 = handle_turn(state2, "Aapki jaankari ke liye bahut-bahut shukriya. Main ek automated assistant hoon.")
    print(f"Turn {state2.turn_number} (auto-reply 2): action={resp3['action']} (should be 'end')")
