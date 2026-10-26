# LurkNotes MVP — acceptance report

Date: 2026-10-27
Branch: `ticket/10-acceptance` (merged with `feature/lurknotes-mvp`)
Environment: Ubuntu 24.04.5, GNOME Shell 46.0, Mutter 46, XWayland `DISPLAY=:0`,
PyGObject 3.48.2, GTK 4.14.5, Python 3.12.3.
Session: X11 client under XWayland, `GDK_BACKEND=x11`.

This ticket is verification and honest documentation. No product code was
changed. The measurements below are from the recorded run of
`scripts/acceptance.py` on this machine; the feature smokes are from the same
integration tip.

## How to reproduce

```sh
cd /path/to/lurknotes
/home/dev/projects/ubuntu/.venv/bin/python -m pytest -q
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

`scripts/acceptance.py` is the ticket-10 harness. It creates a temporary
`XDG_DATA_HOME`/`XDG_CONFIG_HOME`, uses a unique application id per probe,
moves the pointer away before rest-state measurements, never installs a real
GNOME keybinding, never writes `~/.local/share/lurknotes` or
`~/.config/autostart`, and stops every process/window it starts. `--keep`
leaves the temporary tree for inspection.

## Suite result

```
185 passed in 0.38s
```

All eight feature smokes exited 0 on the final rerun. The first rerun of
`smoke_all_notes.py` hit a test-only dump race (`0x0` GTK size read before
allocation); the smoke now waits for the documented 720x560 size. That is the
only change made to an existing smoke, and it does not touch product code. Their key assertions are quoted with the
corresponding criterion below.

## Twelve acceptance criteria

| # | Criterion (spec §12) | Verdict | Evidence |
|---|---|---|---|
| 1 | Strip visible at the right edge after login; absent from dock and Alt+Tab | **PASS** (EWMH) | `--autostart`: strip `20x1856+2860+64` physical (10x928 logical, right edge of workarea `132,64 2748x1856`, scale 2); `_NET_WM_STATE` ⊇ `ABOVE`, `SKIP_TASKBAR`, `SKIP_PAGER`, `STICKY`; `_NET_WM_DESKTOP=4294967295`; `WM_HINTS input=False`; `_NET_WM_USER_TIME=0`; no focus, no fan, no `notes.json`. Shell-side dock/Alt+Tab filtering cannot be enumerated by a client; GNOME 46 filters `skip_taskbar` (PLATFORM §2/§9). |
| 2 | Hover expands, leave collapses, `Esc` after click closes | **PASS** | Unit clock: expand exactly at 120 ms, collapse exactly at 400 ms. Live `smoke_hover`: fan mapped in **138 ms**, pointer leave collapsed in **412 ms**, `Esc` closed the open note to the fan, second `Esc` collapsed the focused fan. |
| 3 | Peek appears ~150 ms and does not flicker while the pointer crosses tabs | **PASS** | Unit clock: no peek at 149 ms, peek at 150 ms. Live `smoke_hover`: peek visible **205 ms** after the pointer move (150 ms timer + snapshot/dump latency), 3 body lines inside the fan, no extra window. Crossing tabs removes the old peek at once and shows only the new one; leaving the tab hides it and keeps the fan. |
| 4 | Click opens; typed input reaches the editor; saves after ~400 ms | **PASS** | Real XTest typing in `acceptance.py`: 3 runs, text reached the editor and `notes.json` **382 ms** median (381/384/382). `smoke_note`: real tab click, cursor at end, debounce, `SIGKILL`, restart shows the saved text; backup holds the previous file. |
| 5 | `Ctrl+Alt+N` from another application creates a note on cold and warm start | **PASS** (command path; binding is manual) | Cold `lurknotes new` from `/tmp` opened a note. Warm `lurknotes new` from `/tmp` delivered in **158 ms** median (148–176) and the note was visible in **191 ms** median (189–199); only the primary process remained. `not` installed: the GNOME shortcut is the documented manual step below. |
| 6 | Delete + undo works for 10 s; no undo after restart | **PASS** | `acceptance.py` with the production 10 000 ms timer: delete reached UI+disk in 182 ms; undo at **9.5 s** restored the note at its index; expiry at **9 945 ms**; `Ctrl+Z` after expiry did nothing; after restart no toast/undo and `Ctrl+Z` did nothing. |
| 7 | Drag reorders; same order in deck/rail/All Notes; survives restart | **PASS** | `smoke_drag`: 2 px press opened the note; crossing 5 px raised the tab (`#3d3d4c`) and set `grabbing`; release at the third row reordered and wrote immediately; release outside cancelled byte-identically; restart made fan, rail and All Notes agree. |
| 8 | Search finds a substring anywhere in the text | **PASS** | `smoke_all_notes`: search narrowed to matches anywhere (including a body substring), match line bolded, clearing restored every note. |
| 9 | `Ctrl+Alt+A` opens All Notes; row click opens the panel | **PASS** (command path; binding is manual) | `smoke_integration`: warm `all` in 155 ms and cold `all` opened All Notes; second `all` raised the same window. `smoke_all_notes`: row click opened the note and left All Notes mapped. |
| 10 | Corrupt JSON recovers from backup | **PASS** | `smoke_storage`: corrupt main recovered from `notes.bak.json`, quarantined as `notes.corrupt-<ts>.json`, persisted; restart clean; double corruption shows Continue and writes nothing; after Continue the next save preserves the original; future version stays read-only; unwritable deck works in memory and retries. |
| 11 | A fullscreen application covers the deck (expected) | **FAIL — accepted deviation** | Focused real fullscreen window (`_NET_WM_STATE_FULLSCREEN`, `_NET_WM_STATE_FOCUSED`) is **below** the strip: `_NET_CLIENT_LIST_STACKING` bottom→top = `0xc00004` (fullscreen), `0xe00004` (strip). Root pixels: strip column `#24242c`, 200 px left `#00aa00` (fullscreen probe surface). The `ABOVE` hint wins over `FULLSCREEN` in Mutter 46. See “Accepted deviations”. |
| 12 | No light flashes or white areas when the panel opens | **PASS** | `smoke_hover` captured the first fan frame while mapping: no near-white pixel. `acceptance.py`: strip `#24242c`, 0/2320 near-white; first fan frame `#1c1c22`; 33 map-time captures, 0 near-white; brightest sampled pixel `#e9e9f1` (normal primary text); fan visible 142 ms after the bare command. |

