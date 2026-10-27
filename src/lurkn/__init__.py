"""LurkNotes — a notes deck at the edge of the screen."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lurknotes")
except PackageNotFoundError:  # source checkout / deb without .dist-info
    __version__ = "0.1.0"

__all__ = ["__version__"]
