# Branching & Release Model (Avenue MDP)

Trunk-based model on the release remote **`deploy`** (`Hieu123k/mdp-deploy-v0.0`).
This file lives on `develop`, so `main` stays byte-identical to the `v0.1.5` tag.

## Branches

| Branch | Purpose | Rules |
|--------|---------|-------|
| `main` | **Stable trunk** = the latest released code. | Every release is tagged `vX.Y.Z`. Enter ONLY via a reviewed merge (or an admin-approved trunk reset). No direct commits, no force-push, tags are immutable. `main` == the current release tag, byte-identical. |
| `develop` | **Integration / development branch.** | Feature and epic branches branch off `develop` and merge back into `develop`. When a release is cut, `develop` is merged into `main` and tagged. |
| `feat/<area>-<desc>` | A scoped feature. | Off `develop`. Built + tested DEV-only on `mdp2`; a handoff report must PASS (full pytest 0-failed + `next build` + acceptance) before merge to `develop`. |
| `fix/<area>-<desc>` | A scoped bug fix. | Same flow as `feat/*`. |
| `epic/<name>` | A large, multi-step change. | Off `develop`; integrates incrementally. Examples: `epic/ingestion-<tool>` (a new ingestion engine to replace ora2pg, shipped behind a **coexist feature-flag** so the old path keeps working) targeting **`v0.2.0`**. |
| `feat/reporting-grafana` | Reporting as **dashboards-as-code** committed in this repo, coexisting with the Grafana already running on `.63`. | Targets **`v0.3.0`**. |

## Versioning & rollback

- **SemVer** `vX.Y.Z`. Each release pushes an annotated tag `vX.Y.Z` on the release commit and a
  rollback anchor `pre-vX.Y.Z` pointing at the previous trunk commit.
- Rollback = `git checkout pre-vX.Y.Z` (or reset trunk to it with admin approval).
- **Schema changes**: each schema change is exactly **one alembic migration**; the repo keeps a
  **single alembic head** at all times.
- **Release remote** is **`deploy`** only. `origin` (`MDP-ver1.1`) is NOT used for releases.

## Trunk history note (v0.1.5)

`main` was reset to **`v0.1.5`** (`3b3a33f`) as the clean trunk. The previous `main`
(`68dcf87`) was a **parallel line** whose features are **no longer on the trunk** and are currently
**not in use**:

- MQTT consumer (UNS broker -> Type A inbound, default OFF)
- reference-data API + model + service
- `EditableSelect` UI component
- ora2pg-dashboard enhancements

That old `main` is preserved permanently in the tag **`archive/baseline-main-68dcf87`** (rollback
anchor `pre-main-v0.1.5` -> `68dcf87`). **Re-integration is OPTIONAL** - pull any of those features
back **only if genuinely needed**, as a `feat/*` branch off `develop` with full QA. There is no
mandatory re-integration.

## `only-api`

The `only-api` variant is archived as **`archive/only-api-ba18168`**. The plan is to fold it into
`main` as a **build-flag** (API-only build) in a separate task - the FE is not merged into it.

## Immutable refs (do not modify/delete)

Release tags `v0.1.0`-`v0.1.5`, all `pre-*`, all `archive/*`, the `release/streaming-ui-v0.1.x`
branches, `only-api`, and `old` are immutable history. Only `main` (via reviewed merge / approved
reset) and `develop` move.
