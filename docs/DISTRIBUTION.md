# Package-manager distribution

This is the maintainer contract for publishing the same OMH release through
GitHub, npm/Bun, and Homebrew. Normal users only need the installation choices
in the README or website.

## Public package identities

| Surface | Identity |
| --- | --- |
| Python wheel | `oh_my_hermes-X.Y.Z-py3-none-any.whl` |
| npm and Bun | `oh-my-hermes@X.Y.Z` |
| Homebrew tap | `rlaope/tap/omh` |
| CLI | `omh` |

`pyproject.toml` is the canonical version source. A release is refused unless
`src/omh/version.py`, the wheel metadata, npm metadata, tag, and rendered
formula carry the same `X.Y.Z`.

## Platform boundary

Windows npm/Bun launcher support is gated by the Windows CI suite. The shared
launcher has Windows path, `py -3`, and command-shim handling, but support must
remain marked pending until that Windows job installs the packed tarball and
runs the CLI successfully.

## One-time release setup

Before advertising the package-manager commands:

1. Reserve `oh-my-hermes` on npm.
2. Configure npm trusted publishing for
   `rlaope/oh-my-hermes`, workflow `.github/workflows/release.yml`, and
   environment `npm`.
3. Create the public repository `rlaope/homebrew-tap` with a default branch.
4. Add a write-enabled deploy key to `rlaope/homebrew-tap` and store its
   private key as the `HOMEBREW_TAP_SSH_KEY` repository secret. The key must
   grant access only to that tap.
5. Keep the GitHub `npm` environment protected according to the release policy.

The workflow uses GitHub OIDC for npm provenance. It does not require a
long-lived npm token. npm trusted publishing requires Node 22.14.0 or newer and
npm CLI 11.5.1 or newer; the workflow installs and verifies those minimums
before any release work.

## Local dry run

```sh
rm -rf dist/distribution
export SOURCE_DATE_EPOCH="$(git log -1 --format=%ct)"
uv build --wheel --out-dir dist/distribution/python
wheel="$(find dist/distribution/python -name '*.whl' -print -quit)"
uv run tools/package_manager/metadata.py --wheel "$wheel" --json
uv run tools/package_manager/stage_npm.py \
  --wheel "$wheel" \
  --output dist/distribution/npm
npm publish --dry-run dist/distribution/npm
```

The npm package vendors that exact wheel. The npm/Bun launcher verifies its
SHA-256, requires an existing Python 3.11 or newer interpreter, and never
downloads source or Python packages.

Render a local Homebrew formula from the same wheel:

```sh
version="$(uv run tools/package_manager/metadata.py --version)"
uv run tools/package_manager/render_homebrew.py \
  --version "$version" \
  --wheel "$wheel" \
  --output dist/distribution/omh.rb
ruby -c dist/distribution/omh.rb
```

## Release order

A `vX.Y.Z` tag runs the distribution workflow in this order:

1. Validate that a newly pushed tag resolves to the current protected `main`
   tip and that every version surface matches. A manual recovery may use an
   older tag only when every later `main` change is confined to the
   release-control allowlist.
2. Run distribution contract tests.
3. Generate the revision-bound release evidence bundle
   (`omh_release_evidence_bundle/v2`) from the exact tagged checkout and
   assert it is `ready`, publication-ready, clean, and bound to the tag
   commit. Any other state blocks the run before anything is built or
   published.
4. Build one wheel and stage the npm tarball from it.
5. Rebind the canonical local evidence bundle
   (`.omh/runtime/release-evidence/X.Y.Z.json`) to the built wheel so the
   retained bundle records the artifact's SHA-256, and assert that digest equals
   the build's recorded wheel digest.
6. Create the GitHub release and upload the wheel plus the evidence bundle
   (`omh-release-evidence-X.Y.Z.json`) as immutable assets.
7. Download and byte-verify the immutable release assets. The evidence
   bundle is compared with its `created_at` stamp excluded: regeneration at
   the same tag legitimately re-stamps it, while every binding field
   (schema, revision, tree, input digests, artifact digest, status) must be
   identical, so a resumed run cannot accept a bundle bound to different
   content behind a matching version/tag.
8. Publish the already-staged npm tarball with provenance.
9. Render the Homebrew formula from the verified release URL and SHA-256.
10. Update `rlaope/homebrew-tap/Formula/omh.rb` only when its existing
    version is older; an equal version must already be byte-identical, and a
    newer version blocks the run.

All distribution tags share one non-cancelling concurrency group. The tap
update cannot run before npm publication succeeds, and an older run cannot
downgrade a newer tap formula.

## Cutting a release on demand

