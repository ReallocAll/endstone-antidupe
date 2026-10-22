# Release procedure

Update pyproject.toml and docs/releases/VERSION.md (plus CHANGELOG.md where present). Commit on the existing default branch with the exact subject `chore: release vVERSION`. As in EndKeep, this is the formal release request: ordinary pushes only validate. The complete CI matrix must pass before publication. The release job downloads this same run's wheel, validates its metadata and entry point, tags the exact tested commit without moving an existing tag, and publishes the wheel with SHA256SUMS. Existing releases are never overwritten.

A matching vVERSION tag or workflow_dispatch with version and dry_run=false is also supported. Dispatch defaults to validation only. No PyPI publishing or server deployment occurs.
