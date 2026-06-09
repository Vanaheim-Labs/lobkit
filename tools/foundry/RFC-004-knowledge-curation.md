# RFC-004: Knowledge Curation

> Reality is the editor.

**Status:** Draft v2 — iterating
**Date:** 2026-06-09
**Authors:** Andrew, Mimir
**Feedback:** Heimdall v1 review incorporated

---

## 1. Problem

Foundry's check-in flow is write-heavy: conversations get committed, Pages get created, decisions get recorded. But there's no read-back loop. Nothing asks "is this still true?" or "did this actually happen?"

At 24 Pages this is manageable. At 240 it's a swamp. At 2,400 it's actively dangerous — agents retrieve stale knowledge and make decisions based on things that are no longer true.

The goal: an autonomous process that keeps the wiki retrievable, current, and grounded — with minimal or no human intervention.

---

## 2. Doctrine

This RFC does not introduce a new core concept.

Foundry has four concepts: Workspace, Source, Page, Card.
Foundry has three verbs: Check In, Ask, Work.

The Gardener is none of these. It is a *maintenance process* — an implementation detail that:

- reads Sources, Pages, Cards, Links, and Events;
- calculates Page health metadata;
- adjusts retrieval weighting;
- records curation Events;
- creates Cards only when human judgement is genuinely required.

If a proposed curation feature introduces a new product noun or a curation queue, it is probably wrong.

---

## 3. Core Insight

The most reliable signal for whether knowledge is still relevant isn't a human review — it's whether reality confirms it.

- A decision that was implemented lives in the codebase. Git proves it.
- A decision that was discussed but never shipped is noise.
- An entity page about a tool we actually use is vital. One about a tool we evaluated and passed on fades.
- A concept page that matches deployed architecture is canonical. One that describes a plan we abandoned is misleading.

The codebase, deployed services, active configurations, and completed Cards are ground truth. The wiki should converge toward them.

But code is ground truth *only for code-grounded knowledge*. Foundry also holds business relationships, people, strategy, market observations, and design rationale. Those need different evidence signals. The system must not punish non-code knowledge just because `git grep` can't find it.

---

## 4. Page Health

Every Page carries a small *health vector* — a set of diagnostic scores that together determine how the Page is treated in retrieval.

### 4.1 Health Vector

```yaml
health:
  retrieval_weight: 0.82    # composite — what RAG actually uses
  confidence: 0.91          # how well-supported the claims are
  currentness: 0.74         # how likely the content is still accurate
  usefulness: 0.63          # observed agent reference frequency
  implementation_evidence: 0.95  # code/config/deployment confirmation
  contradiction_risk: 0.08  # detected conflicts with other Pages or reality
  last_gardened_at: "2026-06-09T10:00:00Z"
```

The top-level `retrieval_weight` is the number RAG uses. It's computed from the vector components. The individual scores provide diagnostics when something goes wrong — you can see *why* a Page was downranked, not just that it was.

### 4.2 Why Not a Single Score

A single vitality number compresses too many ideas:

- A page about a *rejected* architecture has low currentness but high historical value.
- A page about a business relationship has no code evidence but may be critical.
- A foundational decision may be old, rarely referenced, and still canonical.
- A page may be frequently retrieved because agents are confused, not because it's good.

The vector keeps these concerns separate. Retrieval uses the composite. Diagnostics use the components.

### 4.3 Evidence Profiles

Different Page types need different evidence signals. The Gardener applies the right scoring model based on the Page's evidence profile:

| Profile | Applies to | Primary signals |
|---------|-----------|-----------------|
| `code_grounded` | Architecture, integrations, deployed services, technical decisions | Git grep, file existence, config presence, deployment state |
| `activity_grounded` | Recurring workflows, agent usage patterns, operating procedures | Card completion, execution frequency, reference logs |
| `source_grounded` | Business decisions, relationships, meeting outcomes, strategy | Source recency, linked Card outcomes, supersession |
| `reference_grounded` | Evergreen concepts, foundational decisions, domain knowledge | Agent retrieval frequency, citation in other Pages |

The profile can be inferred from Page type/tags or set explicitly. A Page about "Meta Cloud API Integration" is `code_grounded`. A Page about "Future Publishing" is `source_grounded`. A Page about "Role Division" is `reference_grounded`.

### 4.4 Retrieval Thresholds

| Retrieval weight | Effect |
|-----------------|--------|
| High (> 0.7) | Retrieved normally, full weight in RAG ranking |
| Medium (0.4–0.7) | Retrieved but lower-ranked |
| Low (0.1–0.4) | Excluded from default RAG queries, still available via direct search |
| Tombstoned (< 0.1) | Not used for agent context, retained for provenance and audit |

Pages are never deleted by the Gardener. Tombstoned Pages remain in the vault. Actual purge is a separate admin/policy action — rare, explicit, and logged. Foundry does not rewrite institutional history.

---

## 5. The Gardener

A background process that traverses the wiki and maintains Page health.

### 5.1 What It Does

On each pass, per Page:

