import inspect
from dataclasses import replace
from types import SimpleNamespace

import pytest
from endstone.event import EventPriority, PlayerKickEvent

from endstone_antidupe.config import Settings, load_settings
from endstone_antidupe.plugin import AntiDupe
from endstone_antidupe.state import ContainerCandidate
from .helpers import CountingPlayer, PacketEvent, auth_input_2193, encode_varuint, make_plugin
from .test_regression import safe_session


def dispatch(handler, event):
    """Model Endstone's cancellation filter around the real handler."""
    if not event.is_cancelled or not handler._ignore_cancelled:
        handler(event)


def start(plugin, player, target=1, payload=None):
    plugin.on_packet_send(PacketEvent(61, player, payload if payload is not None else
                                    encode_varuint((target << 1) ^ (target >> 31)) + bytes(14)))


def receive(plugin, player, packet_id, payload=b''):
    event = PacketEvent(packet_id, player, payload)
    plugin.on_packet_receive(event)
    return event


def complete(plugin, player, target=1):
    plugin.on_player_dimension_change(SimpleNamespace(
        player=player, to_dimension=SimpleNamespace(type=SimpleNamespace(value=target))))


@pytest.mark.parametrize('target', [0, 1, 2])
@pytest.mark.parametrize('log_attempts', [False, True])
def test_normal_transfer_and_routine_guard_drops_are_silent(target, log_attempts):
    plugin = make_plugin(settings=Settings(log_attempts=log_attempts))
    player = CountingPlayer(name='Alex')
    start(plugin, player, target)
    timeout = plugin.server.scheduler.tasks.pop()
    for _ in range(5):
        assert receive(plugin, player, 30).is_cancelled
    complete(plugin, player, target)
    assert plugin.server.scheduler.run_next() == 1
    timeout[0]()
    assert not plugin._transfers
    assert not receive(plugin, player, 30).is_cancelled
    assert plugin._stats.transfers_started == plugin._stats.transfers_completed == 1
    assert plugin._stats.transfers_quarantined == 0
    assert plugin._stats.transfer_packets_blocked == 5
    assert player.name_reads == 1
    assert not plugin.logger.messages


@pytest.mark.parametrize('packet_id', [30, 147, 47, 999])
def test_transfer_immediately_blocks_without_container(packet_id):
    plugin, player = make_plugin(), CountingPlayer()
    start(plugin, player)
    assert receive(plugin, player, packet_id).is_cancelled
    assert player.inventory_reads == 0
    assert player.uuid_reads == 1


@pytest.mark.parametrize('packet_id,payload', [
    (5, b''), (115, b''), (45, b''), (144, auth_input_2193()),
    *[(36, b'\x01' + encode_varuint(action * 2) + bytes(7)) for action in (7, 14, 30, 38)],
])
def test_waiting_allows_transition_and_plain_input_without_releasing(packet_id, payload):
    plugin, player = make_plugin(), CountingPlayer()
    start(plugin, player)
    assert not receive(plugin, player, packet_id, payload).is_cancelled
    assert receive(plugin, player, 30).is_cancelled


@pytest.mark.parametrize('payload', [
    *[auth_input_2193([flag]) for flag in (34, 35, 36, 53, 56, 66, -1)],
    *[auth_input_2193(optionals=bytes(i) + b'\x01') for i in range(3)],
    auth_input_2193(optionals=b'\x00\x02\x00'), b'', bytes(32) + b'\x80\x00',
    bytes(32) + b'\x43', bytes(32) + b'\xff\xff\xff\xff\x10',
    auth_input_2193()[:57],
])
def test_mutation_forged_flags_and_malformed_input_fail_closed(payload):
    plugin, player = make_plugin(), CountingPlayer()
    start(plugin, player)
    assert receive(plugin, player, 144, payload).is_cancelled


@pytest.mark.parametrize('payload', [b'', b'\x80' * 10, b'\x80\x00\x1c', b'\x01\x08',
                                     b'\x01\x80\x00', b'\xff' * 9 + b'\x02\x1c'])
def test_malformed_or_unsafe_player_action_denied(payload):
    plugin, player = make_plugin(), CountingPlayer()
    start(plugin, player)
    assert receive(plugin, player, 36, payload).is_cancelled


