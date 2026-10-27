#!/usr/bin/env python3
"""Build ``dist/lurknotes_<version>_all.deb`` without debhelper.

The app is pure Python on top of the system PyGObject/GTK 4, so the package
only stages the ``lurkn`` package, a launcher, the desktop entry and the icon.
Run from anywhere:

    .venv/bin/python scripts/build_deb.py
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


def version() -> str:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return project["project"]["version"]


def main() -> int:
    package = "lurknotes"
    version_value = version()
    build = ROOT / "build" / f"deb-{package}-{version_value}"
    root = build / f"{package}_{version_value}_all"
    if root.exists():
        shutil.rmtree(root)
    (root / "DEBIAN").mkdir(parents=True)

    share = root / "usr" / "share"
    dist_packages = root / "usr" / "lib" / "python3" / "dist-packages"

    shutil.copytree(
        ROOT / "src" / "lurkn",
        dist_packages / "lurkn",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (root / "usr" / "bin").mkdir(parents=True)
    launcher = root / "usr" / "bin" / "lurknotes"
    launcher.write_text(
        "#!/usr/bin/python3\n"
        "from lurkn.__main__ import main\n"
        "\n"
        "raise SystemExit(main())\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)

    (share / "applications").mkdir(parents=True)
    shutil.copy2(
        ROOT / "packaging" / "lurknotes.desktop",
        share / "applications" / "dev.lurknotes.LurkNotes.desktop",
    )
    icon_dir = share / "icons" / "hicolor" / "scalable" / "apps"
    icon_dir.mkdir(parents=True)
    shutil.copy2(ROOT / "packaging" / "lurknotes.svg", icon_dir / "lurknotes.svg")
    doc_dir = share / "doc" / package
    doc_dir.mkdir(parents=True)
    shutil.copy2(ROOT / "README.md", doc_dir / "README.md")

    # Keep the staged tree conventional: 755 directories, 644 files, and the
    # launcher executable. copytree/copy2 preserve the checkout's umask.
    for path in root.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    launcher.chmod(0o755)

    (root / "DEBIAN" / "control").write_text(
        f"""Package: {package}
Version: {version_value}
Section: utils
Priority: optional
Architecture: all
Depends: python3:any (>= 3.12~), python3-gi, gir1.2-gtk-4.0
Maintainer: Erlan Aytpaev <aytpaev@gmail.com>
Description: Notes deck at the edge of the screen
 LurkNotes is a GTK4 notes deck that sits at the right edge of the
 GNOME desktop. Hover the strip to open the fan, click a tab to edit,
 and keep everything in a local JSON file.
""",
        encoding="utf-8",
    )
    (root / "DEBIAN" / "control").chmod(0o644)

    DIST.mkdir(exist_ok=True)
    output = DIST / f"{package}_{version_value}_all.deb"
    subprocess.run(
        ["dpkg-deb", "--root-owner-group", "--build", str(root), str(output)],
        check=True,
    )
    print(output.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
