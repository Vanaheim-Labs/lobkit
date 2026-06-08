# Foundry

> Check in a conversation. Foundry remembers what matters and tracks what needs doing.

Foundry is an execution engine that builds institutional knowledge as a side effect of getting work done.

**Status:** RFC (Rev 7.1 — Event Delivery added)
**Date:** 2026-06-08
**Authors:** Andrew, Mimir

---

## Doctrine

Foundry has four durable concepts:

1. **Workspace** — the boundary.
2. **Source** — what happened.
3. **Page** — what we know and how we work.
4. **Card** — what needs doing.

Foundry has three verbs:

1. **Check in** — capture a Source and distil it into Pages and Cards.
2. **Ask** — answer from Pages and Sources with provenance.
3. **Work** — execute Cards and write back useful knowledge.

Everything else is:
- a link between these things;
- an event on these things;
- a view over these things; or
- an implementation detail.

If a proposed feature introduces a new core noun or verb, it is probably wrong.

---

## Non-goals

Foundry is not:
- a general project management system;
- a replacement for Slack, email, or documents;
- a freeform agent memory store;
- a database UI;
- a workflow engine;
- a place for every thought — only checked-in knowledge and executable work.

Foundry does not try to capture everything. It captures what people choose to check in.

---

| Concept | Meaning |
|---|---|
| **Source** | What happened |
| **Page** | What we know / how we do things |
| **Card** | What needs doing |

Sources are stored as append-only Markdown files in `/sources`. They are not Pages in the product model. Sources are raw material; Pages are interpreted knowledge. The boundary is clean: Sources are preserved, Pages are evolved.

---

## Golden Path

This is the canonical happy-path example — the whole system in seven steps:

1. A human says: `@Mimir check this in.`
2. Foundry captures the Slack thread as a Source.
3. Foundry updates two Pages:
   - `pages/foundry-architecture.md`
   - `pages/openclaw-workboard.md`
4. Foundry creates one Card:
   - "Draft the Rev 7 implementation checklist"
5. A human later says: `@Mimir work on the next Heimdall card.`
6. The agent loads the Card, linked Pages, and original Source.
7. The agent completes the work, attaches proof, and writes back a finding.

If a proposed feature cannot be explained in terms of this loop, it is probably wrong.

---

## The Full Cycle

This is the end-to-end flow that Foundry enables:

```
Conversation
    │
    ▼
 Check In
    │
    ├──→ Source  (what happened — preserved)
    ├──→ Pages   (what we know — updated)
    └──→ Cards   (what to do — created)
           │
           ▼
      Agent Executes
           │
     ┌─────┴─────┐
     ▼           ▼
   Done       Blocked
  (proof)    (question)
                 │
                 ▼
           Human Replies
                 │
                 ▼
           Agent Resumes
                 │
                 ▼
               Done
```

Check-ins produce knowledge and work. Work gets executed. Execution produces more knowledge (proof, output, findings). That knowledge feeds future check-ins and future work.

The system compounds: the more you check in, the richer the wiki. The richer the wiki, the more context agents have. The more context agents have, the better the work.

---

## 1. Workspace

A Workspace is the boundary. It answers: *which organisation, project, or knowledge base does this belong to?*

```
Heimdall        — Vanaheim Labs internal knowledge base
Slate           — Inkl business knowledge base
Laurion         — Project Laurion (financial advice platform)
```

A Workspace contains:

```
Sources     — what happened
Pages       — what we know
Cards       — what needs doing
Settings    — routing, permissions, defaults
```

