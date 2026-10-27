# Releasing LurkNotes

The release is built from a clean tree on the machine that runs the tests; the
version comes from `pyproject.toml` and the tag must match it.

## 1. Bump the version

Edit `version` in `pyproject.toml` (for example `0.1.0`), commit, and make sure
`README.md` install snippets mention the same version.

## 2. Build the artifacts

```sh
.venv/bin/pip install build pillow
.venv/bin/python -m build --sdist
.venv/bin/python scripts/build_deb.py
ls -l dist/
```

- `dist/lurknotes-<version>.tar.gz` — Python sdist for `pipx install`.
- `dist/lurknotes_<version>_all.deb` — system package for Ubuntu 24.04.

Check the deb before uploading:

```sh
dpkg-deb -I dist/lurknotes_0.1.0_all.deb
dpkg-deb -c dist/lurknotes_0.1.0_all.deb
```

## 3. Tag and push

```sh
git tag -a v0.1.0 -m "LurkNotes 0.1.0"
git push origin v0.1.0
```

## 4. Create the GitHub release

With `gh` authenticated (`gh auth login`), from the repository root:

```sh
gh release create v0.1.0 \
  dist/lurknotes-0.1.0.tar.gz \
  dist/lurknotes_0.1.0_all.deb \
  --title "LurkNotes 0.1.0" \
  --generate-notes
```

Without `gh`, create the release on GitHub, choose `v0.1.0` as the tag, paste
the notes, and attach both files from `dist/`. Mark a first attempt as
*pre-release* if it is only for validating `pipx`/the deb on a clean machine.

The release assets are what the README install commands point at. Upload does
not publish to PyPI and does not need a store account; Snap packaging is a
separate step.
