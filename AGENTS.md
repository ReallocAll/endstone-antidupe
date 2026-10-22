# Development guidelines

- Maintain the current Endstone API 0.11 runtime contract and Python >=3.11 baseline; test CPython 3.11–3.15 in CI (without imposing a needless upper bound). Do not change protocol IDs or packet semantics without testing against a specific BDS protocol revision.
- Keep event handler parameter annotations as **runtime classes**. Do not enable `from __future__ import annotations` in `plugin.py`: Endstone 0.11 checks event annotation objects directly.
- Filter packet IDs before accessing `event.player`, `event.payload`, UUID, inventory, or block state. Avoid heavy work and logging in packet callbacks.
- Preserve `/antidupe` command forms, permissions, configuration keys/defaults, and quarantine/rebuild fail-closed semantics.
- Rebuild is destructive. Only act on correlated container-ID contamination, retain the original block data, and avoid replacing a block already changed by another actor.
- Use `uv sync --extra dev`, `uv run ruff check .`, `uv run pytest`, and `uv build --wheel`. Review wheel entry point `antidupe = endstone_antidupe:AntiDupe`.
- Extend regression tests for session lifecycle, identity cache, reconnection/runtime-ID reuse, multiple players, packet filtering, and container rebuild before behavior changes.
- Do not commit player/world data, secrets, server configs, build output, or virtual environments. Publish GitHub Releases only through the authorized, version-validated release workflow after all CI checks pass. Never publish to PyPI.
