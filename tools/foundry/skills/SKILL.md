---
name: foundry
description: Check in Slack threads and conversations to Foundry workspaces as institutional knowledge. Responds to "check this in", "check this in to {workspace}", "commit this thread", "what does {workspace} know about...", "work on {card}", and similar patterns. Routes by agent ID to the correct workspace (Heimdall, Slate, Laurion).
---

# Foundry Skill

> Foundry is an execution engine that builds institutional knowledge as a side effect of getting work done.

This skill defines the procedures for Foundry's three verbs: **Check In**, **Ask/Search/Get**, and **Work**.

## Trigger Recognition

Respond to these patterns (and natural variants):
- `check this in` / `check this in to {workspace}` (Check In)
- `commit this thread` / `commit this to {workspace}` (legacy alias for Check In)
- `what does {workspace} know about ...` (Search)
- `search {workspace} for ...` (Search)
- `work on the next {workspace} card` / `pick up "{card title}"` (Work)
- `work on {card_id}` (Work)

---

## 1. Check In Procedure

### Step 1: Resolve Workspace

Load the manifest at `~/.openclaw/workspace/lobkit/tools/foundry/config/manifest.json`.

Routing is *agent-based* (manifest v2). Determine your agent ID (e.g. `main` for Mimir, `ed` for Ed, `themis` for Themis), then:

1. If the user specifies a workspace name (e.g. "check this into Heimdall") → use that, if your agent ID is in its `agents` list
2. If no explicit target → use the workspace where your agent ID appears in `defaultFor`
3. If your agent serves multiple workspaces and none is default → ask the user: "Which workspace? I serve Heimdall and Laurion."
4. If your agent is not in any workspace's `agents` list → refuse: "I'm not configured for any Foundry workspace."

You can resolve from *any channel* you're present in — routing follows the agent, not the channel.

Record: `workspace_id`, `vault_path`, `board_id`

### Step 2: Check Idempotency

Look for an existing source file in `{vault_path}/sources/` whose frontmatter contains the same `uri` (e.g. `slack://{channel_id}/{thread_ts}`).

- If found and content unchanged → reply: "This was already checked in on {date}. Want me to update it with new replies?"
- If found and new replies exist → proceed with append mode (add new content to Source, re-distil)
- If not found → proceed with full check-in

### Step 3: Fetch Thread Content

Read the full Slack thread. Capture:
- All messages (with author, timestamp, text)
- File attachments (names, descriptions)
- Reactions (notable ones)
- Thread participants

### Step 4: Distil

This is the core LLM step. Process the raw thread content and produce structured output:

```yaml
title: "Concise thread title (3-8 words)"
summary: "2-4 sentence summary of what was discussed and decided"
findings:
  - text: "A factual finding or observation worth recording"
    confidence: 0.9
    entity: "optional-entity-slug"
  - text: "Another finding"
    confidence: 0.8
decisions:
  - text: "The decision that was made"
    why: "Rationale for the decision"
    status: current
    entity: "entity-slug-this-belongs-on"
  - text: "Another decision"
    why: "..."
    status: current
action_items:
  - title: "Card title — imperative, specific"
    objective: "What needs to be done, in enough detail to start"
    definition_of_done: "How to know this is finished"
    priority: "high|normal|low"
    labels: ["label1", "label2"]
  - title: "Another card"
    objective: "..."
    definition_of_done: "..."
entities:
  - slug: "entity-slug"
    name: "Human Name"
    type: "knowledge|playbook"
    folder: "entities|concepts"
```

**Distillation rules:**
- A finding is factual — something observed, learned, or established
- A decision is a choice that was made — it has a "why" and can be superseded later
- An action item becomes a Card ONLY if it has: (1) a clear objective, (2) a definition of done, (3) enough context to start, (4) a genuine expectation of execution
- Vague intentions ("we should look into X") are findings, NOT cards
- Not every check-in produces cards — that's fine
- Prefer fewer, higher-quality cards over many vague ones

### Step 5: Write Source

Create `{vault_path}/sources/{source_id}.md`:

```markdown
---
pageType: source
id: {source_id}
title: "{title}"
workspace: {workspace_id}
type: slack_thread
uri: "slack://{channel_id}/{thread_ts}"
participants: ["{user1}", "{user2}"]
captured_at: "{ISO-8601}"
content_hash: "{sha256 of raw thread text}"
status: committed
---

# {title}

## Summary
{summary}

## Thread Content

{Full thread messages, formatted as:}

**{Author}** ({timestamp}):
{message text}

---

**{Author}** ({timestamp}):
{message text}
```

