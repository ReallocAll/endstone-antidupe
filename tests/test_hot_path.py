from uuid import UUID

import pytest

from endstone_antidupe.constants import (
    PACKET_CONTAINER_OPEN,
    PACKET_INVENTORY_CONTENT,
    PACKET_PLAYER_AUTH_INPUT,
)
from endstone_antidupe.state import ContainerCandidate
from .helpers import CountingPlayer, PacketEvent, auth_input_payload, make_plugin


@pytest.mark.parametrize('cancelled', [False, True])
def test_irrelevant_outbound_packet_reads_only_packet_id(cancelled):
    plugin = make_plugin(perf=True)
    player = CountingPlayer()
    event = PacketEvent(19, player=player, payload=b'x' * 200)  # MovePlayer-like traffic
    event.is_cancelled = cancelled
    plugin.on_packet_send(event)
    assert event.packet_id_reads == 1
    assert event.cancellation_reads == 0
    assert event.player_reads == 0
    assert event.payload_reads == 0
    assert player.runtime_reads == 0
    assert player.uuid_reads == 0
    assert player.inventory_reads == 0
    assert plugin._perf.send_fast_returns == 1
    assert plugin._perf.send_relevant == 0


def test_irrelevant_inbound_packet_never_touches_player_or_payload():
    plugin = make_plugin()
    player = CountingPlayer()
    event = PacketEvent(1, player=player, payload=b'x' * 200)
    plugin.on_packet_receive(event)
    assert event.player_reads == 0
    assert event.payload_reads == 0
    assert player.runtime_reads == 0
    assert player.uuid_reads == 0
    assert player.inventory_reads == 0


def test_player_auth_input_without_any_active_session_stops_before_player():
    plugin = make_plugin()
    player = CountingPlayer()
    event = PacketEvent(PACKET_PLAYER_AUTH_INPUT, player=player, payload=auth_input_payload(stack_request=True))
    plugin.on_packet_receive(event)
    assert event.player_reads == 0
    assert event.payload_reads == 0
    assert player.runtime_reads == 0
    assert player.uuid_reads == 0


def test_inventory_sync_without_any_active_session_stops_before_player():
    plugin = make_plugin()
    player = CountingPlayer()
    event = PacketEvent(PACKET_INVENTORY_CONTENT, player=player, payload=b'\x05minecraft:bundle')
    plugin.on_packet_send(event)
    assert event.player_reads == 0
    assert event.payload_reads == 0
    assert player.uuid_reads == 0


def test_runtime_id_cache_constructs_uuid_only_once():
    plugin = make_plugin(perf=True)
    player = CountingPlayer(runtime_id=42, unique_id=UUID('00000000-0000-0000-0000-000000000042'))

    assert plugin._player_key(player) == 42
    assert plugin._player_key(player) == 42
    assert player.uuid_reads == 1
    assert plugin._perf.uuid_constructs == 1
    assert plugin._perf.uuid_to_str == 0
    assert plugin._perf.player_cache_misses == 1
    assert plugin._perf.player_cache_hits == 1


def test_158_cow_style_motion_storm_does_zero_identity_work():
    plugin = make_plugin()
    player = CountingPlayer(runtime_id=99)
    # 158 entities * 20 ticks = 3160 representative outbound movement packets.
    for _ in range(158 * 20):
        plugin.on_packet_send(PacketEvent(19, player=player, payload=b'motion'))
    assert player.runtime_reads == 0
    assert player.uuid_reads == 0
    assert player.inventory_reads == 0
    assert not plugin._players


def test_container_open_uses_cached_runtime_identity_and_creates_session():
    plugin = make_plugin()
    player = CountingPlayer(runtime_id=7)
    key = plugin._player_key(player)
    assert player.uuid_reads == 1
    plugin._candidates[key] = ContainerCandidate(
        kind='block', target_type='minecraft:hopper', dimension='Overworld',
        x=1, y=2, z=3, created_at=0.0,
    )
    # Avoid timeout by setting created_at near monotonic in test.
    import time
    plugin._candidates[key].created_at = time.monotonic()
    event = PacketEvent(PACKET_CONTAINER_OPEN, player=player, payload=bytes([5]))
    plugin.on_packet_send(event)
    assert key in plugin._sessions
    assert plugin._sessions[key].container_id == 5
    assert player.uuid_reads == 1