Internally, a Workspace maps to:
- A *Memory Wiki vault* (physically isolated directory, Git-backed)
- A *Workboard board* (logically isolated within Workboard's SQLite)
- A section of the *Foundry Manifest* (config)

### Workspace Manifest

```json5
{
  "foundry": {
    "workspaces": {
      "heimdall": {
        "name": "Heimdall",
        "owner": "andrew",
        "vault": "~/.openclaw/wiki/heimdall",
        "board": "heimdall",
        "agents": ["main", "heimdall"],
        "channels": [
          {
            "provider": "slack",
            "account": "default",
            "ids": ["C0AGSRGQU6Q", "C0AJMGXC14M"],
            "default": true
          }
        ],
        "autoCheckin": true,
        "autoDispatch": false,
        "approvalRequired": [
          "more_than_5_cards",
          "updates_existing_decisions",
          "low_confidence_decision",
          "cross_workspace_reference",
          "sensitive_content"
        ]
      }
    }
  }
}
```

`autoDispatch` defaults to `false`. Early Workspaces require human-triggered or agent-claimed execution until the check-in quality is proven. Turn it on per Workspace as a maturity upgrade.

### Channel Routing

A channel has *exactly one* default Workspace and *zero or more* permitted Workspaces.

- `@Mimir check this in` → routes to the channel's default Workspace.
- `@Mimir check this into Heimdall` → routes to Heimdall, if permitted for this channel.
- If no default and no explicit target → ask the user.

A channel cannot accidentally write to a Workspace it isn't permitted for.

---

## 2. Source

A Source is anything Foundry has captured. A committed Slack thread is a Source. A meeting transcript is a Source. An uploaded document is a Source. A manual note is a Source.

```yaml
id: src_slack_C0AGSRGQU6Q_1780844291
workspace: heimdall
type: slack_thread
title: "Foundry v2 architecture discussion"
uri: "slack://C0AGSRGQU6Q/1780844291"
content_hash: sha256(...)
status: committed
captured_at: "2026-06-08T00:58:11Z"
```

Source files live at `sources/{id}.md` in the Workspace's wiki vault. They are *append-only* — the original capture is never rewritten. If new replies arrive in the thread, they are appended as events on the Source.

A Source is the raw material. It is not interpreted or opinionated. The interpretation happens when Sources become Pages and Cards through the check-in process.

---

## 3. Page

A Page is durable knowledge. Pages are the wiki.

There are two kinds:

| Kind | Purpose | Examples |
|---|---|---|
| **Knowledge Page** | What we know | "Future Publishing", "HubSpot Integration", "Role Division" |
| **Playbook Page** | How we do something | "Publisher Onboarding", "Foundry Deployment" |

That's enough. Everything else is metadata on a Page, not a new kind.

A "decision" is a block on a Page:

```markdown
## Decisions

- **Decision:** Use Workboard for all task management in Foundry v2.
  **Why:** Native OpenClaw primitive — eliminates custom infrastructure.
  **Source:** src_slack_C0AGSRGQU6Q_1780844291
  **Status:** current
  **Date:** 2026-06-08
```

A "finding" is also just a block on a Page.
An "entity" is just a Knowledge Page.
A "domain" is just a tag or folder.

Pages live in the Workspace's wiki vault. They use Memory Wiki's structured claims system for decisions that need provenance, confidence, and lifecycle tracking. But the product-level concept is just "Page."

### The Mutability Rule

| What | How it changes |
|---|---|
| Sources | Append-only (new events added, original never rewritten) |
| Knowledge Pages | Updated (new information added, stale information marked) |
| Playbook Pages | Updated (procedures refined over time) |
| Decision blocks / claims | Versioned — new decisions *supersede* old ones, never silently replace |

Foundry does not rewrite history. When a decision changes, the new one supersedes the old one and both remain in the record.

---

## 4. Card

A Card is work. Something that needs doing — and something that will actually get *done*.

Cards are not a task list. They are executable units of work. An agent will claim a Card, load context from the wiki, do the work, and deliver proof of completion or ask for help.

### What a Card contains

```yaml
id: card_heimdall_abc123
workspace: heimdall
title: "Migrate authentication to OAuth2"
objective: "Replace token-based auth with OAuth2 flow using Auth0"
definition_of_done: "OAuth2 endpoints live, old tokens deprecated, integration tests green"
status: ready
priority: high
assignee: null                          # null = any permitted agent can claim it
source_id: src_slack_C0AGSRGQU6Q_1780844291
labels: ["auth", "api"]
parent_card: null                       # null = top-level; set for sub-cards
proof: null                             # filled on completion
output: null                            # filled on completion
created_at: "2026-06-08T01:00:00Z"
```

Every Card has an *objective* (what to do) and a *definition of done* (how to know it's finished). Cards without these are not valid — they stay in Inbox until clarified.

### What is a Card (and what is not)

A Card is created only when there is:

1. A concrete owner or eligible agent class
2. A clear objective
3. A definition of done
4. Enough context to start
5. A genuine expectation that the work should be executed

Everything else becomes a finding on a Page.

```
"We should look into OAuth"
    → finding on a Knowledge Page

"Prepare a short recommendation comparing Auth0 and Cognito by Friday"
    → Card
```

The distillation skill enforces this boundary. Vague intentions, musings, and "we should eventually" statements are captured as findings, not Cards. A Card that can't be executed is noise.

### Card lifecycle

```
Inbox → Ready → Doing → Done
                  │
                  ▼
               Blocked ── human replies ──→ Ready

Any non-terminal Card may be Cancelled.
```

| State | Meaning | What happens next |
|---|---|---|
| **Inbox** | Captured but not yet accepted | Human or agent reviews; moves to Ready or Cancelled |
| **Ready** | Has a clear objective and can be worked | Dispatch assigns it, or a human triggers it |
| **Doing** | An agent has claimed it and is actively working | Agent completes, blocks, or fails |
| **Done** | Completed successfully — proof/output attached | Terminal. Knowledge may be written back to Pages. |
| **Blocked** | Cannot proceed — needs input, a decision, or a dependency | Question posted; human reply unblocks → Ready |
| **Cancelled** | No longer required or terminal-failed | Terminal. |

Done means *done*. A successfully completed Card moves to Done with proof. Failure is handled differently:

| Situation | State |
|---|---|
| Agent hits missing information | Blocked |
| Agent fails but work should retry | Blocked (with failure reason, re-queued on unblock) |
| Work is no longer worth doing | Cancelled |
| Work was completed successfully | Done |

A failed execution records a `card.failed` event. The Card then moves to Blocked if retryable, or Cancelled if no longer worth pursuing. Done is reserved for success.

### How Cards get executed

Cards can be worked manually, human-triggered, or auto-dispatched. Auto-dispatch is a Workspace setting, not a Foundry assumption.

**1. Human-triggered (default)**

A human directs an agent to work on a specific Card or the next available one:

```
@Mimir work on the next Heimdall card
@Mimir pick up "Migrate to OAuth2"
```

The agent claims the Card and follows the execution flow: load context, do the work, deliver proof.

This is the starting point for new Workspaces — humans control when work begins.

**2. Auto-dispatch (opt-in for mature Workspaces)**

When `autoDispatch: true` is set on a Workspace, Foundry continuously looks for Ready Cards and assigns them automatically:

1. It spawns a worker agent (a background sub-agent session)
2. The worker receives:
   - The Card's objective and definition of done
   - Relevant wiki Pages loaded via the Card's links (context)
   - The original Source that created the Card (provenance)
   - The Workspace's Playbook Pages if the work matches a known procedure
3. The worker executes the objective — writes code, drafts documents, runs analysis, makes API calls, whatever the Card requires
4. On completion, the worker:
   - Attaches proof (PR link, test output, generated document, etc.)
   - Attaches output (the deliverable itself, if applicable)
   - Moves the Card to Done
   - Optionally writes findings back to wiki Pages (knowledge write-back)

Under the hood, auto-dispatch is Workboard's native dispatch system: it selects Ready Cards by priority, avoids duplicate claims, and starts worker sessions through the gateway's sub-agent runtime. Foundry doesn't build its own executor — it configures the native one.

**3. Human execution**

Not all Cards are for agents. A Card like "Schedule a meeting with the Auth0 team" is human work. Humans move these Cards through the board manually (via dashboard or Slack commands) and mark them Done when finished.

### The blocked-unblocked loop

When an agent hits something it can't resolve alone, the Card goes to Blocked:

```yaml
status: blocked
blocked_reason: "Which OAuth provider should we use — Auth0 or Cognito?"
blocked_channel: "slack://C0AGSRGQU6Q/1780844291"
blocked_at: "2026-06-08T02:30:00Z"
```

The question is posted to the Card's originating Slack thread (or the Workspace's default channel). When a human replies:

1. The *reverse-path hook* captures the reply
2. The reply is recorded as an event on the Card (and appended to the Source)
3. The Card moves from Blocked → Ready
4. If auto-dispatch is enabled, a worker picks it up again — now with the human's answer as additional context
5. The worker resumes from where it left off (or re-evaluates if the answer changes the approach)

This is the conversational work loop: agents work, hit walls, ask questions, get answers, and resume. Humans don't project-manage — they answer questions and review output.

### Sub-Cards

When a Card's objective is too large for a single execution, it gets decomposed into child Cards:

```
Parent Card: "Migrate authentication to OAuth2"
├── Child Card 1: "Set up Auth0 tenant and configure redirect URIs"
├── Child Card 2: "Replace token middleware with OAuth2 flow"
├── Child Card 3: "Write integration tests for new auth flow"
└── Child Card 4: "Deprecate old token endpoints"
```

Child Cards execute independently (potentially in parallel) and link back to their parent. The parent Card moves to Done when all children are Done.

Decomposition can happen:
- At check-in time (the distillation skill recognises the work is multi-step)
- During execution (a worker realises the Card is too large and decomposes it)
- By human request ("break this down into steps")

Under the hood, this is Workboard's native `workboard_decompose` — parent/child links with dependency-aware dispatch.

### Knowledge write-back

When a Card completes, the output often contains new knowledge. Write-back follows controlled rules:

| Write-back type | Approval required |
|---|---|
| Proof link (PR, test output, doc link) | No |
| Output summary (what was delivered) | No |
| New finding (discovery during execution) | No |
| Playbook improvement (procedure refined) | Maybe — depends on scope |
| Decision (new decision made during work) | Yes — requires check-in or human approval |
| Superseding existing decision | Yes — requires check-in or human approval |
| Cross-workspace write | Yes — always |

Worker write-back is *append-first*. Workers may freely add proof links, output summaries, and factual findings. Direct mutation of existing decisions or cross-workspace knowledge requires either a check-in transaction or explicit approval. Agents should not be able to quietly rewrite institutional memory.

---

## 5. Links and Events

These are not product concepts. They are the connective tissue.

### Links

Links connect the four core concepts:

```
Source  → Page        extracted_into
Source  → Card        created_card
Page    → Page        related_to
Card    → Page        uses_context
Card    → Source      based_on
Page    → Source      evidenced_by
Card    → Card        child_of
```

Links are what make the system powerful without adding nouns. When an agent claims a Card, the links tell it which Pages and Sources to load as context. When a Page is displayed, the links show which Sources support it and which Cards reference it.

Minimum link model:

```yaml
from: card_abc123
to: src_slack_C0AGSRGQU6Q_1780844291
type: based_on
```

### Events

Events are what happened to a Source, Page, or Card:

```
source.committed          source.appended
page.created              page.updated
card.created              card.claimed
card.executing            card.blocked
card.unblocked            card.completed
card.failed               card.decomposed
comment.added             decision.recorded
decision.superseded       writeback.applied
```

Events replace: conversations table, runs table, task_events table, audit log. One event stream per Workspace, not separate tables for each concern.

Minimum event model:

```yaml
id: evt_123
workspace: heimdall
subject_type: card
subject_id: card_abc123
type: card.blocked
actor: mimir
created_at: "2026-06-08T02:30:00Z"
payload:
  reason: "Which OAuth provider should we use?"
```

Execution events on a Card (`card.claimed`, `card.executing`, `card.blocked`, `card.completed`, `card.failed`) are the equivalent of v1's "runs" — but they're just events, not a separate concept.

### Event Delivery

Events are internal by default. Event delivery makes them visible — publishing updates to Slack (or any channel) when things happen in a Workspace.

Delivery is not a new noun or verb. It is a configurable behaviour on events: when an event fires, optionally format and send a message to a channel.

#### Workspace notification config

Notification preferences live in the Workspace manifest alongside channel routing:

```json5
{
  "notifications": {
    "channel": "C0AQFJDT2HE",      // default delivery channel
    "thread": false,                 // true = thread per card/source
    "on": {
      "checkin.complete": true,       // 📥 Checked in: {title} — N pages, M cards
      "card.created": false,         // usually noisy; off by default
      "card.claimed": true,          // 🔨 {agent} picked up: {title}
      "card.completed": true,        // ✅ Done: {title} — {proof summary}
      "card.blocked": true,          // 🚫 Blocked: {title} — {question}
      "card.failed": true,           // ❌ Failed: {title} — {reason}
      "card.unblocked": false,       // usually implied by next claim
      "page.decision_recorded": true, // 📋 Decision: {text} on {page}
      "page.updated": false,         // too frequent; off by default
      "source.committed": false      // covered by checkin.complete
    },
    "digest": {
      "enabled": false,
      "schedule": "daily",           // daily | weekly
      "channel": null                // defaults to notifications.channel
    }
  }
}
```

Delivery follows the same principle as everything else in Foundry: start quiet, turn up the volume per Workspace as trust grows. All event types default to `false` except the high-signal ones shown above.

#### What gets published

| Event | Default | Message format |
|---|---|---|
| `checkin.complete` | ✅ on | 📥 *Checked in:* {title} — {N} pages updated, {M} cards created |
| `card.created` | off | 📌 *New card:* {title} ({priority}) |
| `card.claimed` | ✅ on | 🔨 *{agent}* picked up: {title} |
| `card.completed` | ✅ on | ✅ *Done:* {title} — {proof summary} |
| `card.blocked` | ✅ on | 🚫 *Blocked:* {title} — {question} |
| `card.failed` | ✅ on | ❌ *Failed:* {title} — {reason} |
| `card.unblocked` | off | 🔓 *Unblocked:* {title} — re-queued |
| `page.decision_recorded` | ✅ on | 📋 *Decision:* {text} — on {page} |
| `page.updated` | off | 📝 *Page updated:* {page} — {change summary} |
| `source.committed` | off | 📄 *Source captured:* {title} |
| `digest` | off | 📊 *{Workspace} today:* {N} check-ins, {M} cards worked, {B} blocked |

#### Delivery mechanics

Event delivery uses the same channel infrastructure as the rest of Foundry:
- The agent posts to the Workspace's notification channel via normal messaging
- Blocked card questions are posted to the *originating thread* (reverse-path), not the notification channel
- Digest summaries can go to a different channel if configured
- Delivery is best-effort and non-blocking — a failed notification does not block the event

The reverse-path hook (Phase 3) is a specific case of event delivery: `card.blocked` → post question to originating thread. General event delivery extends this pattern to all event types.

#### What event delivery is NOT

- Not a new noun (no "Notification" entity)
- Not a new verb (no "Notify" action)
- Not a webhook system — it uses Foundry's existing channel routing
- Not a replacement for the dashboard — it supplements passive browsing with active push

Event delivery is: events + channel routing + message formatting. Three things that already exist, composed.

---

## 6. The Three Verbs

### 6.1 Check In

The canonical verb is **check in**. Not "commit", not "record", not "write to", not "capture". The agent understands natural variants, but the product concept is always *check in*.

```
@Mimir check this in
@Mimir check this into Heimdall
@Mimir check this into Slate
```

What happens:

1. Agent acknowledges in the thread
2. Resolves the target Workspace (explicit name, or channel default)
3. Checks idempotency — has this thread been checked in before?
4. Fetches the full thread
5. Distils: title, summary, findings, decisions, action items, mentioned entities
6. If approval triggers fire → shows a preview and waits for confirmation
7. Creates a Source (append-only)
8. Updates Knowledge/Playbook Pages for mentioned entities and concepts
9. Records decisions as blocks (with structured claims for provenance tracking)
10. Creates Cards for action items — only when they meet the Card criteria (objective, definition of done, concrete owner, enough context, genuine expectation of execution)
11. Wires links between everything
12. Reports back in the thread with a summary of what was captured
13. If `autoDispatch` is enabled, Ready Cards begin executing

A successful check-in may create no Cards. That is not a failure. Some conversations produce only knowledge.

*Idempotency:* If the same thread is checked in twice, Foundry says "This was already checked in. Want me to update it with new replies?" — not create a duplicate.

*Preview:* Required when: >5 cards, low-confidence decisions, cross-workspace references, updates to existing decisions, sensitive content. Configurable per Workspace.

### Check-in record

Each check-in produces an operational receipt. This is not a fifth core noun — it is just the transaction record for idempotency and auditability.

```yaml
id: checkin_slack_C0AGSRGQU6Q_1780844291
workspace: heimdall
source_id: src_slack_C0AGSRGQU6Q_1780844291
origin_uri: slack://C0AGSRGQU6Q/1780844291
content_hash: sha256(...)
status: complete
artifacts:
  pages:
    - page_foundry_architecture
  cards:
    - card_heimdall_abc123
events:
  - evt_123
checked_in_at: "2026-06-08T00:58:11Z"
```

*Check-in modes* (determined by context, not a separate command):

| Situation | Behaviour |
|---|---|
| New discussion | Full check-in → Source + Pages + Cards |
| New initiative with many tasks | Source + domain Page + parent Card + child Cards |
| Plan revised in a thread | Append to Source, update existing Cards |
| General discussion about existing work | Append to Source, add synthesis to related Pages |

### 6.2 Ask

```
@Mimir what does Heimdall know about our API architecture?
@Mimir search Slate for Future Publishing onboarding
```

What happens:

1. Agent resolves the target Workspace
2. Searches Pages and Sources using `wiki_search` / `memory_search`
3. Retrieves relevant Pages with `wiki_get`
4. Synthesises an answer with provenance (links back to Sources and Pages)

The agent answers *from the Workspace's knowledge*, not from general training. Provenance is visible.

Foundry answers should show where the answer came from. If the relevant knowledge has no Source, the agent should say so. The system's credibility depends on distinguishing grounded institutional knowledge from inferred agent synthesis.

### 6.3 Work

```
@Mimir work on the next Heimdall card
@Mimir pick up "Migrate to OAuth2"
```

What happens:

1. Agent claims a Ready Card from the Workspace's board (or auto-dispatch claims it)
2. Card moves to Doing; a `card.claimed` event is recorded
3. Agent loads context:
   - The Card's objective and definition of done
   - Linked Pages (via `uses_context` links)
   - The originating Source (via `based_on` link)
   - Relevant Playbook Pages (if the objective matches a known procedure)
4. Agent executes the work
5. During execution, the agent can:
   - Post progress events (`card.executing` with status notes)
   - Block the Card with a question (`card.blocked`)
   - Decompose into sub-Cards (`card.decomposed`)
   - Write findings back to Pages (within write-back rules)
6. On completion:
   - Agent attaches proof and output to the Card
   - Card moves to Done; a `card.completed` event is recorded
   - If the work produced new knowledge, it's written back to Pages (per write-back rules)
7. If blocked:
   - Question posted to the originating thread
   - Human reply triggers `card.unblocked` → Card returns to Ready
   - Next dispatch cycle picks it up with the new context

The work verb is the same whether triggered by a human ("pick up X") or by auto-dispatch. The only difference is who initiates the claim.

---

## 7. Tool Surface

Five tools. That's enough.

| Tool | Purpose |
|---|---|
| `foundry_checkin` | Capture a Source, update Pages, create Cards |
| `foundry_search` | Search across Sources, Pages, and Cards in a Workspace |
| `foundry_get` | Retrieve a Source, Page, or Card by ID or slug |
| `foundry_card_create` | Create a Card (for agent-initiated work, or manual card creation) |
| `foundry_card_update` | Move Card state, add comment, attach proof/output, block/unblock, decompose |

No separate decision tool — decisions are part of check-in.
No separate wiki write tool — normal agents don't freely write wiki pages; they check in Sources and Foundry controls the distillation. Workers can write back to Pages on Card completion (controlled, not freeform).
No separate task-ask tool — `foundry_card_update(status="blocked", question="...")`.
No separate search for each type — one search across everything.

Under the hood, these tools compose native OpenClaw primitives:
- `foundry_checkin` → `wiki_apply` + `workboard_create`
- `foundry_search` → `wiki_search` / `memory_search`
- `foundry_get` → `wiki_get` / `workboard_read`
- `foundry_card_create` → `workboard_create`
- `foundry_card_update` → `workboard_claim` / `workboard_complete` / `workboard_block` / `workboard_comment` / `workboard_decompose` / `workboard_proof`

---

## 8. Implementation Mapping

Foundry's four concepts map directly to native OpenClaw primitives:

| Foundry Concept | OpenClaw Primitive | How |
|---|---|---|
| **Workspace** | Wiki vault + Workboard board + Manifest config | Physically isolated vault, logically isolated board |
| **Source** | Wiki source file (`sources/`) | Append-only Markdown with YAML frontmatter |
| **Page** | Wiki page (`entities/`, `concepts/`, `syntheses/`) | Memory Wiki with structured claims |
| **Card** | Workboard card | Native lifecycle, dispatch, agent tools |
| **Link** | Wiki backlinks + Workboard card links | Native Memory Wiki + Workboard parent/child |
| **Event** | Wiki provenance + Workboard card events + audit | Native event systems |
| **Auto-dispatch** | Workboard dispatch | Native worker spawning via gateway sub-agent runtime |
| **Blocked loop** | Reverse-path hook + Workboard unblock | Hook captures reply → card update → re-dispatch |
| **Sub-Cards** | Workboard decompose + parent/child links | Native dependency-aware dispatch |
| **Knowledge write-back** | `wiki_apply` from worker context | Worker writes findings to Pages on completion (controlled) |

Foundry does not duplicate these primitives. It composes them.

### What Foundry adds on top of native OpenClaw

The thin layer:

1. **Workspace manifest** — config schema defining workspaces, channel routing, agent permissions, approval policies, dispatch settings
2. **Channel-to-Workspace resolver** — routes "check this in" to the right Workspace
3. **Check-in transaction** — idempotent check-in lifecycle with artifact tracking
4. **Distillation skill** — the LLM-driven process that turns raw Sources into structured Pages and Cards with objectives and definitions of done
5. **Reverse-path hook** — captures thread replies and routes them to Sources and Cards (including unblocking)
6. **Worker context injection** — when dispatch spawns a worker for a Card, Foundry loads the linked Pages and Sources into the worker's prompt context
7. **Write-back rules** — controlled append-first write-back with approval gates for decisions and cross-workspace writes
8. **Event delivery** — configurable per-Workspace notification publishing to channels when events fire (check-ins, card lifecycle, decisions)

Everything else is native:
- Knowledge = Memory Wiki
- Work = Workboard
- Execution = Workboard dispatch (sub-agent runtime)
- Orchestration = TaskFlow / Lobster (for complex multi-Card flows)
- Automation = Hooks / Standing Orders / Cron
- Interface = Slack / any channel

### What's eliminated from v1

| Old Component | New Status |
|---|---|
| Cloudflare Worker | *Eliminated* |
| D1 Database | *Eliminated* |
| Custom dashboard (React/Vite) | *Eliminated* — use OpenClaw Control UI |
| `foundry.sh` CLI | *Eliminated* — use native tools |
| `foundry-commit.py` | *Replaced* by distillation skill |
| `foundry-thread-fetch.py` | *Eliminated* — native Slack history |
| Deploy script | *Eliminated* — nothing to deploy |
| Cron claim loop | *Eliminated* — Workboard dispatch |
| foundry-relay plugin | *Replaced* by reverse-path hook |

---

## 9. Dashboard

Three tabs. That's enough.

| Tab | Shows | Is really |
|---|---|---|
| **Knowledge** | Pages (wiki browser + search) | Memory Wiki vault |
| **Work** | Cards (kanban / list) | Workboard board |
| **Sources** | Committed threads, documents, notes | Wiki source files |

Everything else is a filter, not a tab:

| Old concept | New home |
|---|---|
| Decision log | Knowledge, filtered: `has:decision` |
| Card conversation / comments | Card detail drawer (events) |
| Source timeline | Source detail (events) |
| Execution history | Card detail drawer (events: claimed, executing, completed, failed) |
| Blocked Cards needing input | Work, filtered: `status:blocked` |
| Case management | Work (parent Card with child Cards) |
| Audit log | Source/Card/Page activity drawer (events) |
| Recurring tasks | Work, filtered: `recurring:true` |
| Workspace switcher | Top-level nav — like switching repos in GitHub |

---

## 10. Observability

Health is a view over the core concepts, not a separate system.

**Source health:**
- Check-ins per week
- Duplicate check-ins prevented
- Threads with unprocessed replies
- Sources with no Pages extracted (orphan captures)

**Knowledge health:**
- Stale Pages (no updates in N days)
- Decisions marked contested or low confidence
- Pages with no linked Sources (ungrounded knowledge)
- Playbooks with no linked Cards (unused procedures)

**Work health:**
- Blocked Cards and duration blocked
- Cards in Inbox for >N days (unclaimed/unreviewed)
- Cards that failed repeatedly (execution events show pattern)
- Cards with no proof/output (completed without evidence)
- Average time from Ready to Done
- Dispatch success rate (Cards claimed vs Cards available)

These are wiki dashboard pages (`reports/`) generated by `wiki compile`, or Workboard diagnostics. Native.

---

## 11. Safety and Permissions

Foundry enforces Workspace boundaries at the tool layer, not only through prompts.

An agent may only:
- check in to permitted Workspaces;
- search permitted Workspaces;
- work Cards assigned to permitted Workspaces;
- write back within the Workspace's approval rules.

Cross-Workspace writes always require explicit approval.

---

## 12. Redaction

Sources are append-only, but visibility can be redacted.

Redaction does not rewrite history by default. It records a `source.redacted` event and hides the relevant content from normal search, Ask, and worker context. Administrators may retain the original for audit, or purge it where required by policy or law.

---

## 13. Deploying to a New Organisation

1. Add the Workspace to the Foundry Manifest
2. `openclaw wiki init --path <vault-path>`
3. `openclaw workboard board-create <board-name>`
4. Add the foundry skills to relevant agents
5. (Optional) Seed Pages with existing knowledge
6. (Optional) `git init` the vault

No infrastructure. No hosting. No database. It runs wherever OpenClaw runs.

---

## 14. Implementation Plan

### Phase 1: Kernel — Check In

Build:
- Workspace manifest schema
- Source / Page / Card / Link / Event logical model
- `foundry_checkin` tool (distillation skill + wiki writes + card creation)
- `foundry_search` and `foundry_get` tools
- Channel-to-Workspace resolver
- Idempotency registry

**Gate:** A Slack thread can be checked in. It creates one Source, updates one or more Pages, creates zero or more Cards with objectives and definitions of done. The thread receives a clear confirmation. Checking in the same thread twice is handled gracefully.

### Phase 2: Work Loop — Execution

Build:
- `foundry_card_create` and `foundry_card_update` tools
- Worker context injection (load linked Pages/Sources into worker prompt)
- Human-triggered execution ("work on the next card")
- Proof/output attachment on completion
- Knowledge write-back with controlled rules

**Gate:** An agent can pick up a Ready Card, load relevant Pages/Sources as context, execute the work, and complete it with proof. Write-back rules are enforced.

### Phase 3: Blocked Loop + Event Delivery

Build:
- Reverse-path hook (`message:received` → card unblock + source append)
- Blocked Card → question posted to originating thread
- Human reply → Card unblocked → re-queued with new context
- Comment capture on Cards
- Event delivery layer: configurable per-Workspace notification publishing to Slack
- Workspace manifest `notifications` config section
- Delivery formatting for all core event types (checkin, card lifecycle, decisions)
- Optional digest summaries (daily/weekly rollups)

**Gate:** An agent blocks a Card with a question. The question appears in Slack. A human replies. The Card unblocks, the agent resumes with the answer, and completes the work. The full exchange is captured as events. Additionally, card lifecycle events (claimed, completed, blocked, failed) and check-in completions are published to the Workspace's notification channel.

### Phase 4: Auto-Dispatch — Autonomous Execution

Build:
- Auto-dispatch configuration (Workspace-level toggle, default off)
- Workboard dispatch integration
- Concurrency controls
- Failure intelligence (learnings capture)

**Gate:** A Workspace with `autoDispatch: true` sees Cards created by check-in start executing without human intervention. Cards created by check-in on a default Workspace require human triggering.

### Phase 5: Decomposition — Complex Work

Build:
- Sub-Card creation (manual and agent-initiated)
- Parent/child lifecycle sync (parent Done when all children Done)
- Dependency-aware dispatch (children execute in order or parallel as appropriate)

**Gate:** A large Card gets decomposed into 4 sub-Cards. Sub-Cards execute independently. Parent Card completes when all children complete.

### Phase 6: Dashboard + Polish

Build:
- Three-tab dashboard (Knowledge, Work, Sources)
- Workspace switcher
- Observability dashboards
- Recurring Card templates
- Git-backed vault automation
- Multi-org deployment playbook

**Gate:** Humans can see what Foundry knows, what happened, and what needs doing — across multiple Workspaces.

---

## 15. Migration from v1

| v1 Data | New Home |
|---|---|
| `pages` table | Wiki Pages (Knowledge or Playbook) |
| `decisions` table | Decision blocks on Knowledge Pages |
| `tasks` table | Workboard Cards |
| `sessions` table | Wiki Sources |
| `runs` table | Events on Cards |
| `conversations` table | Events on Cards / Sources |
| Everything else | Historical export / archive |

Selective migration. Active work and recent knowledge. Don't migrate noise.

Run v1 and the new system in shadow mode for a few check-ins before cutting over. Compare outputs. Then shut v1 down.

---

## 16. The Whole System

```
 Humans + Agents
       │
       ▼
    OpenClaw
    messaging · agents · tools
       │
       ▼
    Foundry
    check in · ask · work
       │
  ┌────┼────┐
  ▼    ▼    ▼
Sources  Pages  Cards ──→ Agent Executes ──→ Done (proof)
what     what   what                    ↕
happened we know to do              Blocked ──→ Human Replies ──→ Resumes
  │                                     │
  └──────── Links + Events ─────────────┘
       │
       ▼
   Workspace
```

That's the architecture.

---

## 17. First Build Scope

The first implementation should only prove:

1. Check in a Slack thread.
2. Create one Source.
3. Update one or more Pages.
4. Create zero or more valid Cards.
5. Search and retrieve the result.
6. Work one Card manually.
7. Complete it with proof.

Do not build auto-dispatch, dashboard polish, recurring Cards, or complex decomposition until this loop works reliably.

---

## 18. Quality Bar

Foundry is working when:

- check-ins are trusted, not noisy;
- Pages become more useful over time;
- Cards are executable without re-reading the whole conversation;
- agents can answer with provenance;
- humans can understand why a Card exists;
- failed work produces useful learning;
- the system feels smaller as it becomes more capable.

---

*Foundry is an execution engine that builds institutional knowledge as a side effect of getting work done.*

*Check in a conversation. Foundry remembers what matters and tracks what needs doing.*