def test_completion_matches_target_and_releases_only_next_tick():
    plugin, player = make_plugin(), CountingPlayer()
    start(plugin, player, target=-1)
    timeout = plugin.server.scheduler.tasks.pop()
    complete(plugin, player, 1)
    assert not plugin.server.scheduler.tasks
    complete(plugin, player, -1)
    assert receive(plugin, player, 30).is_cancelled
    assert plugin.server.scheduler.run_next() == 1
    assert not receive(plugin, player, 30).is_cancelled
    timeout[0]()
    assert not plugin._transfers


def test_new_transfer_invalidates_old_release_and_timeout():
    plugin, player = make_plugin(), CountingPlayer()
    start(plugin, player)
    timeout = plugin.server.scheduler.tasks.pop()
    complete(plugin, player)
    release = plugin.server.scheduler.tasks.pop()
    start(plugin, player, target=2)
    timeout[0]()
    release[0]()
    assert receive(plugin, player, 30).is_cancelled
    assert not plugin._transfers[1].quarantined


@pytest.mark.parametrize('target,destination', [
    (0, 'Overworld'), (1, 'Nether'), (2, 'The End'), (-1, 'unknown dimension (ID -1)'),
])
def test_timeout_quarantines_then_defers_kick_and_retains_until_quit(target, destination):
    plugin, player = make_plugin(), CountingPlayer(name="Alex\n'Builder")
    plugin.server.online_players = [player]
    start(plugin, player, target)
    assert plugin.server.scheduler.run_next() == 200
    assert len(plugin.logger.messages) == 1
    level, message = plugin.logger.messages[0]
    assert level == 'warning'
    assert repr("Alex\n'Builder") in message and destination in message
    assert 'did not complete' in message and 'timeout' in message
    assert 'quarantined' in message and 'kick scheduled' in message
    assert 'target=' not in message and '\n' not in message
    assert not player.kicks
    event = receive(plugin, player, 999)
    assert event.is_cancelled and event.payload_reads == 0
    assert receive(plugin, player, 144, auth_input_2193()).is_cancelled
    complete(plugin, player, target)
    assert plugin.server.scheduler.run_next() == 1
    assert len(player.kicks) == 1
    plugin.server.scheduler.run_next()
    assert len(plugin.logger.messages) == 2
    level, message = plugin.logger.messages[-1]
    assert level == 'warning'
    assert repr("Alex\n'Builder") in message and destination in message
    assert 'still online after kick' in message and 'quarantine retained' in message
    assert receive(plugin, player, 30).is_cancelled
    assert len(plugin.logger.messages) == 2
    assert not plugin.server.scheduler.tasks
    assert player.name_reads == 1
    plugin.on_player_quit(SimpleNamespace(player=player))
    assert not plugin._transfers and not plugin._players


def test_kick_failure_warning_identifies_player_destination_and_retained_protection():
    plugin, player = make_plugin(), CountingPlayer(name='Alex')
    plugin.server.online_players = [player]

    def failed_kick(message):
        raise RuntimeError('disconnect unavailable')

    player.kick = failed_kick
    start(plugin, player)
    plugin.server.scheduler.run_next()
    plugin.server.scheduler.run_next()
    assert len(plugin.logger.messages) == 2
    level, message = plugin.logger.messages[-1]
    assert level == 'warning'
    assert "'Alex'" in message and 'Nether' in message
    assert 'kick failed' in message and 'disconnect unavailable' in message
    assert 'quarantine retained' in message
    plugin.server.scheduler.run_next()
    for _ in range(5):
        assert receive(plugin, player, 30).is_cancelled
    assert len(plugin.logger.messages) == 3
    assert not plugin.server.scheduler.tasks
    assert player.name_reads == 1


@pytest.mark.parametrize('quarantined', [False, True])
def test_reconnect_same_uuid_and_runtime_invalidates_callbacks(quarantined):
    plugin, old = make_plugin(), CountingPlayer()
    plugin.server.online_players = [old]
    start(plugin, old)
    if quarantined:
        plugin.server.scheduler.run_next()
    else:
        complete(plugin, old)
    callbacks = list(plugin.server.scheduler.tasks)
    plugin.server.scheduler.tasks.clear()
    new = CountingPlayer(runtime_id=old._runtime_id, unique_id=old._unique_id)
    plugin.server.online_players = [new]
    plugin.on_player_join(SimpleNamespace(player=new))
    start(plugin, new)
    for callback, _, _ in callbacks:
        callback()
    assert not new.kicks and not old.kicks
    assert receive(plugin, new, 30).is_cancelled
    assert not plugin._transfers[1].quarantined


