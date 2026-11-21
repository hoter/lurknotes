"""User-visible strings. English UI for v1."""

STRIP_TITLE = "LurkNotes — strip"
FAN_TITLE = "LurkNotes — fan"
NOTE_TITLE = "LurkNotes — note"

NOTES_HEADER = "Lurk Notes"
NEW_NOTE = "New note (+)"
NEW_NOTE_LABEL = "+"
FAN_HINT = "hover a note to peek · drag to reorder"
FAN_HINT_FILTERED = "hover a note to peek · reordering is off while filtering"
FAN_SEARCH = "Search notes"
NO_MATCH = "No notes match your search"
EMPTY_NEW_NOTE = "+ New note"
PEEK_HINT = "Hover a note to peek"
PEEK_EMPTY = "No body text"
COLLAPSE_DECK = "Collapse deck"
# The panel collapses towards the right screen edge, which is where the strip
# lives, so the chevron points that way instead of reusing the close glyph.
COLLAPSE = "»"
NO_NOTES = "No notes yet"
UNTITLED = "Untitled"
UNDO_TOAST = "Deleted. 10s to undo"
UNDO = "Undo"
UNDO_HINT = "Undo delete (Ctrl+Z)"
CLOSE = "×"
CLOSE_NOTE = "Back to notes (Esc)"
DELETE_NOTE = "Delete note (Ctrl+Backspace)"
CLICK_TO_TYPE = "Click to type"
ONBOARDING_TEXT = (
    "Bind a hotkey in GNOME Settings → Keyboard → Custom Shortcuts:\n"
    "Ctrl+Alt+N runs lurknotes new"
)
ONBOARDING_DISMISS = "Got it"
SAVE_FAILED = "Save failed"
SAVE_FAILED_RETRYING = (
    "Save failed — retrying. Your changes are kept in memory."
)

# Storage recovery (spec §5.3, §10). Placeholders use str.format.
STORAGE_RECOVERED = (
    "The notes file was damaged. {count} note(s) were recovered from the "
    "backup; the damaged file was kept as {corrupt}."
)
STORAGE_CORRUPT = (
    "The notes file and its backup could not be read. Nothing will overwrite "
    "the damaged file until you choose Continue."
)
STORAGE_UNSUPPORTED = (
    "This notes file was written by a newer LurkNotes. It is open read-only; "
    "nothing will be saved."
)
STORAGE_RECOVERY_NOT_SAVED = (
    "Recovered notes from the backup, but saving them failed. Retrying; your "
    "changes are kept in memory."
)
STORAGE_READ_FAILED = "Could not read the notes file: {detail}"

STATUS_CONTINUE = "Continue"
STATUS_DISMISS = "Dismiss status"
QUIT = "Quit LurkNotes"

SYNC_SIGNED_IN = "lurknotes: sync enabled for {email} on {server}"
SYNC_SIGNED_OUT = "lurknotes: sync disabled; the device token was removed"
SYNC_STATUS_ON = "lurknotes: sync on for {email} ({server}); last sync {last}"
SYNC_STATUS_OFF = "lurknotes: sync is off"
SYNC_STATUS_PAUSED = "lurknotes: sync paused for {email}"
SYNC_FAILED = "lurknotes: sync failed: {message}"

# In-deck sync row and status dot (sync spec §6.4).
SYNC_ROW_OFF = "Sync off · local only"
SYNC_ROW_PAUSED = "Sync paused"
SYNC_ROW_ON = "Synced"
SYNC_ROW_ATTENTION = "Signed out · notes not syncing"
SYNC_ROW_HINT = "Turn on to sync with LurkNotes"
SYNC_SET_UP = "Set up"
SYNC_SIGN_IN = "Sign in"
SYNC_SIGN_OUT = "Sign out"
SYNC_PAGE_TITLE = "Sync"
SYNC_PAGE_SUBTITLE = "Keep your deck on every machine."
SYNC_PAGE_ACCOUNT = "Account"
SYNC_PAGE_STATUS = "Status"
SYNC_PAGE_LAST = "Last sync: {last}"
SYNC_PAGE_NEVER = "never"
SYNC_PAGE_SERVER = "Server"
SYNC_PAGE_EMAIL = "Email"
SYNC_PAGE_PASSWORD = "Password"
SYNC_PAGE_BAD_LOGIN = "Could not sign in. Check the email, password and server."
SYNC_STATUS_OFF_LABEL = "Off — the deck stays local"
SYNC_STATUS_ON_LABEL = "On"
SYNC_STATUS_PAUSED_LABEL = "Paused"
SYNC_USAGE = (
    "usage: lurknotes sync login --server URL --email EMAIL --password-stdin | "
    "lurknotes sync logout | lurknotes sync status"
)

VERSION = "lurknotes {version}"
USAGE = (
    "usage: lurknotes [new] | lurknotes --autostart | "
    "lurknotes --install-autostart | lurknotes --help | "
    "lurknotes --version\n"
    "       lurknotes sync login --server URL --email EMAIL --password-stdin\n"
    "       lurknotes sync logout | lurknotes sync status"
)
CLI_UNKNOWN_COMMAND = "lurknotes: unknown command {argument!r}; " + USAGE
CLI_UNKNOWN_OPTION = "lurknotes: unknown option {argument!r}; " + USAGE
CLI_DUPLICATE = "lurknotes: {argument} given twice; " + USAGE
CLI_ONE_COMMAND = (
    "lurknotes: expected one command, got {first!r} and {second!r}; " + USAGE
)
CLI_INSTALL_ALONE = (
    "lurknotes: --install-autostart takes no other arguments; " + USAGE
)
CLI_AUTOSTART_ALONE = (
    "lurknotes: --autostart takes no command; it only shows the strip; " + USAGE
)
AUTOSTART_INSTALLED = "lurknotes: autostart installed at {path}"
AUTOSTART_INSTALL_FAILED = "lurknotes: cannot install autostart: {message}"
ERROR = "lurknotes: {message}"
NO_DISPLAY = "cannot open X display (is XWayland running?)"
