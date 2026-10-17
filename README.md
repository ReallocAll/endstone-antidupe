# AntiDupe

[English](README.md) | [简体中文](README.zh-CN.md)

AntiDupe is an Endstone plugin that limits Bedrock Edition Bundle/container duplication vectors. It blocks suspicious inventory requests around selected high-risk containers, quarantines contaminated sessions, and can rebuild contaminated hoppers as a destructive fallback.

**Version:** 0.2.4

**Requirements:** Python >=3.11; Endstone API 0.11 (as declared by the plugin). The CI compatibility matrix targets CPython 3.11–3.15.

**License:** GPL-3.0-only.

## Protection

- Blocks opening high-risk containers while carrying a Bundle (configurable).
- Checks inventory transaction packets (30, 147) and relevant requests embedded in PlayerAuthInput (144).
- Correlates ContainerOpen (46) with InventoryContent/InventorySlot (49, 50) by container ID to detect contamination.
- Quarantines contaminated sessions; optionally rebuilds affected hoppers while preserving block states, including facing.
- Keeps irrelevant packet callbacks inexpensive; optional performance counters are disabled by default.
- On protocol **2193**, immediately guards an outbound ChangeDimension (61) until the matching server dimension-completion event and one subsequent scheduler tick. Standalone inventory packets (30, 147) are blocked even without a container session.

Protected containers include hoppers, droppers, dispensers, furnaces, smokers, brewing stands, and crafters; hopper minecarts are also guarded. This is a targeted mitigation, **not** a universal anti-dupe solution.

## Installation

Download the release wheel or build it locally, place `endstone_antidupe-0.2.4-py3-none-any.whl` in the server's `plugins/` directory, remove older AntiDupe wheels, and fully restart BDS. Endstone loads plugin wheels from this directory. Do not use `/reload` to swap Python wheels.

## Dimension-transfer protection

The dimension-transfer guard contains the observed unfinished cross-dimension transfer path using public Endstone events only. While waiting it allows Disconnect (5), Respawn (45), NetworkStackLatency (115), selected PlayerAction (36) transition actions (7, 14, 30, 38), validated ServerboundLoadingScreen (312) start/end frames with an optional uint32 ID, validated terrain-loading requests (RequestChunkRadius 69, ClientCacheBlobStatus 135, SubChunkRequest 175), and PlayerAuthInput (144) movement with no actionable flags or embedded mutations. Unknown packet IDs are denied. The protocol-2193 parser independently checks the three mutation optionals, so omitting their declared flags cannot bypass protection. Terrain-loading requests, loading-screen start/end frames, client movement, standing still, teleport ACKs, and player validity are not proof that a transfer completed.

After the configured timeout, the connection is quarantined immediately: **all** inbound application packets are cancelled, and a kick for that exact connection is scheduled for the next tick. A replacement connection is not the target of the deferred kick. The plugin reasserts uncancelled kicks for quarantined sessions at HIGHEST priority, but public APIs cannot guarantee disconnection. If the player remains online after the kick, the plugin logs that fact and keeps quarantine until PlayerQuitEvent. A timeout is **not unique proof of a ghost player**; a slow or interrupted legitimate transfer can also time out.

Completion release relies on the server's dimension-change AFTER event finishing synchronous native cleanup before the next scheduler heartbeat. This is bounded containment, not a repair of the native server bug or universal save-state introspection. Same-dimension respawn and independent server-generated item drops are **not proven covered**.

`/antidupe reload` preserves active transfers and quarantines for the same online connections, even when new protection is disabled in configuration. Container cleanup cannot release them. Enabling the plugin with already-online players on a supported protocol quarantines and schedules kicks for those sessions to obtain fresh known joins; a full server restart is preferred. Protection cannot be guaranteed while the plugin is disabled. Unsupported protocols disable only the new transfer guard and emit a warning; existing container protection keeps its prior behavior.

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
player-message = "§c[AntiDupe] Bundles cannot interact with this container. Store the Bundle in a normal chest or barrel first."
block-open-with-bundle = true
guard-player-auth-input = true
guard-dimension-transfer = true
dimension-transfer-timeout-seconds = 10.0
dimension-transfer-kick-message = "[AntiDupe] Dimension transfer did not complete safely. Please reconnect."
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

The transfer timeout is clamped to 1–120 seconds and scheduled at 20 ticks per second. Status includes transfer start/completion/quarantine and blocked-packet counters. Existing configuration files are not rewritten; missing keys use defaults.

Edit `player-message` and `dimension-transfer-kick-message` to customize the player-facing messages, save `config.toml` as UTF-8, then run `/antidupe reload`. Existing messages are not automatically translated on upgrade. The [Chinese server-owner guide](README.zh-CN.md#配置中文玩家提示) includes a ready-to-use Chinese example. Administrative commands and logs remain in English; these two settings do not localize the whole plugin.

## Validation and limits

A live test on Linux BDS 26.52 with Endstone 0.11.14 observed normal dimension transfer without a parrot. In the tested stalled transfer with a parrot, the 10-second timeout quarantined the connection and actually disconnected the player before the manual item-drop stage. This confirms containment of that observed path. It does not establish explicit drop-packet blocking or item-count conservation, and it does not prove that every duplication path is covered. Automated tests do not establish those live-world outcomes either.

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
uv build --wheel
```

The test suite mocks the Endstone host API; passing it is not a substitute for an in-server integration test. Python 3.15 support here refers to the pure-Python plugin and its universal wheel; running a BDS server on Python 3.15 also requires a compatible native Endstone distribution. CI builds and verifies wheel metadata and contents without deploying to a server or publishing a release.

Historical profiling notes are in [`docs/performance.md`](docs/performance.md).
