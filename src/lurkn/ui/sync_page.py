"""The Sync page: what the deck's "Set up" opens (sync spec §6.4).

It lives in the same window frame as a note, so Esc and the rail's back arrow
behave the way they already do. The page only collects input and reports
state; signing in and out is the app's job, which keeps the network work off
the widget.

The password field is cleared as soon as a sign-in is attempted, successful or
not: it is the one value in this UI that must not linger in a widget that
stays mapped for hours.
"""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Gtk

from .. import strings


class SyncPage(Gtk.Box):
    """Toggle, account form and status, in the deck's width."""

    def __init__(
        self,
        *,
        on_back: Callable[[], None],
        on_toggle: Callable[[bool], None],
        on_sign_in: Callable[[str, str, str], bool],
        on_sign_out: Callable[[], None],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._on_toggle = on_toggle
        self._on_sign_in = on_sign_in
        self._on_sign_out = on_sign_out
        self.add_css_class("sync-page")

        back = Gtk.Button(label=strings.CLOSE)
        back.set_tooltip_text(strings.CLOSE_NOTE)
        back.connect("clicked", lambda _button: on_back())
        self.back_button = back

        title = Gtk.Label(label=strings.SYNC_PAGE_TITLE)
        title.set_xalign(0)
        title.add_css_class("header")
        subtitle = Gtk.Label(label=strings.SYNC_PAGE_SUBTITLE)
        subtitle.set_xalign(0)
        subtitle.add_css_class("hint")

        self.toggle = Gtk.Switch()
        self.toggle.connect("notify::active", self._on_toggled)
        self.toggle_label = Gtk.Label(label=strings.SYNC_STATUS_OFF_LABEL)
        self.toggle_label.set_xalign(0)
        toggle_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        section = Gtk.Label(label=strings.SYNC_PAGE_ACCOUNT)
        section.set_xalign(0)
        section.add_css_class("hint")
        toggle_row.append(self.toggle)
        toggle_row.append(self.toggle_label)

        self.server = Gtk.Entry()
        self.server.set_placeholder_text(strings.SYNC_PAGE_SERVER)
        self.email = Gtk.Entry()
        self.email.set_placeholder_text(strings.SYNC_PAGE_EMAIL)
        self.password = Gtk.Entry()
        self.password.set_placeholder_text(strings.SYNC_PAGE_PASSWORD)
        self.password.set_visibility(False)
        self.password.set_input_purpose(Gtk.InputPurpose.PASSWORD)

        self.sign_in_button = Gtk.Button(label=strings.SYNC_SIGN_IN)
        self.sign_in_button.connect("clicked", self._on_sign_in_clicked)
        self.sign_out_button = Gtk.Button(label=strings.SYNC_SIGN_OUT)
        self.sign_out_button.connect("clicked", lambda _button: self._on_sign_out())

        self.error = Gtk.Label(label=strings.SYNC_PAGE_BAD_LOGIN)
        self.error.set_xalign(0)
        self.error.set_wrap(True)
        self.error.add_css_class("sync-attention")
        self.error.set_visible(False)

        status_section = Gtk.Label(label=strings.SYNC_PAGE_STATUS)
        status_section.set_xalign(0)
        status_section.add_css_class("hint")
        self.status = Gtk.Label(label="")
        self.status.set_xalign(0)
        self.status.set_wrap(True)
        self.status.add_css_class("hint")

        for widget in (
            back,
            title,
            subtitle,
            section,
            toggle_row,
            self.server,
            self.email,
            self.password,
            self.sign_in_button,
            self.error,
            status_section,
            self.status,
            self.sign_out_button,
        ):
            self.append(widget)

    # -- state ---------------------------------------------------------

    def show_state(
        self,
        *,
        state: str,
        email: str = "",
        server: str = "",
        last_sync: str = "",
    ) -> None:
        """Render one of the sync states; the widget never decides, it shows."""
        signed_in = state in ("on", "paused", "needs_attention")
        self.toggle.handler_block_by_func(self._on_toggled)
        self.toggle.set_active(state == "on")
        self.toggle.handler_unblock_by_func(self._on_toggled)

        self.toggle_label.set_text(
            strings.SYNC_STATUS_ON_LABEL
            if state == "on"
            else strings.SYNC_STATUS_PAUSED_LABEL
            if state == "paused"
            else strings.SYNC_STATUS_OFF_LABEL
        )
        self.server.set_text(server)
        self.email.set_text(email)
        self.server.set_visible(not signed_in)
        self.email.set_visible(not signed_in)
        self.password.set_visible(not signed_in)
        self.sign_in_button.set_visible(not signed_in)
        self.sign_out_button.set_visible(signed_in)
        self.error.set_visible(state == "needs_attention" or bool(self.error.get_visible()))
        if state != "needs_attention":
            self.error.set_visible(False)

        if signed_in:
            when = last_sync or strings.SYNC_PAGE_NEVER
            self.status.set_text(
                strings.SYNC_PAGE_LAST.format(last=when) + f"\n{email} · {server}"
            )
        else:
            self.status.set_text(strings.SYNC_STATUS_OFF_LABEL)

    # -- callbacks -----------------------------------------------------

    def _on_toggled(self, switch: Gtk.Switch, _param) -> None:
        self._on_toggle(bool(switch.get_active()))

    def _on_sign_in_clicked(self, _button: Gtk.Button) -> None:
        server = self.server.get_text().strip()
        email = self.email.get_text().strip()
        password = self.password.get_text()
        self.password.set_text("")
        ok = self._on_sign_in(server, email, password)
        self.error.set_visible(not ok)