def test_container_cleanup_and_reload_cannot_open_guard_gap():
    plugin, player = make_plugin(), CountingPlayer()
    plugin.server.online_players = [player]
    start(plugin, player)
    token = plugin._players[1]
    plugin._sessions[1] = safe_session()
    plugin._sessions[1].last_activity = 0
    plugin._cleanup_expired()
    plugin.on_packet_send(PacketEvent(47, player))
    plugin._load_settings_with_log = lambda: Settings(enabled=False, guard_dimension_transfer=False)
    plugin.on_command(player, None, ['reload'])
    assert plugin._players[1] is token
    assert receive(plugin, player, 30).is_cancelled
    complete(plugin, player)
    plugin.server.scheduler.tasks.pop()[0]()
    assert not receive(plugin, player, 30).is_cancelled


def test_reload_preserves_quarantine_and_reconciles_offline():
    plugin, player = make_plugin(), CountingPlayer()
    start(plugin, player)
    plugin.server.scheduler.run_next()
    plugin.server.online_players = [player]
    plugin._load_settings_with_log = lambda: Settings()
    plugin.on_command(player, None, ['reload'])
    assert receive(plugin, player, 999).is_cancelled
    plugin.server.online_players = []
    plugin.on_command(player, None, ['reload'])
    assert not plugin._transfers and not plugin._players


def test_multiplayer_and_unguarded_normal_drop_keep_fast_path():
    plugin, a, b = make_plugin(), CountingPlayer(), CountingPlayer(2)
    assert not receive(plugin, b, 30).is_cancelled
    start(plugin, a)
    event = receive(plugin, b, 999)
    assert not event.is_cancelled and event.payload_reads == 0
    assert b.uuid_reads == b.inventory_reads == 0
    assert receive(plugin, a, 30).is_cancelled


def test_quarantined_kick_cannot_be_cancelled_but_unrelated_kicks_unchanged():
    plugin, a, b = make_plugin(), CountingPlayer(), CountingPlayer(2)
    start(plugin, a)
    plugin.server.scheduler.run_next()
    for player, expected in [(a, False), (b, True)]:
        event = SimpleNamespace(player=player, is_cancelled=True)
        plugin.on_player_kick(event)
        assert event.is_cancelled is expected
    fn = AntiDupe.on_player_kick
    assert fn._priority == EventPriority.HIGHEST and not fn._ignore_cancelled
    assert inspect.signature(fn).parameters['event'].annotation is PlayerKickEvent


@pytest.mark.parametrize('payload', [b'', b'\x80\x00', b'\xff' * 5, b'\x02',
                                     b'\x02' + bytes(12) + b'\x02\x00',
                                     b'\x02' + bytes(13) + b'\x01'])
def test_malformed_start_quarantines(payload):
    plugin, player = make_plugin(), CountingPlayer(name='Alex')
    start(plugin, player, payload=payload)
    assert receive(plugin, player, 144, auth_input_2193()).is_cancelled
    assert len(plugin.logger.messages) == 1
    level, message = plugin.logger.messages[0]
    assert level == 'warning'
    assert "'Alex'" in message and 'unknown destination' in message
    assert 'malformed ChangeDimension' in message
    assert 'quarantined' in message and 'kick scheduled' in message
    assert player.name_reads == 1


@pytest.mark.parametrize('protocol,enabled', [(2193, True), (2168, False)])
def test_enable_existing_online_requires_fresh_connection(protocol, enabled):
    plugin, player = make_plugin(), CountingPlayer(name='Alex')
    plugin.server.protocol_version = protocol
    plugin.server.online_players = [player]
    plugin.register_events = lambda _: None
    plugin._load_settings_with_log = lambda: Settings()
    plugin.on_enable()
    assert receive(plugin, player, 30).is_cancelled is enabled
    if enabled:
        warnings = [msg for level, msg in plugin.logger.messages if level == 'warning']
        assert len(warnings) == 1
        assert "'Alex'" in warnings[0] and 'unknown destination' in warnings[0]
        assert 'already connected' in warnings[0] and 'cannot be verified' in warnings[0]
        assert 'quarantined' in warnings[0] and 'kick scheduled' in warnings[0]
    else:
        start(plugin, player)
        assert not plugin._transfers
        assert any('2193' in msg and '2168' in msg for _, msg in plugin.logger.messages)
    callbacks = list(plugin.server.scheduler.tasks)
    plugin.on_disable()
    assert not plugin.server.scheduler.tasks
    for callback, _, period in callbacks:
        if not period:
            callback()
    assert not player.kicks