**Deciding that `main` deserves a version is a human decision.** Nothing in
this repository cuts a release on its own: `main` may sit any distance ahead
of the published packages, and that gap is not a fault to be automated away.
People who want `main` itself install the preview channel, which needs no
version at all.

`.github/workflows/auto-release.yml` (Actions → *Cut Release* → Run workflow)
performs the release mechanics once a maintainer asks for one. It bumps every
version surface to the next patch with `tools/package_manager/bump_version.py`
(pyproject, `src/omh/version.py`, the plugin manifest, the landing page's
`hero.badge` in `site/index.html` and `site/i18n.js`, and `.release-channel`
back to `stable`), runs the full test suite on the bumped tree, pushes the
commit and `vX.Y.Z` tag to `main` atomically, and dispatches the distribution
workflow for that tag.

Boundaries:

- `workflow_dispatch` is the only trigger. An earlier revision carried a daily
  `schedule:`; it advanced the public version every day that `main` moved,
  without anyone choosing to release. `tests/test_auto_release.py` now fails if
  a schedule, push, or pull_request trigger reappears.
- It cuts stable patch releases only. When the version in `pyproject.toml`
  has no tag yet, a release is already staged by hand and the workflow skips
  without touching anything.
- Publication still pauses at the protected `npm` environment for one human
  deployment approval, after the tag exists and before anything is published.
- The bump commit and tag are pushed with the workflow's `GITHUB_TOKEN`, so
  they do not trigger the tag-push path of the distribution workflow or a CI
  run on `main`; the job runs the full suite itself before pushing, and it
  starts the distribution workflow through `workflow_dispatch` with the new
  tag.
- To bump by hand instead, run `uv run tools/package_manager/bump_version.py`
  (`--set X.Y.Z` for a minor or major, `--dry-run` to preview) and follow the
  Required Checks in [Release](RELEASE.md).
- Publishing changes no installed machine. The tag and the registries move;
  `omh --version`, the plugin manifest, and the Hermes TUI HUD footer keep
  reporting the version each machine installed until it runs `omh update`.
  [Release](RELEASE.md), "After the Cut", owns that step.

## Resume and rollback

The workflow is safe to resume with `workflow_dispatch` and the existing tag
when that tag remains on protected `main` and every later change is confined
to the explicit release-control allowlist: the release workflow, distribution
metadata verifier, its contract test, and this recovery documentation. The
workflow loads the verifier from current `main` while building all published
artifacts from the immutable tag. Any artifact-affecting change after the tag
blocks recovery and requires a new patch release.

A resumed run reuses a GitHub asset only when its bytes match the locally
rebuilt wheel, accepts an existing evidence-bundle asset only when its
binding fields match the locally regenerated bundle (compared with the
`created_at` stamp excluded), accepts an existing npm version only when its
integrity matches the staged tarball, and skips a tap commit when the
formula is already identical. A legitimately regenerated bundle that differs
from the published one — for example after a schema fix — is rejected the
same way an artifact identity mismatch is: correct the source, bump the
patch version, and cut a new tag instead of replacing the asset.

Published npm versions and GitHub release assets are immutable. Do not replace
them. If an identity mismatch occurs, stop the workflow and publish a new patch
version after correcting the source. If npm succeeds but the tap update fails,
repair the tap credential or formula and resume the same tag; the workflow
verifies the existing npm artifact before continuing. If artifact-affecting
source advanced before recovery, publish the correcting patch release instead.

### GitHub release succeeds, npm fails

Do not delete or replace the release wheel. Repair the npm trusted-publisher
configuration or environment approval, then resume the same tag. The
reproducible rebuild must match the existing wheel byte for byte before the
workflow may retry npm. The tap remains unchanged until npm succeeds.
If later `main` changes exceed the release-control allowlist, use a new patch
release.

### npm succeeds, Homebrew tap fails

The npm version is immutable. Repair only the tap repository, token, formula,
or style failure, then resume the same tag. The workflow must verify the
existing npm integrity before rendering and pushing the formula; it must not
republish npm. If later `main` changes exceed the release-control allowlist,
publish a new patch release so the tap advances monotonically.

### Release asset is missing

If the GitHub release exists but its versioned wheel is absent, the workflow
may upload that exact wheel once before npm publication. It must never use
`--clobber`. A missing asset discovered after npm publication is a release
incident: stop, restore the matching immutable asset, and verify its SHA-256
before touching the tap.

### Artifact identity mismatch

Never overwrite a GitHub asset, npm version, or tap formula to hide an identity
mismatch. Stop the workflow, correct the source, bump to a new patch version,
and create a new tag. Record the partial prior release in the release notes and
leave its immutable evidence intact.
