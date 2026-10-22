import time
from types import SimpleNamespace
from uuid import UUID

from endstone_antidupe.constants import (
    PACKET_INVENTORY_CONTENT,
    PACKET_INVENTORY_TRANSACTION,
    PACKET_PLAYER_AUTH_INPUT,
)
from endstone_antidupe.state import ContainerCandidate, ContainerSession
from .helpers import CountingPlayer, FakeItem, PacketEvent, auth_input_payload, make_plugin


def safe_session(container_id=5):
    now = time.monotonic()
    return ContainerSession(
        kind='block', target_type='minecraft:hopper', dimension='Overworld',
        x=10, y=64, z=10, opened_at=now, last_activity=now,
        container_id=container_id,
    )


def test_normal_transaction_in_safe_session_is_not_cancelled():
    plugin = make_plugin()
    player = CountingPlayer(runtime_id=1, inventory=[FakeItem('minecraft:stone')])
    key = plugin._player_key(player)
    plugin._sessions[key] = safe_session()
    event = PacketEvent(PACKET_INVENTORY_TRANSACTION, player=player)
    plugin.on_packet_receive(event)
    assert not event.is_cancelled
    assert player.inventory_reads == 1


def test_bundle_holder_transaction_is_cancelled():
    plugin = make_plugin()
    player = CountingPlayer(runtime_id=1, inventory=[FakeItem('minecraft:bundle')])
    key = plugin._player_key(player)
    plugin._sessions[key] = safe_session()
    event = PacketEvent(PACKET_INVENTORY_TRANSACTION, player=player)
    plugin.on_packet_receive(event)
    assert event.is_cancelled
    assert plugin._stats.blocked_direct_transactions == 1


def test_contaminated_session_blocks_without_inventory_scan():
    plugin = make_plugin()
    player = CountingPlayer(runtime_id=1, inventory=[FakeItem('minecraft:stone')])
    key = plugin._player_key(player)
    s = safe_session()
    s.contaminated = True
    plugin._sessions[key] = s
    event = PacketEvent(PACKET_INVENTORY_TRANSACTION, player=player)
    plugin.on_packet_receive(event)
    assert event.is_cancelled
    assert player.inventory_reads == 0


def test_auth_input_without_embedded_request_does_not_scan_inventory():
    plugin = make_plugin()
    player = CountingPlayer(runtime_id=1, inventory=[FakeItem('minecraft:bundle')])
    key = plugin._player_key(player)
    plugin._sessions[key] = safe_session()
    event = PacketEvent(
        PACKET_PLAYER_AUTH_INPUT,
        player=player,
        payload=auth_input_payload(stack_request=False),
    )
    plugin.on_packet_receive(event)
    assert not event.is_cancelled
    assert player.inventory_reads == 0


def test_auth_input_embedded_request_is_blocked_when_unsafe():
    plugin = make_plugin()
    player = CountingPlayer(runtime_id=1, inventory=[FakeItem('minecraft:bundle')])
    key = plugin._player_key(player)
    plugin._sessions[key] = safe_session()
    event = PacketEvent(
        PACKET_PLAYER_AUTH_INPUT,
        player=player,
        payload=auth_input_payload(stack_request=True),
    )
    plugin.on_packet_receive(event)
    assert event.is_cancelled
    assert plugin._stats.blocked_auth_input_requests == 1


def test_inventory_sync_for_other_container_does_not_contaminate_target():
    plugin = make_plugin()
    player = CountingPlayer(runtime_id=1)
    key = plugin._player_key(player)
    plugin._sessions[key] = safe_session(container_id=5)
    event = PacketEvent(PACKET_INVENTORY_CONTENT, player=player, payload=b'\x00minecraft:bundle')
    plugin.on_packet_send(event)
    assert not plugin._sessions[key].contaminated
    assert not plugin._quarantined_blocks


def test_correlated_marker_quarantines_uncertainty_without_destructive_authority():
    plugin = make_plugin()
    player = CountingPlayer(runtime_id=1)
    key = plugin._player_key(player)
    plugin._sessions[key] = safe_session(container_id=5)
    event = PacketEvent(PACKET_INVENTORY_CONTENT, player=player, payload=b'\x05minecraft:bundle')
    plugin.on_packet_send(event)
    assert plugin._sessions[key].inventory_unverified
    assert not plugin._sessions[key].contaminated
    assert plugin._stats.contaminated_sessions == 0
    assert plugin.server.scheduler.tasks == []


def test_reconnect_runtime_id_reuse_clears_old_session():
    plugin = make_plugin()
    old = CountingPlayer(runtime_id=77, unique_id=UUID(int=1), name='old')
    key = plugin._register_player(old, reset_existing=True)
    plugin._sessions[key] = safe_session()
    plugin._candidates[key] = ContainerCandidate(
        kind='block', target_type='minecraft:hopper', dimension='Overworld',
        x=1, y=2, z=3, created_at=time.monotonic(),
    )

    new = CountingPlayer(runtime_id=77, unique_id=UUID(int=2), name='new')
    plugin._register_player(new, reset_existing=True)
    assert key not in plugin._sessions
    assert key not in plugin._candidates
    assert plugin._players[key].unique_id == UUID(int=2)


def test_multi_player_state_isolation():
    plugin = make_plugin()
    a = CountingPlayer(runtime_id=1)
    b = CountingPlayer(runtime_id=2)
    ka = plugin._player_key(a)
    kb = plugin._player_key(b)
    plugin._sessions[ka] = safe_session(container_id=5)
    plugin._sessions[kb] = safe_session(container_id=6)
    plugin._sessions[kb].x = 20

    event = PacketEvent(PACKET_INVENTORY_CONTENT, player=a, payload=b'\x05minecraft:bundle')
    plugin.on_packet_send(event)

    assert plugin._sessions[ka].inventory_unverified
    assert not plugin._sessions[kb].contaminated


def test_dimension_change_clears_transient_container_state_but_keeps_identity_cache():
    plugin = make_plugin()
    player = CountingPlayer(runtime_id=55)
    key = plugin._player_key(player)
    plugin._sessions[key] = safe_session()
    plugin._candidates[key] = ContainerCandidate(
        kind='block', target_type='minecraft:hopper', dimension='Overworld',
        x=1, y=2, z=3, created_at=time.monotonic(),
    )
    event = SimpleNamespace(player=player)
    plugin.on_player_dimension_change(event)
    assert key not in plugin._sessions
    assert key not in plugin._candidates
    assert key in plugin._players
