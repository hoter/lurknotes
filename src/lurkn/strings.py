"""User-visible strings. English UI for v1."""

STRIP_TITLE = "LurkNotes — strip"
FAN_TITLE = "LurkNotes — fan"
NOTE_TITLE = "LurkNotes — note"
PEEK_TITLE = "LurkNotes — peek"

NOTES_HEADER = "NOTES"
NEW_NOTE = "New note (+)"
NEW_NOTE_LABEL = "+"
FAN_HINT = "hover a note to peek · drag to reorder"
COLLAPSE_DECK = "Collapse deck"
NO_NOTES = "No notes yet"
UNTITLED = "Untitled"
UNDO_TOAST = "Deleted. 10s to undo"
UNDO = "Undo"
UNDO_HINT = "Undo delete (Ctrl+Z)"
CLOSE = "×"
CLOSE_NOTE = "Close note (Esc)"
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

# All Notes (spec §4.3, §6.4).
ALL_NOTES_TITLE = "All Notes"
ALL_NOTES_SEARCH = "Search all notes"
ALL_NOTES_MENU = "Menu"
ALL_NOTES_EMPTY = "No notes yet"
ALL_NOTES_NO_MATCH = "No notes match your search"
QUIT = "Quit LurkNotes"

USAGE = "usage: lurknotes [new|all]"
UNKNOWN_COMMAND = "lurknotes: unknown command {command!r}; " + USAGE
ERROR = "lurknotes: {message}"
NO_DISPLAY = "cannot open X display (is XWayland running?)"