## Measurements

### Start-up

| Measurement | Samples | Median | Min | Max | Target | Verdict |
|---|---|---|---|---|---|---|
| Cold start to first mapped strip (`--autostart`) | 172, 176, 164, 154, 177, 171, 180 ms | **172 ms** | 154 ms | 180 ms | ≤ 1500 ms | PASS |
| Warm `lurknotes new` delivery (second process, cwd `/tmp`) | 176, 158, 158, 148, 150 ms | **158 ms** | 148 ms | 176 ms | ≤ 300 ms | PASS |
| Warm `lurknotes new` visible in the deck (dump) | 196, 199, 189, 189, 191 ms | **191 ms** | 189 ms | 199 ms | ≤ 300 ms | PASS |
| Autosave after real typing (from last key to `notes.json`) | 381, 384, 382 ms | **382 ms** | 381 ms | 384 ms | ~400 ms debounce | PASS |
| Delete to UI + `notes.json` | one run | 182 ms | — | — | immediate | PASS |

The warm visible number includes the app's 150 ms test-dump scheduling and
polling; the actual `present()`/map happens earlier. The command delivery time
is the process wall time from spawn to synchronous hand-off return.

### Idle memory and CPU (strip-only `--autostart`)

| Run | RSS |
|---|---|
| 1 | 134.5 MB |
| 2 | 134.3 MB |
| 3 | 134.6 MB |
| 4 | 134.3 MB |
| 5 | 134.4 MB |

Median **134.4 MB**, min 134.3, max 134.6. Target in spec §11 is ≤ 120 MB.
Idle CPU measured over 3.0 s per run: **0.00 %** (no busy polling observed).

