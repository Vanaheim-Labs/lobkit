# Foundry — Installation Guide

> Install Foundry on any OpenClaw gateway in under 15 minutes.

Foundry is a knowledge and task engine that runs as a skill layer on top of two
standard OpenClaw plugins: **memory-wiki** (wiki vaults) and **workboard**
(task cards). There is no custom plugin to build — you configure the existing
plugins, register the Foundry skill, and your agents can start checking in
conversations immediately.

**Minimum OpenClaw version:** 2026.6.1

---

## What You Get

After installation, any agent on your gateway can:

- **Check in** a Slack thread → distils it into wiki pages (findings, decisions, entities) and workboard cards (action items)
- **Search** accumulated knowledge across wiki vaults
- **Work** on cards — claim, execute, complete with proof, or block with questions
- **Receive notifications** — check-in summaries, card events, decision records posted to configured Slack channels

---

## Prerequisites

| Requirement | How to check |
|---|---|
| OpenClaw ≥ 2026.6.1 | `openclaw --version` |
| `memory-wiki` plugin enabled | `openclaw config get plugins.entries.memory-wiki` |
| `workboard` plugin enabled | `openclaw config get plugins.entries.workboard` |
| Both plugins in `plugins.allow` list | `openclaw config get plugins.allow` |
| At least one agent configured | `openclaw agents` |
| Slack (or other messaging) connected | Agent receives messages |

If `memory-wiki` or `workboard` are not in your `plugins.allow` list, add them:

```bash
# Example: add to existing allow list
openclaw config patch plugins.allow '["memory-wiki", "workboard"]' --merge
```

---

## Step 1: Clone the Foundry Repository

```bash
cd ~/.openclaw/workspace
git clone https://github.com/Vanaheim-Labs/lobkit.git
# Foundry lives at: lobkit/tools/foundry/
```

If you already have the repo, pull latest:

```bash
cd ~/.openclaw/workspace/lobkit && git pull
```

---

## Step 2: Create Your Workspace Manifest

The manifest defines your Foundry workspaces — each is a named knowledge boundary
with its own wiki vault, workboard board, and agent permissions.

Copy the example manifest and edit it:

```bash
cp ~/.openclaw/workspace/lobkit/tools/foundry/config/manifest.example.json \
   ~/.openclaw/workspace/lobkit/tools/foundry/config/manifest.json
```

Or create `manifest.json` directly at
`~/.openclaw/workspace/lobkit/tools/foundry/config/manifest.json`:

```json
{
  "version": "2.0.0",
  "description": "Foundry workspace manifest",
  "workspaces": {
    "my-workspace": {
      "name": "My Workspace",
      "description": "What this workspace is for",
      "owner": "your-name",
      "vault": "~/.openclaw/wiki/my-workspace",
      "board": "my-workspace",
      "agents": ["main"],
      "defaultFor": ["main"],
      "notifications": {
        "channel": null,
        "thread": false,
        "on": {
          "checkin.complete": true,
          "card.claimed": true,
          "card.completed": true,
          "card.blocked": true,
          "card.failed": true,
          "page.decision_recorded": true
        }
      },
      "autoCheckin": false,
      "autoDispatch": false,
      "approvalRequired": [
        "more_than_5_cards",
        "updates_existing_decisions",
        "cross_workspace_reference"
      ]
    }
  }
}
```

### Manifest fields

| Field | Required | Description |
|---|---|---|
| `vault` | Yes | Path to the wiki vault directory. Use `~` for home. |
| `board` | Yes | Workboard board name (created on first card). |
| `agents` | Yes | Agent IDs permitted to read/write this workspace. Use `"main"` for your primary agent. |
| `defaultFor` | Yes | Agents that auto-route to this workspace when no explicit target is given. |
| `notifications.channel` | No | Slack channel ID for event notifications. `null` = no notifications. |
| `autoCheckin` | No | Reserved for future use. |
| `autoDispatch` | No | If `true`, ready cards are auto-dispatched to workers. |

### Multiple workspaces

Add as many workspaces as you need. Each agent can serve multiple workspaces,
but should have exactly one `defaultFor` workspace. If an agent serves multiple
and none is default, they'll be asked which one when checking in.

