# Releasing

Publishing is tag-based: pushing a `v*` tag builds the package and uploads it to PyPI through
trusted publishing (no API token is stored anywhere).

One-time setup on PyPI: Account → Publishing → add a pending publisher with
project `whygit`, owner `Srikarmk`, repository `whygit`, workflow `publish.yml`, environment `pypi`.

Each release:

1. Bump the version in both `pyproject.toml` and `src/whygit/__init__.py` (the workflow refuses a mismatch).
2. Commit, then `git tag vX.Y.Z && git push origin main vX.Y.Z`.
3. Check the Publish run on GitHub Actions, then `uvx whygit@X.Y.Z --version`.
