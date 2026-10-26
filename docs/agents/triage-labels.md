# Triage Labels

Five canonical triage roles, mapped to the strings used in this repo.

| Role | String in our tracker | Meaning |
|---|---|---|
| needs-triage | needs-triage | Maintainer needs to evaluate this issue |
| needs-info | needs-info | Waiting on reporter for more information |
| ready-for-agent | ready-for-agent | Fully specified, ready for an AFK agent |
| ready-for-human | ready-for-human | Requires human implementation |
| wontfix | wontfix | Will not be actioned |

Triage state is written on a `Triage:` line near the top of the issue file. `Status:` is
reserved for wayfinding (`open` / `claimed` / `resolved` / `superseded`), so the two
vocabularies never collide.
