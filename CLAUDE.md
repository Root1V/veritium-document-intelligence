# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## 5. Roadmap & Backlog

**Two files, split by cost: an index you skim, and detail you pay for only when you need it.**

A single roadmap file that mixes a status overview with full reasoning forces every reader to pay the cost of the longest entry just to answer "what's left?" or "what's the state of X?". Splitting index from detail makes the cheap queries actually cheap (read only the table) and the expensive one (understand one item deeply enough to work on it) opt-in per item.

**`roadmap.md`** (repo root) — the index.
- One markdown table **per phase** (a `## F<n> — <name>` heading followed by its table). One row per item, one line of description each, no exceptions — if a row needs more than a line, the extra belongs in the detail file, not here.
- ID prefix `VRT-` (`VRT-01`, `VRT-02`, ...), reused verbatim in branch names and commit messages so an item is traceable end-to-end. Until v0.3.0 the prefix was `RM-` with the same numbers (`feat(RM-21)` = VRT-21).
- Status column stays simple: `done` / `todo`, plus the two states this project actually produces: `blocked` (waiting on another team — reference the cross-team channel ID, e.g. `VRT-AEON-001`) and `superseded` (absorbed by another item — the description points to it). Don't pre-add statuses nothing uses.
- Never grows past its tables. If you're tempted to add a paragraph here, it goes in the detail file instead.

**`docs/roadmap.md`** (or the project's existing context folder, if it has one) — the detail.
- One section per item, keyed by its ID.
- At most two fields: **Why** (1-3 sentences — the actual reason this exists, not a restatement of the description) and **Scope** (short bullets: what's included, and what's deliberately left out).
- Not a changelog and not a running log of what happened — that's what commits and PRs are for. This file explains *why an item exists and what it covers*, nothing else.

**Maintenance rules (apply every time either file is touched):**
- Never duplicate text between the two files — the index links to an ID, it doesn't restate the detail.
- When an item has been `done` and stable for a while, trim its detail section down to 2-3 lines plus a link to the commit/PR — don't preserve the full original reasoning forever.
- Before adding anything to either file, ask: *is this needed to decide or act, or is it just history?* History doesn't go in either file.
- Large architectural decisions don't live in the roadmap. They live in `docs/adr/`; the roadmap only links to them — it never becomes the second home for that reasoning.