This is an accepted deviation below, not hidden.

### `kill -9` during writes

Writer: the real `lurkn.store.Store.save` path, 3 000 notes per deck, each
~3 KB of text (≈ 9 MB text / ≈ 12 MB serialized JSON), alternating deck A/B.
The parent waits for the first save to complete (`DONE 0`), then kills during
the second large save after a random 1–40 ms.

```
15/15 runs: notes.json parsed as a coherent prior/new deck
14/15 runs: notes.bak.json present and valid (one kill hit before the first
            backup copy — allowed by spec §5.2's best effort)
 3/15 runs: a temp file was present after the kill (mid-write evidence)
main generations: A=13, B=2
```

Structural guarantee (spec §5.2, `src/lurkn/store.py`):

1. serialize to `notes.json.tmp`, `flush`, `fsync(tmp)`;
2. copy the previous `notes.json` to `notes.bak.json.tmp`, rename it to
   `notes.bak.json` (atomic; a short copy cannot truncate the old backup);
3. `os.replace(tmp, notes.json)` (atomic);
4. `fsync` the directory.

`SIGKILL` can therefore leave the old or the new `notes.json`, never a
half-written one. A leftover `.tmp` is ignored and truncated by the next save;
a missing backup is possible only if the kill lands before step 2.

### Network

Strip-only instance after 1.5 s idle:

```
6 sockets total, 6 AF_UNIX (D-Bus), 0 AF_INET/AF_INET6 TCP/UDP
lsof -nP -p <pid> -a -i: <empty>
```

Socket inodes were matched against `/proc/net/tcp`, `tcp6`, `udp`, `udp6`;
the six unix sockets matched `/proc/net/unix`. D-Bus over `AF_UNIX` is expected
and is not a network connection. No telemetry or HTTP client is linked.

### Fullscreen probe (criterion 11)

Method: a real GTK fullscreen window (`#00aa00` surface) was focused using the
PLATFORM §4 recipe (`WM_HINTS input=True`, delete `_NET_WM_USER_TIME`,
`present()`). `_NET_WM_STATE` was `FULLSCREEN, FOCUSED`; geometry `2880x1920`.
The deck ran in `--autostart` rest state with the pointer parked away.

```
_NET_CLIENT_LIST_STACKING bottom→top: 0xc00004 (fullscreen), 0xe00004 (strip)
root pixel at strip column (2870,464): (36,36,44) = #24242c
root pixel 200 px left (2470,464):     (0,170,0)  = #00aa00
```

Observed behaviour is the opposite of spec §12.11/§13: the 10 px strip remains
above the fullscreen window. A GNOME Shell extension would be needed to drop
`ABOVE` while a fullscreen window exists; tracking fullscreen clients and
toggling the hint from the client is race-prone and outside MVP.

## Accepted deviations and known defects

### 1. Criterion 11: fullscreen does not cover the strip (new, platform)

- **Observed:** focused fullscreen window is below the `ABOVE` strip; the strip
  stays visible at the right edge.
- **Why:** Mutter 46 layers `_NET_WM_STATE_ABOVE` above `FULLSCREEN`; a client
  cannot opt out per-window without monitoring all fullscreen windows.
- **Decision:** accept for v1 and record the spec contradiction. The impact is
  a 10 px strip over fullscreen video/games; the deck can be collapsed/quit.
  Revisit only together with a GNOME Shell extension (outside MVP). Spec §13
  should be corrected after closure.

### 2. Collapse hands keyboard focus away from the user's application

Spec §13 / PLATFORM §4: hiding the focused panel makes Mutter focus the
application's remaining strip window. In one probe here the root
`_NET_ACTIVE_WINDOW` became `0x0` instead of the strip, but the important part
is unchanged: the previously focused application can lose the keystrokes typed
at that moment. Accepted for v1; the alternative (keep the panel mapped with
transparency/input shape) is out of scope.

### 3. Idle memory is above target

