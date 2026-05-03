"""
Vera-Next: magicpin AI Challenge Submission
Team: Vera-Next
Model: claude-sonnet-4-20250514 via Anthropic API
Approach: Trigger-dispatched prompt composer with structured context injection,
          voice-enforced generation, and multi-turn state machine.
"""

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import anthropic

# ── Anthropic client (no key needed — handled by env in challenge harness) ──
_client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-20250514"

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT — the soul of Vera-Next
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Vera-Next, an AI messaging assistant for magicpin merchants.
Your job: compose the single best WhatsApp message to send to a merchant (or their customer),
given structured context about their business, a trigger event, and category knowledge.

=== HARD RULES (violations → disqualification) ===
1. NEVER use vocab_taboo words from the category voice.
2. NEVER fabricate data — if a number/fact isn't in the provided context, don't invent it.
3. NEVER use generic "% off" framing — always use "Service @ ₹Price" format.
4. NEVER include multiple CTAs — exactly ONE call-to-action per message.
5. NEVER re-introduce yourself after turn 1 of a conversation.
6. NEVER write a preamble ("I hope you're doing well. I'm writing to…").
7. CTA must be the LAST sentence of the message.
8. Match the merchant's language_pref: hi-en mix → mix Hindi and English naturally.

=== VOICE BY CATEGORY ===
- dentists: peer_clinical — sound like a colleague, cite sources (JIDA, DCI), use clinical vocab
- salons: warm_practical — approachable, trend-forward, focus on bookings + revenue
- restaurants: conversational_energetic — local events, food-specific, occasion-driven
- gyms: motivational_practical — data on members, programs, retention
- pharmacies: regulatory_careful — compliance-first, never make health claims, citation required

=== COMPULSION LEVERS (use ≥1 per message) ===
1. Specificity/verifiability: concrete number, date, source citation
2. Loss aversion: "you're missing X" / "before this window closes"
3. Social proof: "N merchants in your locality did Y this month"
4. Effort externalization: "I've drafted X — just say YES to send"
5. Curiosity: "want to see who?" / "want the full breakdown?"
6. Reciprocity: "I noticed Y — thought you'd want to know"
7. Asking the merchant: a genuine question about their business
8. Single binary commitment: Reply YES / STOP (not multi-choice, except booking flows)

