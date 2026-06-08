# Foundry — Check-In Skill

> Foundry is an execution engine that builds institutional knowledge as a side effect of getting work done.

This skill defines the procedures for Foundry's three verbs: **Check In**, **Search**, and **Get**.

## Trigger Recognition

Respond to these patterns (and natural variants):
- `check this in` / `check this in to {workspace}`
- `commit this thread` / `commit this to {workspace}` (legacy alias)
- `what does {workspace} know about ...` (Search)
- `search {workspace} for ...` (Search)

---

## 1. Check In Procedure

### Step 1: Resolve Workspace

Load the manifest at `~/.openclaw/workspace/lobkit/tools/foundry/config/manifest.json`.

Match the current channel ID against the manifest's workspace channel definitions:
- If the channel has a `default: true` workspace → use that workspace
- If the user specifies a workspace name (e.g. "check this into Heimdall") → use that, if the channel is permitted
- If no match and no explicit target → ask the user which workspace

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

## Source ID Convention

`src_slack_{channel_id}_{thread_ts_integer}`

Where `thread_ts_integer` is the Slack thread timestamp with the decimal point removed.

Example: channel `C0AQFJDT2HE`, thread `1780900339.091249` → `src_slack_C0AQFJDT2HE_1780900339091249`