134.4 MB median vs the 120 MB target in spec §11. The deck is a strip-only
`--autostart` instance with 30 notes; GTK/PyGObject/AT-SPI baseline dominates.
Decision: ship v1 with the measured number and treat it as the explicit
threshold for a future Rust/GTK-rewrite decision, as spec §11 asks. No small
safe trim was identified (All Notes is already lazy; CSS is one provider).

### 4. Peek is a fixed in-fan pane, not a per-tab expansion

The peek is one always-allocated read-only pane at the bottom of the fan, not
an in-place expansion of the hovered tab. This keeps tab heights, positions,
the header and the wheel target stable while the pointer moves (spec §6.2/§7.1
intent), and is why crossing tabs cannot flicker. Accepted visual deviation.

### 5. Releasing a drag over the strip cancels the reorder

The release-inside test uses the panel window, not the 10 px strip (a separate
X11 window). Releasing a dragged tab over the strip therefore counts as
“outside the deck” and cancels, while releasing in the fan/panel reorders.
Accepted; the strip is not a drop target.

### 6. All Notes can overlap the edge panel

All Notes is 720x560 logical, centred in the workarea (`x=393..1113` on this
1440-wide screen). The open panel occupies `x=1050..1430`, so the windows
overlap by ~63 logical px when both are open. All Notes is a normal window and
is raised above the panel; spec does not require them to be disjoint. Accepted
for v1.

### 7. Manual GNOME integration steps

The application does not register global shortcuts (no `GlobalShortcuts`
portal on GNOME 46). The user must add, once, in **Settings → Keyboard →
Keyboard Shortcuts → Custom Shortcuts**:

| Combination | Command |
|---|---|
| `Ctrl+Alt+N` | absolute path to `lurknotes new` |
| `Ctrl+Alt+A` | absolute path to `lurknotes all` |

This was **not** installed on the user's real session; only the command path
was verified end-to-end from `/tmp` (cold and warm). Autostart likewise needs
one explicit `lurknotes --install-autostart`; it writes an absolute
`Exec=.../lurknotes --autostart` desktop entry. That was verified in a temp
`XDG_CONFIG_HOME` (`desktop-file-validate` rc 0). A real logout/login cycle was
not performed in this pass.

### 8. Tab drag cancel on strip release (same as 5)

Recorded separately because the ticket names it: the spec says “release outside
the deck cancels”; the strip is visually part of the deck but is a separate
window, so a strip release cancels. No data is lost.

### 9. Other known limitations (spec §13, unchanged)

- XWayland-only; fractional scaling may blur text.
- Window starts below the GNOME top bar (`y=32` logical), not at the physical
  screen edge.
- Only GNOME 46 / Ubuntu 24.04 was tested.
- `_NET_WM_STATE_DEMANDS_ATTENTION` may appear on a no-focus map; with
  `SKIP_TASKBAR` there is no dock icon to flash, so it is invisible.
- `kill -9` may leave `notes.json.tmp` / `notes.bak.json.tmp`; harmless and
  overwritten by the next save.

## Files and hooks

- `scripts/acceptance.py` — deterministic ticket-10 harness described above.
- `scripts/smoke_all_notes.py` — test-only robustness fix: wait for the
  720x560 allocation in the dump predicate instead of reading a 0x0 first
  frame.
- Test-only environment hooks used by the smokes/acceptance (`app.py` header):
  `LURKNOTES_TEST_DUMP`, `LURKNOTES_TEST_TYPE`, `LURKNOTES_TEST_CONTROL`,
  `LURKNOTES_TEST_PIN_DECK`, `LURKNOTES_TEST_REFUSE_FOCUS`,
  `LURKNOTES_TEST_NO_HOVER`, `LURKNOTES_TEST_UNDO_MS`,
  `LURKNOTES_APP_ID`. Production does not register them unless set.
- No product code was changed for this ticket.

## Verdict

11 of 12 criteria pass. Criterion 11 is not met as written; the observed
platform behaviour (strip above focused fullscreen) is documented above as an
accepted deviation with evidence. Memory is measured and above the 120 MB
target, with a Rust-threshold decision. The ticket is left `Status: open` for
the separate final-closure step.
