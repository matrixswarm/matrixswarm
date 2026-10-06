# Versioned website downloads

`publish.py` is a Linux host publisher using Python's standard library. It reads
the public MatrixSwarm GitHub repository; it needs no GitHub or SSH credentials.
It downloads source for the exact current `main` commit only after the latest
push runs of both Security checks and Phoenix offline process tests succeed.
No code from the downloaded archive is executed or extracted.

The filename contains the UTC commit date and full commit SHA. Each ZIP has
matching `.zip.sha256` and `.zip.sha512` checksum files plus a versioned JSON
manifest. Published versioned bytes are not replaced. An atomic `latest.json`
pointer changes only after all files are available; failed checks or downloads
leave the previous public version in place. Old releases remain available.

This publishes checked main snapshots, not semantic version releases or packaged
executables. Branch commits and pull requests are not published. Existing CI
success is a publication gate, not a claim of complete application coverage.

## Website installation

- Install `publish.py` outside the document root, e.g.
  `/usr/local/lib/matrixswarm-downloads/publish.py`.
- Create `/sites/matrixswarm/shared/downloads` and make it writable by a dedicated
  `matrix-downloads` account. Serve it as the active release's `public/downloads`
  symlink. The PHP/web account only needs read access.
- Run every five minutes as that account, using the root-owned installed script:
  `python3 publish.py --destination /sites/matrixswarm/shared/downloads`.
- Install `apache.conf` with mod_headers and reload Apache after checking config.
  It prevents caching the current manifest and download page. Immutable versioned
  assets can be cached without confusing one release with another.
- Install `download.phtml` as the MatrixSwarm site's download template. It reads
  the local manifest and links to the exact version and its checksums.
- Configure any CDN Cache Everything override to respect these origin headers
  or bypass `/download/` and `/downloads/latest.json`.

The runtime publisher and web template are deliberately installed copies, not
automatically executed scripts from new commits. Deploy changes to this tooling
explicitly. The lock prevents concurrent publishers; review the publisher log
if no new version appears. GitHub API limits or failed checks postpone updates.
Recreate the downloads symlink when switching website releases. Retention is
manual: do not delete the version referenced by `latest.json`.

For the first installation, if current main is failing, seed the last checked
main commit with `--bootstrap-commit FULL_COMMIT_SHA`. This is allowed only when
`latest.json` does not yet exist. The publisher verifies that the commit is an
ancestor of current main and still requires both successful push checks. Normal
scheduled runs omit this option and publish current main once its checks pass.

## Verify a download

Linux: `sha256sum -c matrixswarm-VERSION.zip.sha256` or
`sha512sum -c matrixswarm-VERSION.zip.sha512`.

PowerShell: `Get-FileHash .\matrixswarm-VERSION.zip -Algorithm SHA256` or
`Get-FileHash .\matrixswarm-VERSION.zip -Algorithm SHA512`; compare with the
matching checksum file. These hashes verify downloaded bytes; they are not a
digital signature or independent proof of publisher identity.
