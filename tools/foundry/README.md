# Foundry

> Check in a conversation. Foundry remembers what matters and tracks what needs doing.

Foundry is an execution engine that builds institutional knowledge as a side effect of getting work done. It composes two native OpenClaw plugins — **Memory Wiki** and **Workboard** — into a unified check-in → knowledge → execution loop.

## Status

**Phase 2** — Work Loop complete. Check In produces Sources + Pages + Cards. Work Loop picks up Cards, loads wiki context, executes, completes with proof and write-back.

## How it works

Foundry has four concepts and three verbs:

| Concept | Meaning | Backed by |
|---------|---------|-----------|
| **Workspace** | The boundary | Wiki vault + Workboard board + manifest config |
| **Source** | What happened | Wiki `sources/` (append-only Markdown) |
| **Page** | What we know | Wiki `entities/`, `concepts/`, `syntheses/` |
| **Card** | What needs doing | Workboard card |

| Verb | What it does |
|------|-------------|
| **Check in** | Capture a Source, distil it into Pages and Cards |
| **Ask** | Answer from Pages and Sources with provenance |
| **Work** | Execute Cards and write back useful knowledge |

## Prerequisites

- OpenClaw ≥ 2026.6.1
- `memory-wiki` plugin enabled
- `workboard` plugin enabled

## Directory layout

```
tools/foundry/
├── README.md              ← you are here
├── ARCHITECTURE.md        ← Rev 7 full architecture doc
├── config/
│   └── manifest.json      ← workspace definitions
├── skills/
│   └── SKILL.md           ← Check In, Search, Get, Work, Card Create/Update procedures
└── lib/
    └── resolver.py        ← channel→workspace routing, vault/board path expansion
```

## Workspace manifest

See `config/manifest.json` for the workspace definitions. Each workspace maps to:
- A Memory Wiki vault (physically isolated, Git-backed)
- A Workboard board (logically isolated)
- Channel routing rules

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full Rev 7 design.

## Implementation phases

| Phase | Name | Gate |
|-------|------|------|
| **0** | Foundation & Cleanup | ✅ Plugins enabled, vaults init'd, v1 archived |
| **1** | Kernel — Check In | ✅ Thread checked in → Source + Pages + Cards |
| **2** | Work Loop — Execution | ✅ Agent picks up Card, executes with wiki context, completes with proof |
| **3** | Blocked Loop | Agent blocks → human replies → agent resumes |
| **4** | Auto-Dispatch | Cards auto-execute on opt-in workspaces |
| **5** | Decomposition | Parent/child card lifecycle |
| **6** | Dashboard + Polish | Three-tab UI, observability, multi-org playbook |