1. **Score** — recalculate health vector components based on current signals and evidence profile
2. **Detect** — identify duplicates, contradictions, and supersession candidates
3. **Annotate** — update Page health metadata and add diagnostic notes
4. **Rank** — recompute `retrieval_weight` from the health vector
5. **Tombstone** — Pages below threshold drop out of default retrieval
6. **Log** — every scoring action recorded as a curation Event

### 5.2 Action Levels

The Gardener has four levels of intervention, ordered by risk:

| Action | Automated? | Example |
|--------|-----------|---------|
| **Score** | Always | Lower currentness because no evidence found |
| **Annotate** | Always | Add "possible contradiction with Page X" to health metadata |
| **Propose** | Always | Generate a suggested correction as a draft diff |
| **Apply** | Mechanical fixes only | Update a renamed file path, fix a broken link, correct a moved URL |

The Gardener may automatically score, annotate, downrank, and tombstone. It may auto-apply only mechanical corrections: renamed symbols, moved file paths, changed URLs, updated version numbers.

It may *not* silently change decisions, rationale, strategy, or business meaning. Those require check-in or explicit supersession — the same rule Rev 7.5 already enforces for decision blocks.

### 5.3 What It Doesn't Do

- No human approval queue or curation dashboard
- No lifecycle state machine to manage
- No "review these 15 pages" batch tasks
- No silent rewriting of institutional memory

For exceptional cases that genuinely require human judgement (e.g. two Pages with contradictory decisions and both are well-sourced), the Gardener creates a Card. This isn't a curation queue — it's the ordinary Foundry mechanism for work that requires judgement. These should be rare.

### 5.4 Where It Runs

The DGX Spark is the natural home:

- 121GB RAM, Blackwell GPU — can run a capable local model continuously
- No API costs for traversal (hundreds of pages × daily passes)
- Connected as an OpenClaw node — triggered via cron or runs as a persistent service
- Can access codebases, git repos, deployed configs via the network

Candidate models: Llama 3 70B (fits comfortably), or smaller models for specific sub-tasks (embedding, classification, claim extraction).

### 5.5 Traversal Strategy

Not all Pages need daily review. Frequency based on volatility:

| Evidence profile | Check frequency | Trigger |
|-----------------|----------------|---------|
| `code_grounded` | On relevant git push, or weekly | Git webhook, scheduled |
| `activity_grounded` | Weekly | Scheduled |
| `source_grounded` | Monthly, or on related Source check-in | Event-driven + scheduled |
| `reference_grounded` | Monthly | Scheduled |
| Reports (`kind: report`) | Not gardened — regenerated on demand | N/A |

---

## 6. Code Grounding

The sharpest signal. A Page about "Worker Bootstrap Protocol" should be confirmed by actual bootstrap code. A decision about "use Meta Cloud API for WhatsApp" should be confirmed by Meta webhook handlers in the codebase.

### 6.1 How It Works

```
Gardener reads Page
  → extracts key claims (entities, tools, patterns, decisions)
  → searches codebases for evidence (git grep, file scan, config check)
  → scores each claim: confirmed | unconfirmed | contradicted
  → updates implementation_evidence and contradiction_risk accordingly
```

### 6.2 What Counts as Evidence

- **File exists** — `worker/src/routes/meta-webhook.ts` confirms Meta integration
- **Git history** — commit messages referencing the decision/entity
- **Config presence** — wrangler.toml bindings, env vars, plugin configs
- **Import/usage** — code that imports or calls the thing the Page describes
- **Deployment state** — is the described service actually running?
- **Card completion** — a Card about "migrate to Meta Cloud API" was completed with proof

### 6.3 Distinguishing Absence from Contradiction

If a Page describes something with zero codebase evidence:

- **No evidence found** — the knowledge may be correct but unimplemented (a plan, a strategy, external knowledge). Implementation_evidence stays neutral; other signals determine health.
- **Evidence of absence** — the codebase explicitly contradicts the Page (Page says Twilio, code uses Meta). Contradiction_risk rises sharply; currentness drops.

The Gardener should distinguish these. "I can't find it" ≠ "I found the opposite."

---

## 7. Duplicate and Overlap Detection

### 7.1 What the Gardener Does Now

- Detects Pages with high content overlap (embedding similarity, shared entities, overlapping claims)
- Cross-links related Pages (adds `related` links)
- Identifies supersession candidates (newer Page covers same ground as older one)
- Suggests a canonical Page when multiple exist for the same topic

### 7.2 What It Doesn't Do Yet

Auto-merge is high-risk. Two Pages can look similar but serve different purposes ("OpenClaw Workboard" describes the primitive; "Foundry Work Loop" describes the operating pattern). Merging them would lose the distinction.

Auto-merge is a Phase 5+ capability, requiring:

```yaml
merge_confidence: > 0.95
same_primary_entity: true
no_conflicting_decisions: true
one_page_low_retrieval_weight: true
```

Until then: detect, link, suggest. Don't combine.

---

## 8. Reports

Reports are computed views, not durable knowledge:

