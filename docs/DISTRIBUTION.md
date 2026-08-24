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
3. Build one wheel and stage the npm tarball from it.
4. Create the GitHub release and upload the wheel.
5. Download and byte-verify the immutable release asset.
6. Publish the already-staged npm tarball with provenance.
7. Render the Homebrew formula from the verified release URL and SHA-256.
8. Update `rlaope/homebrew-tap/Formula/omh.rb` only when its existing version
   is older; an equal version must already be byte-identical, and a newer
   version blocks the run.

All distribution tags share one non-cancelling concurrency group. The tap
update cannot run before npm publication succeeds, and an older run cannot
downgrade a newer tap formula.

## Release cadence

Releases are cut by hand. Package-manager channels advance only when a
maintainer bumps the version surfaces and pushes a `vX.Y.Z` tag, so `main`
can sit ahead of the published packages between releases; that gap is
expected, not a fault. A scheduled auto-tagging workflow was tried and
removed: automatic patch bumps moved the public version without a person
deciding a release was warranted.

## Resume and rollback

The workflow is safe to resume with `workflow_dispatch` and the existing tag
when that tag remains on protected `main` and every later change is confined
to the explicit release-control allowlist: the release workflow, distribution
metadata verifier, its contract test, and this recovery documentation. The
workflow loads the verifier from current `main` while building all published
artifacts from the immutable tag. Any artifact-affecting change after the tag
blocks recovery and requires a new patch release.

A resumed run reuses a GitHub asset only when its bytes match the locally
rebuilt wheel, accepts an existing npm version only when its integrity matches
the staged tarball, and skips a tap commit when the formula is already
identical.

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
