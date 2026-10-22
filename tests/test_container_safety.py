import time
from types import SimpleNamespace

import pytest

from endstone_antidupe.constants import (
    PACKET_CONTAINER_CLOSE,
    PACKET_INVENTORY_CONTENT,
    PACKET_INVENTORY_TRANSACTION,
    PACKET_PLAYER_AUTH_INPUT,
)
from .helpers import CountingPlayer, FakeItem, PacketEvent, auth_input_2193, make_plugin
from .test_regression import safe_session


def opened():
    plugin = make_plugin()
    player = CountingPlayer()
    key = plugin._player_key(player)
    plugin._sessions[key] = safe_session()
    return plugin, player, key


def test_ordinary_metadata_is_not_typed_bundle_evidence_or_destructive_authority():
    plugin, player, key = opened()
    plugin.on_packet_send(PacketEvent(
        PACKET_INVENTORY_CONTENT, player, b'\x05ordinary item name: bundle of joy'))
    session = plugin._sessions[key]
    assert session.inventory_unverified and not session.contaminated
    assert plugin._stats.contaminated_sessions == 0
    assert plugin.server.scheduler.tasks == []
    assert plugin._stats.rebuilt_containers == 0
    event = PacketEvent(PACKET_INVENTORY_TRANSACTION, player)
    plugin.on_packet_receive(event)
    assert event.is_cancelled  # Suspicion can quarantine, never destroy.


@pytest.mark.parametrize('payload', [auth_input_2193([36]),
                                    auth_input_2193([], b'\x00\x01\x00'),
                                    b'\x00' * 32, auth_input_2193([34])])
def test_shared_2193_mutation_or_malformed_inspector(payload):
    plugin, player, key = opened()
    plugin._sessions[key].inventory_unverified = True
    event = PacketEvent(PACKET_PLAYER_AUTH_INPUT, player, payload)
    plugin.on_packet_receive(event)
    assert event.is_cancelled


def test_unknown_protocol_does_not_claim_movement_is_safe():
    plugin, player, key = opened()
    plugin.server.protocol_version = 9999
    plugin._sessions[key].inventory_unverified = True
    event = PacketEvent(PACKET_PLAYER_AUTH_INPUT, player, auth_input_2193())
    plugin.on_packet_receive(event)
    assert event.is_cancelled


def test_idle_open_window_remains_guarded():
    plugin, player, key = opened()
    player._inventory = [FakeItem('minecraft:bundle')]
    plugin._sessions[key].last_activity = time.monotonic() - 10000
    plugin._cleanup_expired()
    event = PacketEvent(PACKET_INVENTORY_TRANSACTION, player)
    plugin.on_packet_receive(event)
    assert event.is_cancelled


def test_reload_retains_window_suspicion_until_matching_server_close():
    plugin, player, key = opened()
    plugin.server.online_players = [player]
    plugin.on_packet_send(PacketEvent(PACKET_INVENTORY_CONTENT, player, b'\x05bundle'))
    plugin._load_settings_with_log = lambda: plugin._settings
    sender = SimpleNamespace(send_message=lambda _: None)
    plugin.on_command(sender, SimpleNamespace(name='antidupe'), ['reload'])
    assert key in plugin._sessions and plugin._quarantined_blocks
    plugin.on_packet_receive(PacketEvent(PACKET_CONTAINER_CLOSE, player, b'\x05'))
    plugin.on_packet_send(PacketEvent(PACKET_CONTAINER_CLOSE, player, b'\x06'))
    assert key in plugin._sessions and plugin._quarantined_blocks
    plugin.on_packet_send(PacketEvent(PACKET_CONTAINER_CLOSE, player, b'\x05'))
    assert key not in plugin._sessions and not plugin._quarantined_blocks


def test_shared_location_quarantine_lasts_until_last_viewer_closes():
    plugin, player, key = opened()
    other = CountingPlayer(runtime_id=2)
    other_key = plugin._player_key(other)
    plugin._sessions[other_key] = safe_session()
    plugin.on_packet_send(PacketEvent(PACKET_INVENTORY_CONTENT, player, b'\x05bundle'))
    plugin._clear_session_state(key)
    assert plugin._quarantined_blocks
    event = PacketEvent(PACKET_INVENTORY_TRANSACTION, other)
    plugin.on_packet_receive(event)
    assert event.is_cancelled
    plugin._clear_session_state(other_key)
    assert not plugin._quarantined_blocks


def test_unknown_player_inventory_fails_closed():
    class UnreadablePlayer(CountingPlayer):
        @property
        def inventory(self):
            raise RuntimeError('unavailable')
    plugin = make_plugin()
    player = UnreadablePlayer()
    key = plugin._player_key(player)
    plugin._sessions[key] = safe_session()
    event = PacketEvent(PACKET_INVENTORY_TRANSACTION, player)
    plugin.on_packet_receive(event)
    assert event.is_cancelled