### Step 6: Write/Update Pages

For each entity identified in distillation:

**New entity page** at `{vault_path}/{folder}/{slug}.md`:

```markdown
---
pageType: entity
id: {folder}.{slug}
title: "{name}"
entityType: {knowledge|playbook}
status: active
updatedAt: "{ISO-8601}"
sources:
  - {source_id}
claims: []
---

# {name}

## Summary
<!-- openclaw:wiki:summary:start -->
{Summary of what we know about this entity, drawn from the check-in}
<!-- openclaw:wiki:summary:end -->

## Findings
<!-- openclaw:wiki:findings:start -->
{Each finding as a bullet point}
<!-- openclaw:wiki:findings:end -->

## Decisions
<!-- openclaw:wiki:decisions:start -->
{Each decision as a structured block:}
- **Decision:** {text}
  **Why:** {rationale}
  **Source:** {source_id}
  **Status:** current
  **Date:** {date}
<!-- openclaw:wiki:decisions:end -->

## Sources
<!-- openclaw:wiki:sources:start -->
- [{source_id}](../sources/{source_id}.md) — {title} ({date})
<!-- openclaw:wiki:sources:end -->
```

**Existing entity page** — append new findings/decisions to the relevant managed blocks. Do NOT overwrite existing content — add to it. For decisions that supersede existing ones, mark the old decision's status as `superseded` and add the new one.

### Step 7: Create Cards

For each action item from the distillation, create a workboard card:

```bash
openclaw workboard create "{title}" \
  --board {board_id} \
  --notes "Objective: {objective}\n\nDefinition of Done: {definition_of_done}\n\nSource: {source_id}" \
  --priority {priority} \
  --labels "{labels}" \
  --status todo \
  --json
```

Record the card ID for the confirmation message.

### Step 8: Update Indexes

Run `openclaw wiki compile` to refresh the vault indexes and digests.

### Step 9: Git Commit

```bash
cd {vault_path} && git add -A && git commit -m "checkin: {title} [{source_id}]"
```

### Step 10: Post Confirmation

Reply in the originating Slack thread with a summary:

```
✅ *Checked in to {Workspace}*

*Source:* {title}

*Pages updated:*
• {entity1} — {what changed}
• {entity2} — {what changed}

*Decisions recorded:*
• {decision1 summary}

*Cards created:*
• {card1 title} (#{card_id_prefix})
• {card2 title} (#{card_id_prefix})

{Or: "No cards created — this check-in captured knowledge only."}
```

---

## 2. Search Procedure

When asked "what does {workspace} know about X" or "search {workspace} for X":

1. Resolve workspace from the query or channel default
2. Run `openclaw wiki search "{query}"` against the workspace vault
3. If cards are relevant, also run `openclaw workboard list --board {board_id} --json` and filter
4. Synthesise an answer with provenance — cite source IDs and page paths
5. If no results, say so clearly: "The {workspace} workspace has no knowledge about X yet."

---

## 3. Get Procedure

When asked to retrieve a specific Source, Page, or Card:

- **Source:** `openclaw wiki get sources/{source_id}` or read the file directly
- **Page:** `openclaw wiki get {folder}/{slug}` or read the file directly  
- **Card:** `openclaw workboard show {card_id}`

---

## File Locations

| What | Where |
|------|-------|
| Manifest | `~/.openclaw/workspace/lobkit/tools/foundry/config/manifest.json` |
| Heimdall vault | `~/.openclaw/wiki/heimdall/` |
| Sources | `{vault}/sources/{source_id}.md` |
| Entity pages | `{vault}/entities/{slug}.md` |
| Concept pages | `{vault}/concepts/{slug}.md` |
| Synthesis pages | `{vault}/syntheses/{slug}.md` |
| Cards | Workboard SQLite (accessed via CLI/tools) |

---

## 4. Work Procedure

Triggered by: `work on the next {workspace} card`, `pick up "{title}"`, `work on {card_id}`

### Step 1: Resolve Card

**By next card:**
1. Resolve workspace from channel or explicit name
2. `openclaw workboard list --board {board_id}` and filter for `todo` or `ready` status
3. Pick the highest-priority card, then oldest by creation date
4. If no cards available, reply: "No ready cards on the {workspace} board."