=== OUTPUT FORMAT ===
You MUST respond with ONLY valid JSON (no markdown, no preamble):
{
  "body": "<the WhatsApp message text>",
  "cta": "yes_stop" | "open_ended" | "none" | "booking_choice",
  "send_as": "vera" | "merchant_on_behalf",
  "suppression_key": "<string>",
  "rationale": "<1-2 sentences: why this message, what compulsion lever used>"
}"""

# ─────────────────────────────────────────────────────────────────────────────
# TRIGGER-KIND → PROMPT STRATEGY DISPATCHER
# ─────────────────────────────────────────────────────────────────────────────

TRIGGER_STRATEGIES = {
    "research_digest": "Lead with the clinical/research finding. Anchor on trial_n, source citation, patient_segment. CTA: curiosity + effort externalization ('Want me to draft a patient-ed WhatsApp?'). send_as: vera.",
    "regulation_change": "Frame as urgent compliance alert with deadline. Cite the regulatory body. Use loss aversion (deadline). send_as: vera. CTA: yes_stop.",
    "recall_due": "Customer-facing. Sent from merchant number. Use patient's name, exact months since last visit, TWO specific slot options. send_as: merchant_on_behalf. CTA: booking_choice.",
    "perf_dip": "Merchant-facing. Lead with the specific metric + % drop. Use loss aversion ('X calls lost vs last week'). Offer a concrete action. send_as: vera. CTA: yes_stop.",
    "perf_spike": "Celebratory + action-oriented. Cite the specific metric spike %. Ask 'want to capitalise on this momentum?' with a concrete next step. send_as: vera. CTA: yes_stop.",
    "renewal_due": "Urgency + value. Days_remaining is the hook. Cite what the merchant has achieved (views/calls) in the period. CTA: yes_stop. send_as: vera.",
    "festival_upcoming": "Tie festival to the category's natural seasonal beat. Suggest a specific offer from offer_catalog. Use social proof ('salons in your city are already booking for X'). CTA: yes_stop. send_as: vera.",
    "ipl_match_today": "Highly time-sensitive. Use match name + time as the hook. Tie to a specific food/drink offer. Loss aversion (tonight only). CTA: yes_stop. send_as: vera.",
    "review_theme_emerged": "Specific: cite the exact occurrences count and the common_quote. Frame as insight, not accusation. Offer to help address it. CTA: open_ended. send_as: vera.",
    "milestone_reached": "Celebrate + nudge next milestone. Cite the exact number. Use reciprocity. Add a small social proof or next-step CTA. send_as: vera. CTA: yes_stop.",
    "competitor_opened": "Careful — don't name the competitor. Frame as 'new option opened nearby' + differentiation angle. Use their strengths (rating, reviews, offers). CTA: yes_stop. send_as: vera.",
    "curious_ask_due": "A warm, genuine question about their business. No hard sell. Use lever #7 (asking the merchant). Short message. CTA: open_ended. send_as: vera.",
    "dormant_with_vera": "Re-engagement. Acknowledge the silence. Lead with ONE specific insight about their account (performance number or signal). CTA: yes_stop. send_as: vera.",
    "winback_eligible": "Lapsed merchant. Cite days since expiry + specific metric degradation. Use loss aversion. Offer a clear path back. CTA: yes_stop. send_as: vera.",
    "gbp_unverified": "Frame as missed opportunity with concrete number (views blocked, etc). Offer to walk them through verification step-by-step. CTA: yes_stop. send_as: vera.",
    "supply_alert": "Regulatory/compliance urgency. Cite the specific drug/product. Frame as patient safety. CTA: yes_stop. send_as: vera.",
    "chronic_refill_due": "Patient-facing reminder. Very brief, warm, specific service. send_as: merchant_on_behalf. CTA: booking_choice.",
    "category_seasonal": "Anticipatory framing — prepare for the seasonal shift. Tie to offer_catalog. CTA: yes_stop. send_as: vera.",
    "cde_opportunity": "Professional development angle. Cite the event/webinar. Peer tone. CTA: open_ended. send_as: vera.",
    "wedding_package_followup": "Customer-facing. Warm, specific to their wedding date. Tie to the next step in the bridal journey. send_as: merchant_on_behalf. CTA: open_ended.",
    "trial_followup": "Customer-facing post-trial. Warm. Specific to what they tried. Easy next step. send_as: merchant_on_behalf. CTA: yes_stop.",
    "active_planning_intent": "Merchant expressed intent. Move straight to action — skip qualifying. Offer to draft/execute the plan immediately. CTA: yes_stop. send_as: vera.",
    "seasonal_perf_dip": "Normalise the seasonal pattern + offer a specific counter-measure from the category playbook. CTA: yes_stop. send_as: vera.",
    "customer_lapsed_hard": "Customer win-back. Warm, not guilt-tripping. Lead with a specific incentive from catalog. CTA: yes_stop. send_as: merchant_on_behalf.",
}

DEFAULT_STRATEGY = "Compose the best possible message for this trigger. Use at least one compulsion lever. Anchor on verifiable facts from the context. CTA should match the trigger urgency."


def _build_compose_prompt(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None,
) -> str:
    strategy = TRIGGER_STRATEGIES.get(trigger.get("kind", ""), DEFAULT_STRATEGY)

    # Pull key merchant signals
    owner = merchant.get("identity", {}).get("owner_first_name", "")
    merchant_name = merchant.get("identity", {}).get("name", "")
    lang_pref = merchant.get("identity", {}).get("languages", ["en"])
    cat_slug = category.get("slug", "")
    peer_stats = category.get("peer_stats", {})
    
    # Conversation history for anti-repetition
    conv_history = merchant.get("conversation_history", [])
    recent_bodies = [c.get("body", "")[:100] for c in conv_history[-3:]]
    
    # Active offers
    active_offers = [o["title"] for o in merchant.get("offers", []) if o.get("status") == "active"]
    
    # Signals
    signals = merchant.get("signals", [])

    # Build context block
    ctx = {
        "CATEGORY": {
            "slug": cat_slug,
            "voice_tone": category.get("voice", {}).get("tone"),
            "voice_taboo": category.get("voice", {}).get("vocab_taboo", []),
            "offer_catalog": category.get("offer_catalog", [])[:5],
            "peer_stats": peer_stats,
            "digest_top3": category.get("digest", [])[:3],
            "seasonal_beats": category.get("seasonal_beats", []),
            "trend_signals": category.get("trend_signals", []),
        },
        "MERCHANT": {
            "name": merchant_name,
            "owner_first_name": owner,
            "city": merchant.get("identity", {}).get("city"),
            "locality": merchant.get("identity", {}).get("locality"),
            "language_pref": lang_pref,
            "subscription": merchant.get("subscription", {}),
            "performance_30d": merchant.get("performance", {}),
            "active_offers": active_offers,
            "signals": signals,
            "customer_aggregate": merchant.get("customer_aggregate", {}),
            "review_themes": merchant.get("review_themes", []),
            "recent_vera_messages": recent_bodies,
        },
        "TRIGGER": trigger,
    }
    
    if customer:
        ctx["CUSTOMER"] = {
            "name": customer.get("identity", {}).get("name"),
            "language_pref": customer.get("identity", {}).get("language_pref"),
            "state": customer.get("state"),
            "relationship": customer.get("relationship", {}),
            "preferences": customer.get("preferences", {}),
            "consent_scope": customer.get("consent", {}).get("scope", []),
        }

    prompt = f"""=== COMPOSITION TASK ===
