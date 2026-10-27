"""Dark theme, loaded before any window is mapped (spec §6.4)."""

from __future__ import annotations

from importlib.resources import files

from gi.repository import Gdk, Gtk


def theme_css() -> str:
    return files(__package__).joinpath("theme.css").read_text(encoding="utf-8")


def install(display: Gdk.Display) -> Gtk.CssProvider:
    provider = Gtk.CssProvider()
    provider.load_from_string(theme_css())
    Gtk.StyleContext.add_provider_for_display(
        display,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
    return provider