**By title or ID:**
1. `openclaw workboard show {card_id}` or search by title prefix
2. Verify the card is in a workable state (todo/ready/backlog)

### Step 2: Claim the Card

Use the Workboard agent tool to claim:
- Call `workboard_claim` with the card ID
- Card moves to `running` status
- Record the claim token for later completion

If no agent tool is available, note claim in the card notes and proceed.

### Step 3: Load Context

Read the card's notes to extract:
- **Objective** — what needs to be done
- **Definition of Done** — how to verify completion
- **Source ID** — the originating source

Then load linked context from the wiki vault:
1. If a Source ID is referenced → read `{vault}/sources/{source_id}.md`
2. Search wiki for related pages → `openclaw wiki search "{card title keywords}"`
3. Read the most relevant entity/concept pages for background

This context injection is what makes Foundry cards executable — the agent doesn't need to re-read the original conversation.

### Step 4: Execute

Do the work described in the objective. This could be:
- Writing code, documents, or analysis
- Running commands or making API calls
- Researching and synthesising information
- Creating files, PRs, or deployments

During execution:
- Call `workboard_heartbeat` periodically on longer tasks (every 5-10 min)
- Use `workboard_worker_log` to record significant milestones
- If stuck → go to Step 6 (Block)

### Step 5: Complete with Proof

When the objective is met and the definition of done is satisfied:

1. Gather proof of completion:
   - File paths, PR links, test output, screenshots, etc.
   - A brief summary of what was done and any notable findings

2. Call `workboard_complete` with:
   - `summary`: What was accomplished
   - `proof`: Evidence of completion (links, output, etc.)

3. Knowledge write-back (if applicable):
   - **Findings** discovered during work → append to relevant wiki Pages
   - **Playbook improvements** → update concept pages if procedures were refined
   - **New decisions** → DO NOT write directly. Note in completion summary; requires check-in or human approval.
   - **Cross-workspace writes** → NEVER. Flag in summary for human action.

4. Git commit the vault changes:
   ```bash
   cd {vault_path} && git add -A && git commit -m "work: {card_title} [card:{card_id_prefix}]"
   ```

5. Post completion confirmation:
   ```
   ✅ *Card complete: {title}*
   
   *Summary:* {what was done}
   *Proof:* {evidence}
   *Write-back:* {pages updated, or "none"}
   ```

### Step 6: Block (if stuck)

When the work cannot proceed without external input:

1. Call `workboard_block` with:
   - `reason`: Clear description of what's needed

2. Post the question to the originating thread (or workspace default channel)

3. The card stays in `blocked` status until a human replies
   (Phase 3 adds the automated unblock hook; for now, manual unblock)

### Write-Back Rules

| Write-back type | Allowed during Work? |
|---|---|
| Proof links (PR, test output, doc) | ✅ Yes — attach to card |
| Output summary | ✅ Yes — attach to card |
| New finding on a Page | ✅ Yes — append to findings block |
| Playbook refinement | ⚠️ Maybe — small updates OK, major rewrites need approval |
| New decision on a Page | ❌ No — requires check-in or human approval |
| Supersede existing decision | ❌ No — requires check-in or human approval |
| Cross-workspace write | ❌ Never — flag for human action |

---

## 5. Card Create Procedure

To create a card outside of check-in (ad-hoc work):

```bash
openclaw workboard create "{title}" \
  --board {board_id} \
  --notes "Objective: {what to do}\n\nDefinition of Done: {how to verify}\n\nSource: {source_id or 'manual'}" \
  --priority {low|normal|high|urgent} \
  --labels "{comma,separated}" \
  --status todo
```

Every card MUST have an objective and definition of done in the notes. Cards without these are not valid Foundry cards.

---

## 6. Card Update Procedure

For state changes outside of the Work flow:

- **Add comment:** `workboard_comment` with the card ID and note text
- **Attach proof:** `workboard_proof` with evidence reference
- **Unblock:** `workboard_unblock` when a blocked card receives its answer
- **Reassign:** `workboard_reassign` to change ownership
- **Decompose:** `workboard_decompose` to fan out a large card into children

---

## 7. Event Delivery Procedure

After every Foundry action that produces an event, check the workspace's `notifications` config and post formatted messages to the configured channel.

### When to deliver

Look up `notifications.on.{event_type}` in the workspace manifest. Only post if the event type is `true`.

### Message formats

