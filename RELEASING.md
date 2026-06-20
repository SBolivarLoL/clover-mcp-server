# Releasing

Releases are cut by pushing a version tag. The [`Release` workflow](.github/workflows/release.yml)
then builds the artifacts and creates a GitHub Release automatically.

**Nothing is published to PyPI** — releases are GitHub-only for now (intentional).

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
wheel, and publishes a GitHub Release with the artifacts attached and
auto-generated notes. The tag **must** equal the `pyproject.toml` version
(prefixed with `v`) or the build fails fast.

## Enabling PyPI later

Add a publish step after the build in `release.yml`:

```yaml
      - name: Publish to PyPI
        run: uv publish
        # configure a trusted publisher (OIDC) on PyPI, or set UV_PUBLISH_TOKEN
```
