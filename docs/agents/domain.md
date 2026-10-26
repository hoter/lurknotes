# Domain Docs

How the engineering skills should consume this repo's domain documentation.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root. No `GLOSSARY-MAP.md` exists; this is a single-context repo.
- **`docs/adr/`**: read ADRs that touch the area you're about to work in.

If either doesn't exist yet, proceed silently. Don't flag its absence and don't suggest
creating it upfront: `/domain-modeling` creates them lazily when terms or decisions
actually get resolved.

## File structure

Single context:

```
/
├── GLOSSARY.md
├── docs/adr/
└── src/
```

## Use the glossary's vocabulary

When output names a domain concept (issue title, refactor proposal, test name), use the
term as defined in `GLOSSARY.md`. Don't drift to synonyms it lists under _Avoid_.

If the concept isn't in the glossary yet, that's a signal: either you're inventing
language the project doesn't use (reconsider) or there's a real gap (note it for
`/domain-modeling`).

## Flag ADR conflicts

If output contradicts an existing ADR, surface it explicitly rather than overriding it
silently:

> _Contradicts ADR-0007 (…), but worth reopening because…_