| Event | Format |
|---|---|
| `checkin.complete` | 📥 *Checked in:* {title} — {N} pages updated, {M} cards created |
| `card.created` | 📌 *New card:* {title} ({priority}) |
| `card.claimed` | 🔨 *{agent}* picked up: *{title}* |
| `card.completed` | ✅ *Done:* {title} — {proof summary} |
| `card.blocked` | 🚫 *Blocked:* {title} — {question} |
| `card.failed` | ❌ *Failed:* {title} — {reason} |
| `card.unblocked` | 🔓 *Unblocked:* {title} — re-queued |
| `page.decision_recorded` | 📋 *Decision:* {text} — on {page} |

### Delivery rules

- Post to `notifications.channel` (from the workspace manifest)
- If `notifications.channel` is null → skip delivery (workspace has no notification channel)
- `card.blocked` questions are ALSO posted to the *originating thread* (reverse-path) — not just the notification channel
- Delivery is best-effort — a failed notification does not block the action
- Keep messages concise — one line per event, not walls of text

### Integration with existing procedures (MANDATORY)

Event delivery is *not optional*. Every Foundry action MUST post its notification.

- *Check In* (§1 Step 10): after posting the in-thread confirmation, ALSO post `checkin.complete` to the notification channel
- *Work* (§4 Step 2): post `card.claimed` when claiming a card
- *Work* (§4 Step 5): post `card.completed` when completing with proof
- *Work* (§4 Step 6): post `card.blocked` to BOTH the notification channel AND the originating thread
- *Card Create* (§5): post `card.created` to the notification channel
- *Decisions*: post `page.decision_recorded` for each decision recorded during check-in

Use `notify.py` (`tools/foundry/lib/notify.py`) to format messages consistently, or format manually following the templates above. The notification channel comes from the workspace manifest's `notifications.channel` field.

Skip delivery only if `notifications.channel` is null (workspace has no notification target configured).

---

## 8. Blocked Loop Procedure

The blocked loop is the conversational work cycle: agent works → hits a wall → asks a question → human answers → agent resumes.

### Blocking a Card

1. During Work (§4 Step 6), when the agent cannot proceed:
2. Update the card to `blocked` status with the reason
3. Post the question to:
   - The *originating Slack thread* (where the source was checked in) — this is the reverse-path
   - The workspace notification channel (if `card.blocked` is enabled)
4. Record the blocked state:
   - `blocked_reason`: the question
   - `blocked_thread`: `slack://{channel}/{thread_ts}` where the question was posted
   - `blocked_at`: timestamp

### Unblocking a Card

When a human replies to the blocked question:

1. Read the reply content
2. Append the reply to the Source (if one exists for this thread)
3. Update the card:
   - Move from `blocked` → `todo` (re-queued for work)
   - Add the human's answer to the card notes as context
4. Fire `card.unblocked` delivery (if enabled)
5. If `autoDispatch` is on, the card will be picked up automatically
6. If manual, the agent or human can trigger `work on {card}` to resume

### How unblocking works (Phase 3 implementation)

In Phase 3, unblocking is *agent-mediated* — when I see a reply in a thread where I posted a blocked question, I recognise it as an unblock signal and process it. The agent is already a participant in the thread.

A fully automated reverse-path hook (OpenClaw plugin that watches all messages and auto-routes to blocked cards) is a Phase 4+ enhancement. The Phase 3 implementation proves the loop works; automation makes it hands-free.

---

## 9. Auto-Dispatch Procedure

Auto-dispatch enables Workspaces to execute Ready cards without human triggering.

### Configuration

In the workspace manifest, set `autoDispatch: true` on a workspace. Also configure dispatch limits:

```json
"dispatch": {
  "maxConcurrent": 3,
  "failurePolicy": "block-after-2",
  "workerModel": null
}
```

### How it works

1. A periodic dispatch cycle runs (via cron or manual `openclaw workboard dispatch`)
2. Workboard's native dispatch engine:
   - Promotes dependency-ready cards
   - Cleans stale claims and timed-out runs
   - Selects up to 3 Ready cards (by priority, then oldest)
   - Starts a worker sub-agent session for each
3. Each worker receives:
   - The card's title, notes (objective + definition of done), and claim token
   - Access to wiki tools (`wiki_search`, `wiki_get`) for context loading
   - The Workboard worker protocol (`workboard_heartbeat`, `workboard_complete`, `workboard_block`)
