# LurkNotes

Notes deck at the right edge of the screen for Ubuntu 24.04 / GNOME 46.
Spec: [.scratch/edge-notes/spec.md](.scratch/edge-notes/spec.md).
Plan: [.scratch/edge-notes/plan.md](.scratch/edge-notes/plan.md).

## Run

`./lurknotes` starts the strip on the XWayland display. The process stays in
the foreground; `Ctrl+C` in the terminal stops it. `new` and `all` are accepted
as commands but are wired to the deck in a later milestone.

## Test

```sh
/home/dev/projects/ubuntu/.venv/bin/python -m pytest
/home/dev/projects/ubuntu/.venv/bin/python scripts/smoke.py
```

The smoke script starts its own instance against a temporary
`XDG_DATA_HOME`, checks the X11 geometry and EWMH hints, then stops it.
