from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ContainerCandidate:
    kind: str
    target_type: str
    dimension: str
    x: int
    y: int
    z: int
    created_at: float


@dataclass(slots=True)
class ContainerSession:
    kind: str
    target_type: str
    dimension: str
    x: int
    y: int
    z: int
    opened_at: float
    last_activity: float
    container_id: int | None = None
    contaminated: bool = False
    contamination_alerted: bool = False
    blocked_count: int = 0


@dataclass(slots=True)
class PlayerRuntimeState:
    """Connection-local identity cache.

    runtime_id is the hot-path key. unique_id is captured once per connection
    (or once after plugin reload) and never stringified for dictionary lookup.
    """

    runtime_id: int
    unique_id: Any
    name: str
    created_at: float


@dataclass(slots=True)
class DimensionTransfer:
    """Object identity distinguishes successive transfers on one connection."""

    target: int | None
    quarantined: bool = False


@dataclass(slots=True)
class Counters:
    transfers_started: int = 0
    transfers_completed: int = 0
    transfers_quarantined: int = 0
    transfer_packets_blocked: int = 0
    blocked_opens: int = 0
    blocked_direct_transactions: int = 0
    blocked_auth_input_requests: int = 0
    contaminated_sessions: int = 0
    rebuilt_containers: int = 0
    rebuild_failures: int = 0


@dataclass(slots=True)
class PerfCounters:
    packet_send_calls: int = 0
    packet_receive_calls: int = 0
    send_fast_returns: int = 0
    receive_fast_returns: int = 0
    send_relevant: int = 0
    receive_relevant: int = 0
    player_key_calls: int = 0
    player_cache_hits: int = 0
    player_cache_misses: int = 0
    uuid_constructs: int = 0
    uuid_to_str: int = 0
    deep_checks: int = 0
    inventory_queries: int = 0
    world_block_queries: int = 0
    database_accesses: int = 0
    payload_reads: int = 0
    send_by_packet_id: dict[int, int] = field(default_factory=dict)
    receive_by_packet_id: dict[int, int] = field(default_factory=dict)

    def reset(self) -> None:
        self.packet_send_calls = 0
        self.packet_receive_calls = 0
        self.send_fast_returns = 0
        self.receive_fast_returns = 0
        self.send_relevant = 0
        self.receive_relevant = 0
        self.player_key_calls = 0
        self.player_cache_hits = 0
        self.player_cache_misses = 0
        self.uuid_constructs = 0
        self.uuid_to_str = 0
        self.deep_checks = 0
        self.inventory_queries = 0
        self.world_block_queries = 0
        self.database_accesses = 0
        self.payload_reads = 0
        self.send_by_packet_id.clear()
        self.receive_by_packet_id.clear()
