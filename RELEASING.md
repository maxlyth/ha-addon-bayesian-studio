# Releasing

This project uses tag-triggered GitHub Releases. Pushing an annotated tag of the
form `vX.Y.Z` runs [`.github/workflows/release.yml`](.github/workflows/release.yml),
which runs the test suite and — on green — creates a GitHub Release whose body is
extracted from the matching `## [X.Y.Z]` section in [`CHANGELOG.md`](CHANGELOG.md).

## Checklist

1. **Bump the version in all three files.** Enforced by `tests/test_version.py`:
   - `bayesian-studio/config.yaml` — `version:`
   - `bayesian-studio/Dockerfile` — `ARG VERSION=`
   - `pyproject.toml` — `version =`
2. **Add a changelog entry** under a new `## [X.Y.Z] - YYYY-MM-DD` heading in
   `CHANGELOG.md`. The release workflow fails if no matching section exists.
3. **Commit and push** to `main`. Wait for the `Tests` workflow to pass.
4. **Tag and push:**
   ```sh
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
5. The `Release` workflow runs the tests again, extracts the changelog section,
   and publishes the release. Verify it appears under
   [Releases](https://github.com/maxlyth/ha-addon-bayesian-studio/releases).

## Local deploy (no tag)

`./deploy_local.sh` rsyncs the current source into `/addons/local/bayesian_studio/`
and triggers a Supervisor rebuild or update. Intended for rapid iteration; does
not touch GitHub, tags, or the changelog.
