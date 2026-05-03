# Vera-Next — magicpin AI Challenge Submission

**Team**: Vera-Next | **Model**: claude-sonnet-4-20250514 | **Version**: 2.0.0

---

## What we built

A production-grade Vera replacement that addresses every pain point listed in the brief — plus the three open challenge bonuses.

### Architecture

```
Judge HTTP call
     ↓
Trigger-Kind Dispatcher (25 strategies)
     ↓
Context Builder (category + merchant + trigger + customer → structured JSON)
     ↓
Claude Sonnet (temp=0, voice-enforced system prompt)
     ↓
Post-LLM Validator (CTA shape, suppression key, language check)
     ↓
Response
```

**Five HTTP endpoints** per the testing brief: `/v1/healthz`, `/v1/metadata`, `/v1/context`, `/v1/tick`, `/v1/reply`.

---

## What makes this submission different

### 1. Trigger-kind dispatching (25 strategies)

Rather than one generic prompt, every trigger kind gets its own strategy string that tells the LLM exactly which compulsion lever to lead with, what CTA shape to use, and how to frame the message. `research_digest` → cite trial_n and source. `perf_dip` → exact numbers + loss aversion. `recall_due` → customer name + two slot options. No generic output possible.

### 2. Voice enforcement baked into system prompt

The system prompt embeds all five category voices, the full taboo word list, and explicit anti-patterns from §11 of the brief. The LLM cannot produce "Flat 30% off" or "AMAZING DEAL!" because it's told the judge will penalise exactly that.

### 3. Auto-reply state machine (extra credit #1)

`conversation_handlers.py` detects auto-replies with a phrase list and a counter. Rule: attempt one pierce on the first auto-reply, then `action: end` immediately on the second. No 3-turn waste.

### 4. Intent transition routing (extra credit #2)

When a merchant says "mujhe join karna hai" or "haan chal" → local regex triggers `Intent.INTENT_TRANSITION` → bot skips qualification entirely and goes straight to onboarding action. No re-qualifying after accept.

### 5. Turn limit + unanswered nudge guard (extra credit #5)

Hard limit: 5 turns max. Also tracks 3 consecutive unanswered nudges → graceful exit. Category-aware exit messages (dental vs salon vs restaurant tone).

### 6. Context versioning (idempotency)

`/v1/context` correctly implements `(context_id, version)` idempotency with 409 on same-version re-post, atomic replacement on version bump.

---

## 5-dimension scoring strategy

| Dimension | Our approach |
|---|---|
| **Specificity** | Every compose call is anchored to at least one verifiable number from the context: trial_n, CTR, views, days_remaining, lapsed_count, offer price. |
| **Category fit** | System prompt embeds category-specific voice rules + vocab taboo. Dentist messages cite JIDA; pharmacy messages cite CDSCO; restaurant messages tie to local events. |
| **Merchant fit** | Prompt builder extracts owner_first_name, city, locality, active_offers, signals, customer_aggregate and injects them as named variables. |
| **Trigger relevance** | Trigger strategy tells the LLM "this is WHY you are messaging right now" — not generic guidance. |
| **Engagement compulsion** | System prompt lists all 8 compulsion levers and requires ≥1 per message. Social proof (#3) and asking the merchant (#7) — the two levers production Vera misses most — are explicitly called out. |

---

## Tradeoffs

- **Single prompt per trigger** vs retrieval: We chose a single well-structured prompt with full context injection over RAG/retrieval. With 5 categories × ~20 digest items each, full injection fits within context limits and is simpler to reproduce deterministically.
- **Temperature=0**: Required by the brief for determinism. We compensate with a rich strategy string per trigger kind to reduce variance at T=0.
- **Flask vs async**: Flask for simplicity and reliability. The 30s per-call judge limit is easily met; Flask's synchronous model makes state management straightforward.

## What additional context would have helped

1. **Merchant's last 7 days of conversation history** (not just last 2 turns) — better anti-repetition.
2. **Which day of the week** the message is being sent — timing affects framing (don't send a Diwali campaign on Diwali itself).
3. **Merchant's WhatsApp session status** — within 24h window (free-form) vs cold outbound (template required). Bot currently assumes template for first message.
4. **Click/read receipts from prior messages** — knowing a merchant read but didn't reply changes the tone of the follow-up.

---

## File manifest

```
bot.py                   — compose() + Flask HTTP server (5 endpoints)
conversation_handlers.py — multi-turn state machine (bonus)
submission.jsonl          — 30 test pair outputs
README.md                 — this file
dataset/                  — provided dataset (unmodified)
```