Category: {cat_slug}
Merchant: {merchant_name} ({owner}), {merchant.get('identity',{}).get('city','')}
Trigger kind: {trigger.get('kind')} | Urgency: {trigger.get('urgency',2)}/5
{'Customer: ' + customer.get('identity',{}).get('name','') if customer else 'No customer context (merchant-facing)'}

=== STRATEGY FOR THIS TRIGGER KIND ===
{strategy}

=== FULL CONTEXT (use verifiable data from here, never invent) ===
{json.dumps(ctx, indent=2, ensure_ascii=False)}

=== ANTI-REPETITION CHECK ===
Recent messages sent (do NOT repeat these): {recent_bodies}

Compose the message now. Return ONLY valid JSON with keys: body, cta, send_as, suppression_key, rationale."""

    return prompt


def compose(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None,
) -> dict:
    """
    Core compose function.
    Returns: {body, cta, send_as, suppression_key, rationale}
    Guaranteed to return a dict with at least body, cta, send_as, suppression_key.
    """
    try:
        prompt = _build_compose_prompt(category, merchant, trigger, customer)

        response = _client.messages.create(
            model=MODEL,
            max_tokens=1000,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        # Strip any accidental markdown fences
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("` \n")

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            # Fallback: extract JSON block
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            result = json.loads(match.group()) if match else None
            
            if not result:
                # Last resort: create minimal response
                merchant_name = merchant.get("identity", {}).get("owner_first_name", "Merchant")
                trigger_kind = trigger.get("kind", "general")
                result = {
                    "body": f"Hi {merchant_name}, checking in about {trigger_kind} — let me know if helpful!",
                    "cta": "open_ended",
                    "send_as": "vera",
                    "rationale": "fallback"
                }

        # Ensure all required fields are present
        if not result.get("body"):
            merchant_name = merchant.get("identity", {}).get("owner_first_name", "Merchant")
            result["body"] = f"Hi {merchant_name}, I have an update for you. Let me know if you'd like to discuss!"
        
        if not result.get("cta"):
            result["cta"] = "open_ended"
        
        if not result.get("send_as"):
            result["send_as"] = "vera"

        # Ensure suppression_key is set
        if not result.get("suppression_key"):
            result["suppression_key"] = trigger.get("suppression_key", f"msg:{merchant.get('merchant_id','')}:{trigger.get('id','')}")

        return result
    
    except Exception as e:
        # Fallback response on any error
        merchant_name = merchant.get("identity", {}).get("owner_first_name", "Merchant")
        trigger_kind = trigger.get("kind", "general")
        return {
            "body": f"Hi {merchant_name}, I wanted to reach out about an update regarding {trigger_kind}. Are you available for a quick chat?",
            "cta": "yes_stop",
            "send_as": "vera",
            "suppression_key": trigger.get("suppression_key", f"msg:{merchant.get('merchant_id','')}:{trigger.get('id','')}"),
            "rationale": f"error fallback: {str(e)[:50]}"
        }


# ─────────────────────────────────────────────────────────────────────────────
# MULTI-TURN CONVERSATION HANDLER
# ─────────────────────────────────────────────────────────────────────────────

MULTI_TURN_SYSTEM = """You are Vera-Next, magicpin's merchant AI assistant. You are continuing a WhatsApp conversation.

