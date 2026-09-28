# Scope: Strategy Marketplace / Social Layer and Visual Strategy Builder

Status: **design only, nothing implemented.** Both features were audited as entirely absent
(no schema, endpoints, UI or docs). This document scopes them against the codebase as it
exists after 3.10.36, reusing its existing safety conventions rather than inventing new ones.

## Constraints inherited from the codebase (non-negotiable)

- Every strategy row is scoped by `customer_id`; all reads filter on it. Sharing must be an
  explicit, additive exception, never a relaxation of that filter.
- AI/research output has no execution authority. `live_approved` defaults False and is reset
  to False by every `validate`. A copied strategy must start as an unvalidated DRAFT.
- Approval-affecting actions require `require_aal2=True`; features are gated with
  `_require_feature(...)`; notable actions are written via `_audit(...)`.
- Validation today covers the *strategy family* (TREND/MOMENTUM/...) mapped to a built-in
  Atlas implementation, **not** the literal AI-written conditions
  (`implementation_status: ATLAS_SUPPORTED_FAMILY`). This matters a lot for a marketplace
  (see Risks).

---

## 1. Marketplace / social layer

### Phase 0 - decisions needed before any code (blocking)
1. **Regulatory posture.** Publishing strategies others can copy, with any performance
   claims or fees, can constitute investment advice / copy-trading / social-trading
   activity in some jurisdictions. Needs counsel input. The safest v1 scope is
   *share-and-clone strategy specifications with validation evidence, no auto-mirroring of
   trades, no performance fees.*
2. **Who can publish.** Recommend: only strategies with status `VALIDATED` on a recent
   attempt, published by customers with a verified account.
3. **Ownership/licensing** of published specs and what the author retains.

### Phase 1 - publish and clone (no social graph yet)
Schema (new migration, after 0031):
- `strategy_listings`: `id, candidate_id, author_customer_id, title, description,
  visibility (PRIVATE|UNLISTED|PUBLIC), status (ACTIVE|WITHDRAWN|SUSPENDED), published_run_id
  (FK strategy_candidate_runs), clone_count, created_at, updated_at`.
- `strategy_reports`: `id, listing_id, reporter_customer_id, reason, status, created_at`
  (moderation queue).
- Snapshot the listing's evidence from the referenced `StrategyCandidateRun` at publish time
  (immutable). Live-recomputed stats would let an author silently swap the evidence.

Endpoints (all customer-scoped, AAL2 for writes):
- `POST /api/customer/marketplace/listings` - publish a VALIDATED candidate.
- `GET  /api/customer/marketplace/listings` - browse PUBLIC listings (paginated, filter by
  asset/timeframe/family). Returns spec + evidence snapshot, **never** author identity beyond
  a display alias, and never the author's account, equity or trade history.
- `POST /api/customer/marketplace/listings/{id}/clone` - creates a *new* `StrategyCandidate`
  owned by the caller: `status="DRAFT"`, `live_approved=False`, spec copied with
  `cloned_from_listing_id` set. The clone must go through validate on the cloner's own market
  data before it can be approved. Never copy `live_approved`, bot links, or executor links.
- `POST /api/customer/marketplace/listings/{id}/withdraw`, `.../report`.
- Admin: list/suspend reported listings (reuse `auth(x_admin_token, ...)`).

Reuse: `StrategyCandidate.spec_json`, `StrategyCandidateRun` (evidence), `_audit`.

### Phase 2 - social signals (only after Phase 1 has real usage)
- Ratings/comments (needs abuse moderation), follow-author, "validation reproduced by N
  cloners" (count clones whose own validate passed - a far more honest signal than likes).
- Leaderboards: rank on *out-of-sample, cost-adjusted* metrics from the evidence snapshot,
  with minimum trade-count and minimum age thresholds, and a multiple-testing caveat
  (many authors submitting many strategies guarantees some lucky winners).

### Explicitly out of scope until legal/risk review
Automatic trade mirroring/copy-trading, performance fees or revenue share, paid listings.

### Risks specific to this codebase
- **Evidence mismatch:** validation tests the built-in family, not the author's literal
  rules. A listing must display `validation_scope` prominently or it overstates what was
  tested. Fixing this properly (compiling `entry_conditions/exit_conditions` into an
  executable, backtestable form) is a prerequisite for a *credible* marketplace and is the
  largest hidden dependency.
- **Prompt-injection through shared specs:** cloned `spec_json`/description is untrusted
  text. It must never be fed to an LLM as instructions; render as escaped text only (the UI
  already uses `textContent`).
- **Survivorship/data-snooping:** authors can re-validate repeatedly until one attempt
  passes. `StrategyCandidateRun` now records every attempt; listings should show attempt
  count so cherry-picking is visible.
- **Privacy:** listings must not leak `customer_id`; use a per-author alias.

Effort (rough): Phase 1 is a medium build (~2 migrations, ~7 endpoints, one UI panel,
moderation tooling); Phase 2 is open-ended.

---

## 2. Visual strategy builder

Today the "builder" is a prompt box; output is now a readable validation summary, not a
visual editor.

### Foundation that already exists
`strategy_ai.py` defines a strict schema (`StrategyCondition`, indicators, entry/exit
conditions, risk caps). A visual editor should be a **projection of that schema**, not a
second format.

### Phase 1 - structured editor over the existing schema (no new engine)
- Form/blocks UI in `customer.html`: choose family, add entry/exit condition rows
  (indicator, operator, value/timeframe), risk sliders clamped to the same caps the server
  enforces. Load an AI-generated candidate into the editor, edit, save.
- New endpoint `PUT /api/customer/strategy-lab/candidates/{id}/spec`: re-validate the edited
  spec through the same Pydantic model server-side (never trust client-side clamping), set
  status back to `DRAFT`, force `live_approved=False`, and require re-validation. This is
  also where an edit-history row belongs.
- Deliberately *not* a node-graph canvas yet: a canvas over a schema the engine does not
  execute would let users draw strategies whose behaviour is never tested.

### Phase 2 - make conditions executable (the real prerequisite)
Compile `entry_conditions/exit_conditions` into a vectorised signal function over the
existing feature frame, backtest *that*, and report `implementation_status` as
`COMPILED_AND_BACKTESTED` instead of `ATLAS_SUPPORTED_FAMILY`. Only after this does a
drag-and-drop canvas make sense, since what the user draws is then what gets validated.
Requires a safe expression model (allow-listed indicators/operators, no `eval`), lookahead
guards (signals may only use data up to bar t, executed at t+1), and fuzz tests.

### Phase 3 - canvas
Node-graph UI (conditions as nodes, AND/OR as edges) generating the same JSON. Purely a
front-end concern once Phase 2 exists.

### Risks
- Any client-side editor must be treated as untrusted input; the server schema is the
  authority.
- Editing a validated strategy must invalidate its validation and approval, or a user could
  validate a safe spec and then swap in a risky one.
- Lookahead bias in a user-composable condition system is easy to introduce and hard to
  notice; Phase 2 needs explicit tests for it.

Effort (rough): Phase 1 small-to-medium; Phase 2 large (it is a mini strategy compiler);
Phase 3 medium front-end work.

---

## Recommended order
1. (done in 3.10.36) persistence of validation attempts, so evidence exists to publish.
2. Visual builder Phase 1 (cheap, improves AI creation UX, forces an edit-history model).
3. Compile conditions (Phase 2) - prerequisite for honest marketplace evidence.
4. Marketplace Phase 1, after the legal decisions in Phase 0.