def test_config_defaults_clamps_and_preserves_file(tmp_path):
    settings = load_settings(tmp_path)
    assert settings.guard_dimension_transfer and settings.dimension_transfer_timeout_seconds == 10
    path = tmp_path / 'config.toml'
    for value, expected in [(0, 1), (999, 120)]:
        raw = f'guard-dimension-transfer = false\ndimension-transfer-timeout-seconds = {value}\n'
        path.write_text(raw)
        settings = load_settings(tmp_path)
        assert not settings.guard_dimension_transfer and settings.dimension_transfer_timeout_seconds == expected
        assert path.read_text() == raw


def test_configured_timeout_and_status_counters():
    plugin, player = make_plugin(), CountingPlayer()
    plugin._settings = replace(plugin._settings, dimension_transfer_timeout_seconds=1.25)
    start(plugin, player)
    assert plugin.server.scheduler.tasks[0][1] == 25
    receive(plugin, player, 30)
    plugin.on_command(player, None, ['status'])
    assert any('transfer' in msg.lower() for msg in player.messages)


def test_fresh_join_does_not_arm_and_quarantine_cannot_be_replaced_by_new_start():
    plugin, player = make_plugin(), CountingPlayer()
    plugin.on_player_join(SimpleNamespace(player=player))
    assert not receive(plugin, player, 30).is_cancelled
    start(plugin, player)
    plugin.server.scheduler.run_next()
    queued = len(plugin.server.scheduler.tasks)
    start(plugin, player, target=2)
    complete(plugin, player, target=2)
    assert receive(plugin, player, 115).is_cancelled
    assert len(plugin.server.scheduler.tasks) == queued


def test_deferred_kick_requires_cached_uuid_and_guard_drops_are_silent():
    plugin, player = make_plugin(), CountingPlayer()
    start(plugin, player)
    for _ in range(5):
        receive(plugin, player, 30)
    assert not plugin.logger.messages
    assert plugin._stats.transfer_packets_blocked == 5
    plugin.server.scheduler.run_next()
    impostor = CountingPlayer(runtime_id=1, unique_id=CountingPlayer(2)._unique_id)
    plugin.server.online_players = [impostor]
    plugin.server.scheduler.run_next()
    assert not impostor.kicks


def test_disabled_guard_does_not_arm_on_outbound_change():
    plugin, player = make_plugin(), CountingPlayer()
    plugin._settings = replace(plugin._settings, guard_dimension_transfer=False)
    plugin._configure_transfer_guard()
    start(plugin, player)
    assert not receive(plugin, player, 30).is_cancelled


@pytest.mark.parametrize('payload', [
    b'\x01\x1c', b'\x01\x1c' + bytes(6), b'\x01\x1c' + bytes(8),
    b'\x01\x1c' + bytes(6) + b'\x80\x00',
    b'\x01\x1c' + bytes(6) + b'\xff\xff\xff\xff\x10',
])
def test_player_action_requires_complete_canonical_frame(payload):
    plugin, player = make_plugin(), CountingPlayer()
    start(plugin, player)
    assert receive(plugin, player, 36, payload).is_cancelled


@pytest.mark.parametrize('tail', [
    b'', b'\x00', b'\x00\x00' + bytes(27), b'\x00\x00' + bytes(29),
    b'\x02\x00' + bytes(28), b'\x00\x02' + bytes(28),
    b'\x01' + bytes(7), b'\x00\x01',
    b'\x00\x01\x80\x00' + bytes(28),
    b'\x00\x01' + b'\xff' * 9 + b'\x02' + bytes(28),
])
def test_auth_input_requires_complete_canonical_tail(tail):
    plugin, player = make_plugin(), CountingPlayer()
    start(plugin, player)
    # Drop the two absent vehicle optionals and the three final vectors.
    payload = auth_input_2193()[:-30] + tail
    assert receive(plugin, player, 144, payload).is_cancelled


@pytest.mark.parametrize('rotation,vehicle_id', [
    (b'\x00', b'\x00'), (b'\x01' + bytes(8), b'\x00'),
    (b'\x00', b'\x01' + encode_varuint((1 << 64) - 1)),
    (b'\x01' + bytes(8), b'\x01\x02'),
])
def test_auth_input_allows_complete_vehicle_optional_combinations(rotation, vehicle_id):
    plugin, player = make_plugin(), CountingPlayer()
    start(plugin, player)
    payload = auth_input_2193()[:-30] + rotation + vehicle_id + bytes(28)
    assert not receive(plugin, player, 144, payload).is_cancelled
    assert receive(plugin, player, 30).is_cancelled