```yaml
kind: report
computed: true
index: false     # excluded from RAG
```

Reports live in `reports/` and are regenerated by `wiki compile` or on demand. They cite Pages, Sources, and Cards, but they don't compete with knowledge Pages in retrieval.

Reports are *inputs to the Gardener* (the Stale Pages report is the seed of this whole system) but are not themselves gardened. They don't have health vectors.

---

## 9. RAG Integration

Page health becomes the quality layer for retrieval:

```
Query → retrieve candidate Pages → rank by (relevance × retrieval_weight) → return top-k
```

High-weight Pages dominate retrieval. Low-weight Pages are noise-filtered before reaching the agent. RAG quality improves automatically as the Gardener maintains scores — no separate embedding curation step.

### 9.1 Embedding Strategy

- Embed Pages with `retrieval_weight > threshold` into vector store
- Re-embed when content changes or weight crosses a threshold boundary
- Drop embeddings when weight falls below inclusion threshold
- Vector store: Cloudflare Vectorize (distributed queries) or local FAISS on Spark (local model access)

### 9.2 Retrieval with Provenance

When an agent uses `Ask`, the response should include:

- Which Pages contributed to the answer
- The health status of those Pages (so the agent knows if it's drawing on shaky ground)
- Links back to Sources for verification

If key Pages have low confidence or high contradiction risk, the agent should caveat its answer. The system's credibility depends on distinguishing grounded knowledge from uncertain synthesis.

---

## 10. Where This Fits in Rev 7.5

The current loop:

```
Check in → Source → Pages + Cards → Work → Proof + Write-back
```

Curation adds a parallel loop:

```
Observe → Score → Rank → Annotate → Downrank / Tombstone
```

The whole system:

```
Check in creates knowledge.
Work proves or changes knowledge.
Gardening keeps knowledge retrievable, current, and grounded.
Ask uses the gardened index.
```

This extends Section 10 (Observability) and Section 6.2 (Ask) of the core architecture. It is not a new pillar — it's the maintenance process that makes Ask reliable over time.

---

## 11. Implementation Sequence

Start passive. Earn trust. Layer in automation.

### Phase 1 — Passive Scoring

Calculate and store per-Page:

- Last referenced timestamp
- Source count (linked Sources)
- Linked Card count + completion status
- Age and staleness
- Duplicate candidates (embedding similarity)
- Contradiction candidates (claim overlap with conflicting content)

No edits. No pruning. Just metadata and Events. Display in dashboard.

*Gate: Health vectors visible on all Pages. Gardener runs, logs Events, changes nothing.*

### Phase 2 — Retrieval Weighting

Use `retrieval_weight` in Ask:

```
relevance × retrieval_weight
```

Low-weight Pages are downranked, not hidden. Direct search still finds everything.

*Gate: Ask demonstrably returns better results. Low-vitality Pages stop polluting agent context.*

### Phase 3 — Code Grounding

For `code_grounded` Pages only:

- Extract claims from Page content
- Search repos, configs, deployments for evidence
- Mark claims: confirmed / unconfirmed / contradicted
- Update `implementation_evidence` and `contradiction_risk`

Annotate only. No edits.

*Gate: Code-grounded Pages carry accurate implementation evidence scores. Dashboard shows grounding status.*

### Phase 4 — Tombstoning

Pages below the low threshold leave the default RAG index. They remain in the vault, searchable via direct lookup, but no longer injected into agent context.

*Gate: Stale/contradicted Pages stop appearing in Ask results. No knowledge lost — just deprioritised.*

### Phase 5 — Suggested Patches and Merges

Generate correction diffs for contradicted Pages. Generate merge proposals for high-overlap duplicates. Surface these as proposed Events, reviewable in the dashboard or by agents.

*Gate: Gardener produces actionable suggestions. Quality of suggestions is high enough to trust.*

### Phase 6 — Narrow Auto-Fixes

Allow automatic mechanical corrections only: renamed file paths, broken links, moved URLs, updated version numbers. Logged as Events with full before/after.

*Gate: Mechanical corrections applied without error. Institutional meaning never silently changed.*

---

## 12. Open Questions

1. **How should evidence profile be assigned?** Inferred from Page type/tags? Explicitly set at check-in? Both (inferred default, explicit override)?

2. **What's the right decay rate?** A Page with no signals shouldn't plummet overnight — but it shouldn't stay at full weight forever either. Linear decay? Exponential? Step-function after N days?

3. **How do we handle Pages that are deliberately archival?** A "Foundry v1 Architecture" Page has zero currentness but high historical value. Should there be a `preserve: true` flag, or should `reference_grounded` profile handle this naturally?

4. **Should the Gardener run as a single monolithic pass or as specialised sub-tasks?** e.g. one task for code grounding, another for duplicate detection, another for staleness scoring. Easier to debug and iterate on individually.

5. **How does this interact with Memory Wiki's existing claim system?** Claims already have confidence and provenance. Should health vector components map directly to claim metadata, or is Page-level health a separate layer?
