# LurkNotes

Notes deck at the right edge of the screen for Ubuntu 24.04 / GNOME 46.
Spec: [.scratch/edge-notes/spec.md](.scratch/edge-notes/spec.md).
Plan: [.scratch/edge-notes/plan.md](.scratch/edge-notes/plan.md).

## Run

```sh
./lurknotes            # show the deck; the fan expands immediately
./lurknotes new        # create a note at the top and open the editor
./lurknotes all        # open (or raise) the All Notes window
./lurknotes --autostart # quiet session start: only the strip, no focus
```

The process stays in the foreground; `Ctrl+C` in the terminal stops it.
`lurknotes` is a single instance: a second invocation hands its command to
the running process and exits with that process' exit code, so `new` and `all`
work from a terminal, a hotkey or a script without starting a second deck.

`new` while an untouched note is already open focuses that note instead of
stacking another empty one. Hover never takes keyboard focus; after `new` or
`all` the app asks for activation and, if the window did not get the keyboard
within 150 ms, the panel shows **Click to type**. The first click anywhere on
the panel takes input and focuses the editor.

`./lurknotes --help` prints usage. Unknown arguments and options exit with
status 2.

## Hotkeys

GNOME 46 has no global-shortcut portal, so bind the commands once by hand:

1. Open **Settings → Keyboard → Keyboard Shortcuts → Custom Shortcuts**.
2. Add `Ctrl+Alt+N` running the absolute path to `lurknotes new`.
3. Add `Ctrl+Alt+A` running the absolute path to `lurknotes all`.

The first visible deck shows the same instructions once and records that in
`$XDG_DATA_HOME/lurknotes/onboarded`; it is never shown again.

## Autostart

Install the per-user session entry once:

```sh
./lurknotes --install-autostart
```

It writes `$XDG_CONFIG_HOME/autostart/dev.lurknotes.LurkNotes.desktop`
(usually `~/.config/autostart/`) with an absolute `Exec=... --autostart`.
After the next login only the strip is mapped: the fan stays closed, keyboard
focus is not taken and no note is created. Run the same command again to
refresh the entry; delete the file to disable autostart.

## Data

Notes live in `$XDG_DATA_HOME/lurknotes/notes.json`
(usually `~/.local/share/lurknotes/notes.json`) with `notes.bak.json` beside
it. Nothing is written outside `$XDG_DATA_HOME` and `~/.config`.

## Test

```sh
/home/dev/projects/ubuntu/.venv/bin/python -m pytest
/home/dev/projects/ubuntu/.venv/bin/python scripts/smoke.py
/home/dev/projects/ubuntu/.venv/bin/python scripts/smoke_note.py
/home/dev/projects/ubuntu/.venv/bin/python scripts/smoke_hover.py
/home/dev/projects/ubuntu/.venv/bin/python scripts/smoke_delete.py
/home/dev/projects/ubuntu/.venv/bin/python scripts/smoke_all_notes.py
/home/dev/projects/ubuntu/.venv/bin/python scripts/smoke_storage.py
/home/dev/projects/ubuntu/.venv/bin/python scripts/smoke_drag.py
/home/dev/projects/ubuntu/.venv/bin/python scripts/smoke_integration.py
/home/dev/projects/ubuntu/.venv/bin/python scripts/acceptance.py
```

Each smoke starts its own instance against temporary XDG directories, uses a
unique application id, checks the real X11 windows, then stops the process it
started. `acceptance.py` covers the remaining MVP criteria and measurements
(cold/warm start, idle RSS/CPU, real 10 s undo, fullscreen stacking, no-network
sockets, `kill -9` stress); its report is
[.scratch/lurknotes-mvp/acceptance.md](.scratch/lurknotes-mvp/acceptance.md).