=== CONVERSATION STATE MACHINE ===
Detect the merchant's intent from their reply and choose the right action:

INTENT DETECTION:
- AUTO_REPLY: Verbatim canned message (e.g., "Thank you for contacting", "I am not available"). → Try ONCE to pierce with a direct question, then EXIT if auto-reply again.
- ACCEPT: "yes", "haan", "sure", "chalega", "ok do it", "go ahead" → action=send, honor the commitment immediately, do the work.
- DECLINE: "no", "nahi", "not interested", "band karo" → action=end, graceful exit.
- QUESTION: Merchant asks something → action=send with a helpful, brief answer + guide back to original CTA.
- WAIT: Merchant says busy, call later → action=wait (1800-3600 seconds).
- COMPLAINT: Negative sentiment about magicpin/service → action=send, acknowledge + de-escalate, offer escalation path.
- CURVEBALL: Something unexpected → action=send, engage genuinely, brief response.
- INTENT_TRANSITION: "mujhe join karna hai", "let's do it", "start karo" → SKIP qualifying, go straight to action/next step.

=== HARD RULES ===
- If you already tried to pierce an auto-reply once, EXIT immediately on the second auto-reply.
- ACCEPT always → immediate execution / next step. Never ask qualifying questions after accept.
- Max 5 turns in any conversation. After 5 turns with no commitment, graceful exit.
- Keep replies SHORT (under 80 words) in turns 2+.
- Never re-introduce yourself.
- Match the merchant's language from their reply.

=== OUTPUT FORMAT ===
Return ONLY valid JSON:
{
  "action": "send" | "wait" | "end",
  "body": "<reply text, only if action=send>",
  "cta": "yes_stop" | "open_ended" | "none",
  "wait_seconds": <int, only if action=wait>,
  "rationale": "<1 sentence>"
}"""


def respond(state: dict, merchant_message: str) -> dict:
    """
    Multi-turn handler. state contains conversation history + merchant/category context.
    Returns: {action, body, cta?, wait_seconds?, rationale}
    """
    # Auto-reply detection
    auto_reply_phrases = [
        "thank you for contacting",
        "i am not available",
        "i am away",
        "automated",
        "automated response",
        "aapki jaankari ke liye",
        "shukriya",
        "our team will get back",
        "i will get back",
        "not available right now",
        "bahut-bahut shukriya",
        "main ek automated",
    ]
    msg_lower = merchant_message.lower()
    is_auto = any(phrase in msg_lower for phrase in auto_reply_phrases)
    
    # Count prior auto-replies in conversation
    prior_auto_count = state.get("auto_reply_count", 0)
    if is_auto:
        if prior_auto_count >= 1:
            return {
                "action": "end",
                "body": "",
                "rationale": "Second auto-reply detected. Gracefully exiting to avoid burning turns on a bot.",
            }
        state["auto_reply_count"] = prior_auto_count + 1

    # Turn count guard
    turn_number = state.get("turn_number", 1)
    if turn_number >= 5:
        return {
            "action": "end",
            "body": "",
            "rationale": "Reached 5-turn limit without commitment. Gracefully exiting.",
        }

    # Build history string
    history = state.get("conversation_history", [])
    history_str = "\n".join(
        f"[{m['from'].upper()}] {m['body']}" for m in history[-6:]
    )

    # Minimal context for the reply
    merchant = state.get("merchant", {})
    category = state.get("category", {})
    
    context_summary = {
        "merchant_name": merchant.get("identity", {}).get("name", ""),
        "owner_first_name": merchant.get("identity", {}).get("owner_first_name", ""),
        "category": category.get("slug", ""),
        "language_pref": merchant.get("identity", {}).get("languages", ["en"]),
        "active_offers": [o["title"] for o in merchant.get("offers", []) if o.get("status") == "active"],
        "performance": merchant.get("performance", {}),
        "signals": merchant.get("signals", []),
        "is_auto_reply_detected": is_auto,
        "prior_auto_replies": prior_auto_count,
        "turn_number": turn_number,
    }

    prompt = f"""=== CONVERSATION HISTORY ===
{history_str}