4. The worker executes autonomously:
   - Reads wiki context (linked Pages/Sources from card notes)
   - Does the work
   - Calls `workboard_complete` with summary + proof, or `workboard_block` if stuck

### Triggering dispatch

*Manual:* `openclaw workboard dispatch` (CLI) or `/workboard dispatch` (Slack)
*Periodic:* Cron job running dispatch every N minutes for auto-dispatch workspaces
*On check-in:* When `autoDispatch` is true, dispatch runs after a check-in creates Ready cards

### Failure intelligence

When a worker fails or a card is blocked repeatedly:

1. The failure reason is recorded on the card (via workboard events)
2. If `failurePolicy: "block-after-2"` → card moves to `blocked` after 2 failed attempts
3. Findings from the failure (what went wrong, what was tried) should be written back to the relevant wiki Page as a finding
4. This is the "failed work produces useful learning" principle from the quality bar

### Concurrency controls

- `maxConcurrent`: maximum simultaneous workers per workspace (default: 3)
- Workboard dispatch natively avoids duplicate claims and limits starts per pass
- One card per owner/agent per dispatch pass
- Cards with active claims are skipped

### Enabling auto-dispatch for a workspace

This is a maturity upgrade. Only enable when:
- Check-in quality is proven (cards have good objectives and DoD)
- The wiki has enough context for workers to execute independently
- Human review of completed work is in place

---

## 10. Decomposition Procedure

When a card's objective is too large for a single execution, decompose it into child cards.

### When to decompose

- *At check-in time:* the distillation recognises multi-step work and creates a parent + children
- *During execution:* a worker realises the card is too large and decomposes before proceeding
- *By human request:* "break this down into steps"
- *Rule of thumb:* if the objective has more than 3 distinct deliverables, or would take a worker >30 minutes, decompose

### How to decompose

*Step 1:* Identify the parent card (the large objective)

*Step 2:* Break the objective into 2-6 independently executable child cards. Each child must have:
- Its own title (imperative, specific)
- Its own objective (scoped to one deliverable)
- Its own definition of done
- Inherited board and labels from parent

*Step 3:* Create children via CLI:
```bash
for each child:
  openclaw workboard create "{child_title}" \
    --board {board_id} \
    --notes "Objective: {child_objective}\n\nDefinition of Done: {child_dod}\n\nParent: {parent_card_id}" \
    --priority {inherited_priority} \
    --labels "{inherited_labels}" \
    --status todo
```

*Step 4:* Link children to parent in the workboard SQLite:
```sql
-- For each child card, create a "child_of" link from the child to the parent
INSERT INTO workboard_card_links (id, card_id, ordinal, type, target_card_id, title, url, created_at)
VALUES ('{uuid}', '{child_id}', {ordinal}, 'child_of', '{parent_id}', '{parent_title}', NULL, {now_ms});
```
The `child_of` link type means "this card is a child of the target card". Query all children of a parent:
```sql
SELECT card_id FROM workboard_card_links WHERE target_card_id = '{parent_id}' AND type = 'child_of';
```

*Step 5:* Move the parent card to a holding status (or mark it as an orchestration card). The parent completes when all children are done.

### Lifecycle sync

- Children execute independently (potentially in parallel)
- Dispatch promotion: children stay in `todo` until dependencies (if any) reach `done`, then get promoted to `ready`
- When ALL children reach `done`, the parent card can be completed
- If any child is `blocked`, the parent is effectively blocked (but stays in its current status)
- The agent or dispatch cycle checks: "are all children done?" → if yes, complete the parent with a summary of all child outcomes

### Parent completion format

When completing a parent card after all children finish:
```
✅ *Parent complete: {title}*

*Sub-cards completed:*
• {child1_title} — {child1_proof_summary}
• {child2_title} — {child2_proof_summary}
• {child3_title} — {child3_proof_summary}

*Combined output:* {synthesis of all child results}
```

### What decomposition is NOT

- Not a way to create dependency chains (children are parallel by default)
- Not infinite recursion (max 2 levels deep: parent → children, no grandchildren)
- Not required (most cards are single-execution; decompose only when the objective is genuinely too large)

---

## Source ID Convention

`src_slack_{channel_id}_{thread_ts_integer}`

Where `thread_ts_integer` is the Slack thread timestamp with the decimal point removed.

Example: channel `C0AQFJDT2HE`, thread `1780900339.091249` → `src_slack_C0AQFJDT2HE_1780900339091249`