### Finding your agent IDs

```bash
openclaw agents
```

Your primary agent is typically `main` (or whatever ID your first agent has).
Named agents (e.g. `heimdall`, `themis`) use their configured `id`.

---

## Step 3: Create Wiki Vaults

For each workspace in your manifest, create and initialise the wiki vault directory:

```bash
# For each workspace vault path:
mkdir -p ~/.openclaw/wiki/my-workspace/sources
mkdir -p ~/.openclaw/wiki/my-workspace/entities
mkdir -p ~/.openclaw/wiki/my-workspace/concepts
cd ~/.openclaw/wiki/my-workspace && git init && git add -A && git commit -m "init: empty vault" --allow-empty
```

The check-in procedure creates `sources/`, `entities/`, and `concepts/`
subdirectories as needed, but pre-creating them ensures git tracks the structure
from the start.

### Configure the memory-wiki plugin

The `memory-wiki` plugin currently supports a single vault in its config.
Point it at whichever vault you consider primary:

```bash
openclaw config patch plugins.entries.memory-wiki '{
  "enabled": true,
  "config": {
    "vaultMode": "isolated",
    "vault": {
      "path": "~/.openclaw/wiki/my-workspace",
      "renderMode": "obsidian"
    },
    "render": {
      "preserveHumanBlocks": true,
      "createBacklinks": true,
      "createDashboards": true
    }
  }
}'
```

> **Note:** Foundry's skill procedures read/write vault directories directly
> (the paths come from the manifest), so all vaults work regardless of which one
> the memory-wiki plugin points to. The plugin config determines which vault
> gets `openclaw wiki compile` and agent-digest generation.

---

## Step 4: Enable the Workboard Plugin

If not already enabled:

```bash
openclaw config patch plugins.entries.workboard '{
  "enabled": true,
  "config": {}
}'
```

Ensure `workboard` is in your `plugins.allow` list:

```bash
openclaw config get plugins.allow
# If workboard is missing, add it:
openclaw config patch plugins.allow '["workboard"]' --merge
```

Workboard boards are created implicitly on first card creation — no explicit
setup needed. The `board` field in your manifest just needs to match what
you'll pass to `openclaw workboard create --board <name>`.

---

## Step 5: Register the Foundry Skill

This is the critical step that makes agents aware of Foundry. Add the Foundry
skills directory to your gateway's skill search path:

```bash
openclaw config patch skills.load.extraDirs '["~/.openclaw/workspace/lobkit/tools/foundry/skills"]'
```

After this, **all agents** on the gateway will see the Foundry skill in their
`available_skills` list. When a user says "check this in", the agent discovers
the skill, reads `SKILL.md`, and follows the procedure.

### Verify skill registration

Restart the gateway to pick up the new skill path:

```bash
openclaw gateway restart
```

Then check that agents see the skill:

```bash
# In any agent session, the Foundry skill should appear in available_skills
# You can verify by asking your agent: "What skills do you have?"
```

---

## Step 6: Add Foundry Guidance to Agent AGENTS.md (Recommended)

While the skill auto-discovery works, adding a short note to each agent's
`AGENTS.md` helps them recognise check-in requests more reliably:

Add this block to your agent's workspace `AGENTS.md`:

```markdown
## Foundry — Knowledge Check-In

When someone says "check this in", "commit this thread", or "check this in to {workspace}":
- Read the Foundry skill from your available_skills list
- Follow its Check In procedure
- The Foundry manifest at `~/.openclaw/workspace/lobkit/tools/foundry/config/manifest.json`
  defines your workspace routing
```

This is optional — the skill file contains all the instructions — but it
reduces the chance of an agent not recognising the trigger phrase.

---

## Step 7: Verify the Installation

Run these checks to confirm everything is wired up:

```bash
# 1. Manifest loads correctly
python3 ~/.openclaw/workspace/lobkit/tools/foundry/lib/resolver.py list

# 2. Agent routing works (replace 'main' with your agent ID)
python3 ~/.openclaw/workspace/lobkit/tools/foundry/lib/resolver.py resolve main

# 3. Wiki vaults exist and are git-tracked
ls ~/.openclaw/wiki/*/

# 4. Workboard responds
openclaw workboard list --json

# 5. Skill is registered (after gateway restart)
# Ask your agent: "check this in to [workspace]" in a Slack thread
```