def test_cancelled_dimension_send_still_arms_guard_through_dispatch():
    plugin, player = make_plugin(), CountingPlayer()
    event = PacketEvent(61, player, b'\x02' + bytes(14))
    event.is_cancelled = True  # An earlier listener cancelled network delivery.
    dispatch(plugin.on_packet_send, event)
    assert event.is_cancelled
    assert receive(plugin, player, 30).is_cancelled


@pytest.mark.parametrize('packet_id,payload', [
    (46, b'\x05'), (47, b''), (49, b'\x05minecraft:bundle'), (50, b'\x05minecraft:bundle'),
])
def test_cancelled_container_send_does_nothing_through_dispatch(packet_id, payload):
    plugin, player = make_plugin(), CountingPlayer()
    key = plugin._player_key(player)
    session = safe_session()
    plugin._sessions[key] = session
    candidate = ContainerCandidate(
        kind=session.kind, target_type=session.target_type, dimension=session.dimension,
        x=session.x, y=session.y, z=session.z, created_at=session.opened_at,
    )
    plugin._candidates[key] = candidate
    event = PacketEvent(packet_id, player, payload)
    event.is_cancelled = True
    dispatch(plugin.on_packet_send, event)
    assert plugin._sessions[key] is session
    assert plugin._candidates[key] is candidate
    assert not session.contaminated
    assert event.player_reads == event.payload_reads == 0


@pytest.mark.parametrize('payload', [
    bytes.fromhex('02 01 09 00 00 00'), bytes.fromhex('04 00'),
    bytes.fromhex('02 00'), bytes.fromhex('04 01 ff ff ff ff'),
])
def test_loading_screen_waiting_allows_without_completion_or_deadline_refresh(payload):
    plugin, player = make_plugin(perf=True), CountingPlayer()
    start(plugin, player)
    record = plugin._transfers[1]
    original = replace(record)
    tasks = list(plugin.server.scheduler.tasks)
    reads = plugin._perf.payload_reads
    event = receive(plugin, player, 312, payload)
    assert not event.is_cancelled
    assert event.payload_reads == 1
    assert plugin._perf.payload_reads == reads + 1
    assert plugin._transfers[1] is record and record == original
    assert plugin.server.scheduler.tasks == tasks
    assert receive(plugin, player, 30).is_cancelled
    assert plugin.server.scheduler.run_next() == 200
    assert record.quarantined


@pytest.mark.parametrize('payload', [
    b'', bytes.fromhex('00 00'), bytes.fromhex('06 00'), bytes.fromhex('01 00'),
    bytes.fromhex('80'), bytes.fromhex('82 00 00'), bytes.fromhex('ff ff ff ff 10 00'),
    bytes.fromhex('80 80 80 80 80 00'), bytes.fromhex('02'), bytes.fromhex('02 02'),
    bytes.fromhex('02 01'), bytes.fromhex('02 01 09 00 00'),
    bytes.fromhex('04 00 00'), bytes.fromhex('02 01 09 00 00 00 00'),
])
def test_loading_screen_malformed_denied(payload):
    plugin, player = make_plugin(), CountingPlayer()
    start(plugin, player)
    assert receive(plugin, player, 312, payload).is_cancelled


def test_loading_screen_quarantine_denies_without_payload_read():
    plugin, player = make_plugin(perf=True), CountingPlayer()
    start(plugin, player)
    plugin.server.scheduler.run_next()
    reads = plugin._perf.payload_reads
    event = receive(plugin, player, 312, bytes.fromhex('02 01 09 00 00 00'))
    assert event.is_cancelled and event.payload_reads == 0
    assert plugin._perf.payload_reads == reads


def test_loading_screen_without_guard_keeps_field_free_hot_path():
    plugin, player = make_plugin(perf=True), CountingPlayer()
    event = receive(plugin, player, 312, bytes.fromhex('04 00'))
    assert not event.is_cancelled
    assert event.player_reads == event.payload_reads == 0
    assert player.runtime_reads == player.uuid_reads == player.inventory_reads == 0
    assert plugin._perf.payload_reads == 0