[MERCHANT] {merchant_message}

=== MERCHANT CONTEXT ===
{json.dumps(context_summary, ensure_ascii=False)}

=== TASK ===
Detect intent. Choose the right action. Compose the reply (if action=send).
Remember: if merchant accepted → execute immediately, no more qualifying.
If this is an auto-reply (is_auto_reply_detected=true) and prior_auto_replies=0 → try once to pierce.
Return ONLY valid JSON. Always include "body" field in response."""

    response = _client.messages.create(
        model=MODEL,
        max_tokens=600,
        temperature=0,
        system=MULTI_TURN_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("` \n")
    
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        result = json.loads(match.group()) if match else {"action": "send", "body": "Main samajh gayi. Koi help chahiye toh batayein! 🙂", "cta": "none", "rationale": "parse fallback"}
    
    # Ensure body is always present
    if "body" not in result:
        result["body"] = ""

    return result


# ─────────────────────────────────────────────────────────────────────────────
# FLASK HTTP SERVER — implements all 5 judge-facing endpoints
# ─────────────────────────────────────────────────────────────────────────────

try:
    from flask import Flask, request, jsonify
    
    app = Flask(__name__)
    
    # ── In-memory state stores ──
    _contexts: dict = {}          # {scope: {context_id: {version, payload}}}
    _conversations: dict = {}     # {conversation_id: {state}}
    _start_time = time.time()
    _suppression_set: set = set() # for dedup
    
    for scope in ("category", "merchant", "customer", "trigger"):
        _contexts[scope] = {}
    
    # ── / ──
    @app.route("/", methods=["GET"])
    def index():
        return jsonify({
            "service": "Vera-Next API",
            "status": "ok",
            "message": "Use the /v1 endpoints below.",
            "endpoints": {
                "health": "/v1/healthz",
                "metadata": "/v1/metadata",
                "context": "/v1/context",
                "tick": "/v1/tick",
                "reply": "/v1/reply",
            },
        })

    # ── /v1/healthz ──
    @app.route("/v1/healthz", methods=["GET"])
    def healthz():
        return jsonify({
            "status": "ok",
            "uptime_seconds": int(time.time() - _start_time),
            "contexts_loaded": {
                scope: len(_contexts[scope])
                for scope in ("category", "merchant", "customer", "trigger")
            },
        })
    
    # ── /v1/metadata ──
    @app.route("/v1/metadata", methods=["GET"])
    def metadata():
        return jsonify({
            "team_name": "Vera-Next",
            "team_members": ["Candidate"],
            "model": MODEL,
            "approach": "Trigger-dispatched prompt composer with 25-strategy routing, voice-enforced generation, auto-reply state machine, multi-turn conversation handler",
            "contact_email": "candidate@example.com",
            "version": "2.0.0",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        })
    
    # ── /v1/context ──
    @app.route("/v1/context", methods=["POST"])
    def receive_context():
        data = request.get_json(force=True)
        scope = data.get("scope")
        context_id = data.get("context_id")
        version = data.get("version")
        payload = data.get("payload")
        delivered_at = data.get("delivered_at")
    
        if scope not in _contexts:
            return jsonify({"accepted": False, "reason": "invalid_scope", "details": f"Unknown scope: {scope}"}), 400
    
        existing = _contexts[scope].get(context_id)
        if existing:
            if existing["version"] == version:
                # Same version — idempotent no-op → return 409 per spec
                return jsonify({"accepted": False, "reason": "stale_version", "current_version": existing["version"]}), 409
            if existing["version"] > version:
                return jsonify({"accepted": False, "reason": "stale_version", "current_version": existing["version"]}), 409
    
        _contexts[scope][context_id] = {"version": version, "payload": payload, "updated_at": delivered_at}
        ack_id = f"ack_{context_id}_v{version}"
        return jsonify({"accepted": True, "ack_id": ack_id, "stored_at": datetime.now(timezone.utc).isoformat()})
    
    # ── /v1/tick ──
    @app.route("/v1/tick", methods=["POST"])
    def tick():
        data = request.get_json(force=True)
        now_str = data.get("now", datetime.now(timezone.utc).isoformat())
        available_triggers = data.get("available_triggers", [])
    
        actions = []
    
        for trigger_id in available_triggers:
            # Skip if already suppressed
            trigger_ctx = _contexts["trigger"].get(trigger_id, {})
            if not trigger_ctx:
                continue
            trigger = trigger_ctx.get("payload", {})
            if not trigger:
                continue
            
            suppression_key = trigger.get("suppression_key", "")
            if suppression_key in _suppression_set:
                continue
    
            merchant_id = trigger.get("merchant_id")
            if not merchant_id:
                continue
    
            merchant_ctx = _contexts["merchant"].get(merchant_id, {})
            if not merchant_ctx:
                continue
            merchant = merchant_ctx.get("payload", {})
            if not merchant:
                continue
    
            category_slug = merchant.get("category_slug")
            if not category_slug:
                continue
            category_ctx = _contexts["category"].get(category_slug, {})
            if not category_ctx:
                continue
            category = category_ctx.get("payload", {})
            if not category:
                continue
    
            # Customer context (optional)
            customer = None
            customer_id = trigger.get("customer_id")
            if customer_id:
                cust_ctx = _contexts["customer"].get(customer_id, {})
                if cust_ctx:
                    customer = cust_ctx.get("payload", {})
    
            try:
                result = compose(category, merchant, trigger, customer)
                # Result is guaranteed to have body, cta, send_as, suppression_key
                if not result:
                    continue
            except Exception as e:
                # Log error for debugging but continue to next trigger
                continue
    
            conv_id = f"conv_{uuid.uuid4().hex[:8]}"
            _suppression_set.add(suppression_key)
    
            # Store conversation state for multi-turn
            _conversations[conv_id] = {
                "merchant_id": merchant_id,
                "customer_id": customer_id,
                "merchant": merchant,
                "category": category,
                "trigger": trigger,
                "conversation_history": [{"from": "vera", "body": result["body"]}],
                "turn_number": 1,
                "auto_reply_count": 0,
            }
    
            actions.append({
                "conversation_id": conv_id,
                "merchant_id": merchant_id,
                "customer_id": customer_id,
                "send_as": result.get("send_as", "vera"),
                "trigger_id": trigger_id,
                "template_name": f"vera_{trigger.get('kind', 'general')}_v1",
                "template_params": [
                    merchant.get("identity", {}).get("owner_first_name", ""),
                    trigger.get("kind", ""),
                    result.get("body", "")[:50],
                ],
                "body": result.get("body", ""),
                "cta": result.get("cta", "open_ended"),
                "suppression_key": suppression_key,
                "rationale": result.get("rationale", ""),
            })
    
        return jsonify({"actions": actions})
    
    # ── /v1/reply ──
    @app.route("/v1/reply", methods=["POST"])
    def reply():
        data = request.get_json(force=True)
        conv_id = data.get("conversation_id")
        merchant_message = data.get("message", "")
        received_at = data.get("received_at")
    
        if conv_id not in _conversations:
            return jsonify({"action": "end", "body": "", "rationale": "Unknown conversation_id"}), 404
    
        state = _conversations[conv_id]
        state["turn_number"] = data.get("turn_number", state.get("turn_number", 1) + 1)
    
        # Add merchant message to history
        state["conversation_history"].append({"from": "merchant", "body": merchant_message})
    
        result = respond(state, merchant_message)
    
        # If sending, add to history and ensure body is present
        if result.get("action") == "send":
            state["conversation_history"].append({"from": "vera", "body": result.get("body", "")})
        
        # Ensure body field is always in response, even for end action
        if "body" not in result and result.get("action") == "end":
            result["body"] = ""
    
        return jsonify(result)
    
    
    if __name__ == "__main__":
        port = int(os.environ.get("PORT", 8080))
        app.run(host="0.0.0.0", port=port, debug=False)

except ImportError:
    # Flask not installed — bot.py still works as a module for compose()
    pass
