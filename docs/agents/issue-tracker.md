# Issue tracker: Local Markdown

Issues, specs and plans live as markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- Spec: `.scratch/<feature-slug>/spec.md`
- Plan: `.scratch/<feature-slug>/plan.md` (optional, after the spec)
- Issues: one file per ticket, `.scratch/<feature-slug>/issues/NN-<slug>.md`, numbered from `01`
- Triage state: a `Triage:` line near the top (`needs-triage`, `needs-info`,
  `ready-for-agent`, `ready-for-human`, `wontfix`)
- Wayfinding state: a separate `Status:` line (`open`, `claimed`, `resolved`, `superseded`)
- Comments and history: appended under `## Comments`

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/issues/`, creating directories if needed.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user normally passes the path or the issue number.

## Wayfinding operations

Used by `/wayfinder`. The **map** is one file with one **child** file per ticket.

- **Map**: `.scratch/<effort>/map.md` — Destination / Notes / Decisions so far /
  Not yet specified / Out of scope.
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md`, question in the body,
  `Type:` line (`research` / `prototype` / `grilling` / `task`), `Status:` line.
- **Blocking**: `Blocked by: NN, NN`; a ticket is unblocked when every listed file is `resolved`.
- **Frontier**: open, unblocked, unclaimed tickets; first number wins.
- **Claim**: set `Status: claimed` before any work.
- **Resolve**: append the answer under `## Answer`, set `Status: resolved`, append a gist
  and link to the map's Decisions so far.
