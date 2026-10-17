# AntiDupe 0.2.3 Performance Review

This report records the historical 0.2.3 implementation and measurements. Its packet lists, lifecycle behavior, and test count are not a description of the 0.2.4 dimension-transfer guard; see the [current README](../README.md) for that behavior. No new benchmark results are implied by this translation.

## Baseline

Baseline hotspots in the supplied profile report:

- `AntiDupe.on_packet_send` ≈ 7.16 ms/tick
- `AntiDupe._player_key` ≈ 5.38 ms/tick
- Python UUID path ≈ 2.98 ms/tick
- Frequent ActorMotionSync packets continually amplify the AntiDupe packet listener cost

## 0.2.1 hot path

Old outbound path:

```text
PacketSendEvent
→ event.player
→ _player_key
→ player.unique_id
→ C++ UUID -> Python uuid.UUID
→ str(UUID)
→ time.monotonic
→ only then check packet_id
```

Every entity synchronization packet therefore incurred the player/UUID/string costs.

Old inbound path:

```text
PacketReceiveEvent
→ event.player
→ _player_key / UUID string
→ session lookup
→ _session_is_unsafe
→ possibly scan player.inventory
→ only then distinguish 144 / 30 / 147
```

## 0.2.3 hot path

Ordinary outbound packet:

```text
PacketSendEvent
→ packet_id
→ not in {46,47,49,50}
→ return
```

Ordinary inbound packet:

```text
PacketReceiveEvent
→ packet_id
→ not in {30,47,144,147}
→ return
```

`PlayerAuthInput(144)`:

```text
packet_id
→ no active high-risk session? return
→ event.player
→ runtime_id (uint64)
→ session lookup
→ payload
→ bit 36 absent? return
→ unsafe check
→ only then possibly inventory scan/cancel
```

Ordinary ActorMotionSync packets do not read `event.player`, payload, UUID, inventory, or world state.

## Identity cache

Connection-local dictionary key is now `player.runtime_id` (`uint64`).

`PlayerRuntimeState` caches:

- runtime ID
- stable UUID object (captured once, never converted to str for lookup)
- player name
- creation timestamp

Lifecycle:

- join: reset any stale state for reused runtime ID, cache connection identity
- lazy miss after plugin reload: cache once
- quit: clear runtime state + sessions + candidates + report cooldowns
- dimension change: clear transient sessions/candidates, preserve connection identity
- reload/disable: clear all runtime state

## Packet list after review

Outbound: 46, 47, 49, 50 only.
Inbound: 30, 47, 144, 147 only.

No actor movement packet is required by the anti-dupe state machine.

## Allocation / IO review

Removed from irrelevant packet hot path:

- `uuid.UUID` construction
- `str(UUID)`
- player property lookup
- payload access/copy
- `payload.lower()` bytes allocation
- inventory lookup
- world/block lookup
- report string construction

No SQLite/database/file IO exists in packet callbacks. Config file IO occurs only on enable/reload.

## Instrumentation

`perf-counters = true` exposes:

- send/receive callback counts
- per-packet-ID counts
- relevant/fast-return counts
- `_player_key` calls
- player cache hit/miss
- UUID constructs / UUID-to-string count
- deep checks
- inventory queries
- payload reads
- world/block queries
- database accesses

Counters are disabled by default to avoid perturbing the production profile.

## Tests

Automated regression suite covers:

- irrelevant outbound/inbound packet fast return before player/payload
- PlayerAuthInput with no active session
- inventory sync with no active session
- runtime ID identity cache and one-time UUID construction
- 158-entity motion storm simulation
- normal safe container transaction
- Bundle holder transaction blocking
- contaminated-session blocking without inventory scan
- PlayerAuthInput bit-36 positive/negative paths
- exact container ID contamination correlation
- reconnect/runtime-ID reuse
- multi-player isolation
- dimension-change session cleanup
- destructive rebuild state restoration / changed-block protection
- Endstone 0.11 real-class event annotations (no postponed string annotations)

Result: `24 passed` (the 0.2.3 source regression suite).

## Synthetic hot-path benchmark

200,000 representative irrelevant outbound movement callbacks, CPython test harness:

```text
0.2.3: 0.174 us/call, UUID reads=0, runtime-id reads=0,
       event.player reads=0, payload reads=0
0.2.1 ordering model: 2.678 us/call, UUID reads=200,000
synthetic speedup: ~15.37x
```

This is not a replacement for Spark/BDS profiling; it validates that the expensive operations identified in the profile are structurally absent from irrelevant packets.

## Remaining Endstone limitation

Endstone 0.11.12 registers Python listeners by event class, not packet ID. Its network hook creates a `PacketSendEvent` / `PacketReceiveEvent` and calls the plugin manager for packets generally. AntiDupe therefore cannot prevent the Python handler invocation itself for unrelated packet IDs.

After this refactor the remaining per-unrelated-packet AntiDupe work is essentially:

```text
Python callback dispatch
→ event.packet_id getter
→ integer set-membership test
→ return
```

Eliminating that fixed callback cost requires a native packet-ID subscription/filter in Endstone core or a native implementation of this guard.

## Next Spark profile

Verify:

- `AntiDupe._player_key` is no longer a hotspot
- `uuid.UUID.__init__` / `uuid.UUID.__str__` disappear from AntiDupe packet paths
- `ActorMotionSync → sendPacket → EventHandler → AntiDupe.on_packet_send` collapses to small fixed callback cost
- `AntiDupe.on_packet_send` drops sharply from the ≈7.16 ms/tick baseline
- Endstone aggregate `EventHandler` may still remain visible because other packet listeners and native event dispatch remain
