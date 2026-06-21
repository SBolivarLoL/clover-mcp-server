# Releasing

Releases are cut by pushing a version tag. The [`Release` workflow](.github/workflows/release.yml)
then builds the artifacts, creates a GitHub Release, and publishes to PyPI.

## One-time PyPI setup (trusted publishing)

Publishing uses PyPI **trusted publishing** (OIDC) — no API token is stored in the
repo. Configure it once on PyPI before the first publish:

1. Sign in to <https://pypi.org> with the account that will own `clover-mcp`.
2. Go to **Your projects → Publishing** (or, for a brand-new name, **Add a pending
   publisher**) and add a GitHub publisher:
   - **PyPI Project Name:** `clover-mcp`
   - **Owner:** `SBolivarLoL`
   - **Repository:** `clover-mcp-server`
   - **Workflow name:** `release.yml`
   - **Environment:** *(leave blank)*
3. Save. The next tag push will publish automatically.

PyPI uploads are **immutable** — a version can never be re-uploaded. Always bump
the version for a new release.

## Steps

1. Bump `version` in `pyproject.toml` (SemVer).
2. In `CHANGELOG.md`, move the `[Unreleased]` items under a new `[X.Y.Z]`
   heading dated today.
3. Commit: `git commit -am "release: vX.Y.Z"`.
4. Tag and push:
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

The workflow verifies the tag matches the package version, builds the sdist +
wheel, creates a GitHub Release (artifacts + auto-generated notes), and publishes
to PyPI via trusted publishing. The tag **must** equal the `pyproject.toml`
version (prefixed with `v`) or the build fails fast.

If the PyPI trusted publisher isn't set up yet, the GitHub Release still succeeds;
only the final publish step fails (re-runnable once configured).
