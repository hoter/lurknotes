"""First-launch onboarding is shown once (spec §4.6, §9.2)."""

from __future__ import annotations

from pathlib import Path

from lurkn.onboarding import mark_onboarded, marker_path, needs_onboarding


def test_a_fresh_data_dir_needs_onboarding(tmp_path: Path) -> None:
    assert needs_onboarding(tmp_path) is True
    assert marker_path(tmp_path) == tmp_path / "lurknotes" / "onboarded"


def test_marking_creates_the_marker_and_never_asks_again(tmp_path: Path) -> None:
    assert mark_onboarded(tmp_path) is True

    assert marker_path(tmp_path).is_file()
    assert needs_onboarding(tmp_path) is False


def test_marking_is_idempotent(tmp_path: Path) -> None:
    assert mark_onboarded(tmp_path) is True
    assert mark_onboarded(tmp_path) is True
    assert needs_onboarding(tmp_path) is False


def test_an_unwritable_data_dir_does_not_crash(tmp_path: Path) -> None:
    # A file where the data directory should be makes mkdir fail. The app must
    # still run; only the "never again" promise is lost until the disk is fixed.
    (tmp_path / "lurknotes").write_text("not a directory", encoding="utf-8")

    assert mark_onboarded(tmp_path) is False
    assert needs_onboarding(tmp_path) is True
