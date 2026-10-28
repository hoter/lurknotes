# Research: публикация и ревью в Snap Store

Type: research
Status: resolved
Blocked by:

Research branch: `research/store-review` (findings: `.scratch/snap-store/research/05-store-review.md`)

## Question

Какой полный путь публикации strict GUI-снапа в Snap Store и что проверяет
ревью?

Выяснить по первоисточникам (snapcraft.io docs, store review policy, snapd):

- регистрация аккаунта, имени `lurknotes`, Publisher Agreement;
- обязательные поля листинга: license, contact, homepage, категория,
  скриншоты, иконка, description;
- какие интерфейсы/особенности (`x11`, `autostart`, `desktop`) триггерят
  ручное ревью; чего избегать (classic, system-files);
- каналы, ревизии, `snapcraft upload`/`release`, откат, публикация в `stable`;
- требования к сборке (`snapcraft` + LXD/Multipass), можно ли собрать без
  root/виртуалки;
- что видит пользователь при `snap install` (permissions, autostart).

Ответ — пошаговый чек-лист публикации с командами и ссылками.

## Answer

Resolved by research on branch `research/store-review`; full report:
<https://github.com/hoter/lurknotes/blob/research/store-review/.scratch/snap-store/research/05-store-review.md>

- **Name registration is itself a manual review** (since March 2024): every new
  name is queued for the Store team, target 2 business days but sometimes much
  longer. Do it before building/uploading. The current agreement is the
  **Developer Programme Agreement** (Store Terms + Privacy Notice), not
  "Publisher Agreement".
- Listing fields: title (≤40), summary (≤78 in snapcraft.yaml), Markdown
  description, category, website, contact, license, icon, screenshots,
  banner/video. **There is no keywords field**; the category slug is
  **`utilities`**, not `Utility`.
- `x11`, `desktop` and `autostart` alone do **not** trigger manual review
  (x11/desktop auto-connect on classic Ubuntu). Hidden triggers for LurkNotes:
  a named `dbus` slot (likely required), `desktop-file-ids`,
  `personal-files`/`system-files`, `home` with `read: all`, and `classic`.
- Autostart is only a filename declaration; the app must write
  `$SNAP_USER_DATA/.config/autostart/...` on first launch (moving the write out
  of `--install-autostart`).
- Build: LXD is the default provider; non-root works after a one-time `lxd`
  group setup (root-equivalent), or use Multipass/`snapcraft remote-build`;
  `--destructive-mode` for core24 needs root. Use `base: core24` +
  `platforms: amd64:`.
- Release: `snapcraft upload --release=edge` → test → `snapcraft release <rev>
  stable` (or `promote`). Revisions are immutable; rollback is re-releasing an
  older revision (`snap revert` is client-side).
- Strict install shows no permission prompt; the desktop entry/icon appear in
  the app grid; autostart is silent and has no generic `snap` toggle; updates
  refresh up to 4×/day.
- Pre-flight: `snap-review` from Canonical's `review-tools` snap runs the Store
  checks; `snapcraft lint` helps too.
- Uncertainties: no public upload-review SLA; Gtk.Application without a dbus
  slot untested; listing limits can drift from the store JS source.
