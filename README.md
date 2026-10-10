# AntiDupe

AntiDupe is an Endstone plugin that limits Bedrock Edition Bundle/container duplication vectors. It blocks suspicious inventory requests around selected high-risk containers, quarantines contaminated sessions, and can rebuild contaminated hoppers as a destructive fallback.

**Version:** 0.2.3  
**Requirements:** Python 3.11–3.15 (CI-tested); Endstone API 0.11 (as declared by the plugin).  
**License:** GPL-3.0-only.

## Protection

- Blocks opening high-risk containers while carrying a Bundle (configurable).
- Checks inventory transaction packets (30, 147) and relevant requests embedded in PlayerAuthInput (144).
- Correlates ContainerOpen (46) with InventoryContent/InventorySlot (49, 50) by container ID to detect contamination.
- Quarantines contaminated sessions; optionally rebuilds affected hoppers while preserving block states, including facing.
- Keeps irrelevant packet callbacks inexpensive; optional performance counters are disabled by default.

Protected containers include hoppers, droppers, dispensers, furnaces, smokers, brewing stands, and crafters; hopper minecarts are also guarded. This is a targeted mitigation, **not** a universal anti-dupe solution.

## Installation

Download the wheel from the CI artifact or build it locally, place `endstone_antidupe-0.2.3-py3-none-any.whl` in the server's `plugins/` directory, remove older AntiDupe wheels, and fully restart BDS. Endstone loads plugin wheels from this directory. Do not use `/reload` to swap Python wheels.

## Commands

| Command | Function |
| --- | --- |
| `/antidupe` or `/antidupe status` | View protection status and counters |
| `/antidupe reload` | Reload the configuration |
| `/antidupe perf` | View optional packet performance counters |
| `/antidupe perf reset` | Reset performance counters |

Commands require the `antidupe.command` permission (default: operator).

## Configuration

On first enable, the plugin creates `plugins/antidupe/config.toml`. Existing configuration files and keys are preserved. Defaults:

```toml
enabled = true
alert-ops = true
log-attempts = true
player-message = "§c[AntiDupe] 收纳袋不能与该类容器进行库存交互。请先将收纳袋存入普通箱子/木桶。"
block-open-with-bundle = true
guard-player-auth-input = true
quarantine-contaminated-session = true
rebuild-on-contamination = true
rebuild-container-types = ["minecraft:hopper"]
rebuild-delay-ticks = 1
alert-cooldown-seconds = 3.0
session-timeout-seconds = 60.0
candidate-timeout-seconds = 1.5
perf-counters = false
```

**Caution:** Rebuilding a contaminated container intentionally destroys its existing block-entity inventory. It should be used only when this trade-off is acceptable. Failed rebuilds remain quarantined (fail-closed).

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
uv build --wheel
```

The test suite mocks the Endstone host API; passing it is not a substitute for an in-server integration test. Python 3.15 support here refers to the pure-Python plugin and its universal wheel; running a BDS server on Python 3.15 also requires a compatible native Endstone distribution. CI builds and verifies wheel metadata and contents without deploying to a server or publishing a release.

Historical profiling notes are in [`docs/performance.md`](docs/performance.md).