TERRAIN_GOLDENS = [
    (69, bytes.fromhex('18 c8')),
    (135, bytes.fromhex('02 01 00 00 00 00 00 00 00 02 00 00 00 00 00 00 00 01 03 00 00 00 00 00 00 00')),
    (175, bytes.fromhex('00 01 ff 00 01 01 00 00 00 02 00 00 00 03 00 00 00')),
]


@pytest.mark.parametrize('packet_id,payload', TERRAIN_GOLDENS + [
    (69, bytes.fromhex('01 ff')), (135, bytes(2)), (175, bytes(14)),
    (135, encode_varuint(1024) + bytes(8192) + encode_varuint(1024) + bytes(8192)),
    (175, b'\x00' + encode_varuint(1024) + bytes(3072 + 12)),
], ids=['radius', 'cache', 'subchunk', 'negative-radius', 'empty-cache', 'empty-subchunk',
        'large-cache', 'large-subchunk'])
def test_terrain_waiting_allows_without_completion_or_deadline_refresh(packet_id, payload):
    plugin, player = make_plugin(perf=True), CountingPlayer()
    start(plugin, player)
    record = plugin._transfers[1]
    original = replace(record)
    tasks = list(plugin.server.scheduler.tasks)
    reads = plugin._perf.payload_reads
    event = receive(plugin, player, packet_id, payload)
    assert not event.is_cancelled
    assert event.payload_reads == 1 and plugin._perf.payload_reads == reads + 1
    assert plugin._transfers[1] is record and record == original
    assert plugin.server.scheduler.tasks == tasks
    assert receive(plugin, player, 30).is_cancelled
    assert plugin.server.scheduler.run_next() == 200
    assert record.quarantined


@pytest.mark.parametrize('packet_id,payload', [
    *[(packet_id, payload[:i]) for packet_id, payload in TERRAIN_GOLDENS for i in range(len(payload))],
    *[(packet_id, payload + b'\x00') for packet_id, payload in TERRAIN_GOLDENS],
    *[(packet_id, bad) for packet_id in (69, 135, 175) for bad in (
        bytes.fromhex('80'), bytes.fromhex('80 00 00'),
        bytes.fromhex('ff ff ff ff 10 00'), bytes.fromhex('80 80 80 80 80 00'),
    )],
    (135, bytes.fromhex('ff ff ff ff 0f 00')),
    (135, bytes.fromhex('00 ff ff ff ff 0f')),
    (135, bytes.fromhex('00 80 00')), (135, bytes.fromhex('00 ff ff ff ff 10')),
    (135, bytes.fromhex('02 01 01 00 00 00 00 00 00 00 02 00 00 00 00 00 00 00 03 00 00 00 00 00 00 00')),
    (175, bytes.fromhex('00 ff ff ff ff 0f') + bytes(12)),
    (175, bytes.fromhex('00 ff ff ff ff 10') + bytes(12)),
    (175, bytes.fromhex('00 80 00') + bytes(12)),
    (175, bytes.fromhex('00 02 04 06 01 00 00 00 ff 00 01')),
])
def test_terrain_malformed_denied(packet_id, payload):
    plugin, player = make_plugin(), CountingPlayer()
    start(plugin, player)
    assert receive(plugin, player, packet_id, payload).is_cancelled


@pytest.mark.parametrize('packet_id,payload', TERRAIN_GOLDENS)
def test_terrain_quarantine_denies_without_payload_read(packet_id, payload):
    plugin, player = make_plugin(perf=True), CountingPlayer()
    start(plugin, player)
    plugin.server.scheduler.run_next()
    reads = plugin._perf.payload_reads
    event = receive(plugin, player, packet_id, payload)
    assert event.is_cancelled and event.payload_reads == 0
    assert plugin._perf.payload_reads == reads


@pytest.mark.parametrize('packet_id,payload', TERRAIN_GOLDENS)
def test_terrain_without_guard_keeps_field_free_hot_path(packet_id, payload):
    plugin, player = make_plugin(perf=True), CountingPlayer()
    event = receive(plugin, player, packet_id, payload)
    assert not event.is_cancelled
    assert event.player_reads == event.payload_reads == 0
    assert player.runtime_reads == player.uuid_reads == player.inventory_reads == 0
    assert plugin._perf.payload_reads == 0


def test_login_cache_status_remains_denied_while_waiting():
    plugin, player = make_plugin(), CountingPlayer()
    start(plugin, player)
    assert receive(plugin, player, 129, b'\x01').is_cancelled