---

## Step 8: Test a Check-In

In any Slack thread with some conversation content:

1. Say: `@YourAgent check this in` (or `check this in to My Workspace`)
2. The agent should:
   - Read the full thread
   - Distil findings, decisions, entities, and action items
   - Write a Source file to `~/.openclaw/wiki/my-workspace/sources/`
   - Create/update entity Pages in `~/.openclaw/wiki/my-workspace/entities/`
   - Create Workboard cards for action items
   - Reply with a confirmation summary

If the agent doesn't recognise the command, check:
- Is the skill directory in `skills.load.extraDirs`?
- Has the gateway been restarted since the config change?
- Does the agent's ID appear in the manifest's `agents` list for the target workspace?

---

## Configuration Reference

### File Locations

| File | Purpose |
|---|---|
| `lobkit/tools/foundry/skills/SKILL.md` | The Foundry skill — all check-in/search/work procedures |
| `lobkit/tools/foundry/config/manifest.json` | Workspace definitions — vaults, boards, agents, notifications |
| `lobkit/tools/foundry/lib/resolver.py` | Workspace routing utility |
| `lobkit/tools/foundry/lib/notify.py` | Event notification formatter |
| `~/.openclaw/wiki/<workspace>/` | Wiki vault directories |

### Notification Channel Setup

To receive Foundry event notifications in Slack, set the `notifications.channel`
field in your workspace manifest to a Slack channel ID:

```json
"notifications": {
  "channel": "C0AQFJDT2HE",
  "on": {
    "checkin.complete": true,
    "card.completed": true,
    "card.blocked": true
  }
}
```

Find your channel ID: open the channel in Slack → click the channel name →
scroll to the bottom of the "About" panel.

### Multi-Agent Setup

Each agent's `id` must appear in the workspace's `agents` array to be permitted.
Use `defaultFor` to set the auto-route target:

```json
"agents": ["main", "research-agent", "ops-agent"],
"defaultFor": ["research-agent"]
```

This means `research-agent` auto-routes here, while `main` and `ops-agent`
must specify the workspace explicitly (or it's their only permitted workspace).

---

## Updating Foundry

```bash
cd ~/.openclaw/workspace/lobkit && git pull
```

The skill file and manifest schema may evolve. After pulling:
- Review any changes to `SKILL.md` (the skill is self-contained; agents read it fresh each time)
- Check `manifest.json` against `manifest.schema.json` for new fields
- No gateway restart needed for skill content changes (agents read the file on demand)

---

## Uninstalling

To remove Foundry without affecting other gateway functionality:

```bash
# Remove the skill directory from the search path
openclaw config patch skills.load.extraDirs '[]'

# Optionally remove the AGENTS.md guidance from agents

# Wiki vaults and workboard cards persist — they're standard OpenClaw data
# Remove them manually if you want a clean slate:
# rm -rf ~/.openclaw/wiki/<workspace>
# openclaw workboard list --board <board> --json  # to review before deleting
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Agent says "I don't know how to check in" | Skill not registered | Verify `skills.load.extraDirs` includes the foundry skills path; restart gateway |
| Agent asks "which workspace?" | Agent serves multiple, none is default | Set `defaultFor` in manifest, or specify workspace explicitly |
| "Not permitted on workspace X" | Agent ID not in `agents` array | Add the agent's ID to the workspace's `agents` list in manifest |
| No notifications in Slack | `notifications.channel` is null | Set it to your Slack channel ID |
| Workboard cards not created | Workboard plugin not enabled | `openclaw config get plugins.entries.workboard` — ensure `enabled: true` |
| Wiki files not written | Vault directory doesn't exist | `mkdir -p ~/.openclaw/wiki/<workspace>/sources` |
| Git commit fails after check-in | Vault not a git repo | `cd ~/.openclaw/wiki/<workspace> && git init` |

---

*Foundry is part of [lobkit](https://github.com/Vanaheim-Labs/lobkit) — tools for multi-agent organisations.*
