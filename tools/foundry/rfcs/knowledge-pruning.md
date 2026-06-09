# RFC: Knowledge Pruning — Ground-Truth Reconciliation

> Status: Draft
> Date: 2026-06-09
> Authors: Andrew, Mimir

## Problem

Foundry accumulates knowledge through check-ins. Without pruning, the wiki
becomes a landfill: stale findings, superseded decisions, speculative pages
that never led anywhere. Human curation doesn't scale and won't happen.

## Core Insight

**The codebase is the oracle.** Decisions checked into Foundry either get
implemented or they don't. Findings are either reflected in what was built or
they were noise. The ground truth isn't in the wiki — it's in the repos,
configs, deployed services, and running systems that the wiki describes.

A pruning system that requires human judgement to classify "keep vs discard"
is just a slower version of not pruning. The system should reconcile knowledge
against reality and prune what reality has already discarded.

## How It Works

### 1. Reconciliation Pass

A background agent periodically traverses the wiki and asks one question per
page: **does this still reflect reality?**

For each page, it gathers evidence:

- **Code references:** Does the codebase contain what this page describes?
  Search repos for function names, config keys, architecture patterns.
- **Recency signal:** When was this page last linked from a new Source or Card?
  Pages nobody references are likely stale.
- **Decision outcomes:** Did the decisions on this page get implemented? Check
  the code. A decision that says "use Cloudflare D1" is confirmed if D1 is in
  the stack, superseded if it's been replaced.
- **Card completion:** Did Cards spawned from this page's Source actually get
  done? Or were they cancelled/abandoned?

### 2. Classification (automatic, no human queue)

Each page gets a vitality score from the reconciliation pass:

- **Active** — referenced recently, confirmed by code, decisions implemented
- **Settled** — historically accurate but no longer evolving (e.g. a completed
  migration). Keep but deprioritise in search/context.
- **Stale** — no references in 30+ days, no code evidence, no active Cards.
  Candidate for archival.
- **Contradicted** — code evidence contradicts the page's claims. Flag the
  contradiction; the page's knowledge is wrong.

### 3. Consolidation (merge, don't just delete)

When multiple pages cover the same ground (common after several check-ins
about the same topic), the reconciler proposes a merge:

- Identify overlapping pages by semantic similarity + shared entity references
- Produce a single consolidated page with the union of confirmed findings
  and current decisions
- Archive the originals as Sources (they become provenance, not active
  knowledge)

### 4. Archival (not deletion)

Pruned pages move to an `archive/` folder. They're excluded from search and
agent context, but preserved for provenance. Nothing is destroyed — it's just
removed from the active working set.

## What Runs This

A local model is the right fit. The reconciliation pass is high-volume,
low-stakes work:

- Read every page (small context per page)
- Search codebases for evidence (grep, file existence checks)
- Score and classify
- Propose merges where overlap is high

This runs continuously or on a schedule. It doesn't need Opus — a capable
local model (Qwen, Llama) with tool access to the filesystem is sufficient.
The expensive part is the initial traversal; incremental passes only need to
re-check pages with new activity.

## What This Is Not

- Not a human curation queue (no "approve this prune" step)
- Not a RAG system (that's a consumer of curated knowledge, not the curator)
- Not a rewrite engine (it classifies and consolidates, it doesn't invent)
- Not a replacement for check-in quality (garbage in → garbage archived)

## Open Questions

1. **Threshold tuning:** What staleness threshold triggers archival? 30 days
   with no references? 60? Should it vary by page type?
2. **Contradiction handling:** When code contradicts a decision, should the
   system auto-update the page or just flag it? (Leaning toward flag-only —
   contradictions might reveal bugs, not just stale docs.)
3. **Cross-workspace reconciliation:** If Heimdall and Laurion both have pages
   about the same entity, should the pruner notice? Or is that out of scope?
4. **Merge approval:** Is fully automatic merge too aggressive? A middle ground
   might be: merge automatically when overlap > 80% and no conflicting
   decisions; flag for review otherwise.
5. **RAG graduation:** When does curated knowledge move into an embedding
   index? Is that a separate concern or part of the same pipeline?
