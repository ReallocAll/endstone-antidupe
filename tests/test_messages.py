import json
from types import SimpleNamespace

import pytest

from endstone_antidupe.config import load_settings
from .helpers import CountingPlayer, FakeItem, make_plugin
from .test_transfer_guard import receive, start


def write_config(folder, values):
    path = folder / 'config.toml'
    text = '\n'.join(f'{key} = {json.dumps(value, ensure_ascii=False)}' for key, value in values.items())
    path.write_text(text, encoding='utf-8')
    return path, path.read_bytes()


def test_custom_chinese_bundle_message_is_preserved_and_delivered(tmp_path):
    message = '  §c[AntiDupe] 请先把收纳袋放入普通箱子。  '
    path, original = write_config(tmp_path, {'player-message': message})
    settings = load_settings(tmp_path)
    plugin = make_plugin(settings=settings)
    player = CountingPlayer(inventory=[FakeItem('minecraft:bundle')])
    block = SimpleNamespace(type='minecraft:hopper', dimension=SimpleNamespace(name='Overworld'), x=1, y=2, z=3)
    event = SimpleNamespace(action=1, has_block=True, block=block, player=player, is_cancelled=False)
    plugin.on_player_interact(event)
    assert event.is_cancelled
    assert settings.player_message == message
    assert player.messages == [message]
    assert path.read_bytes() == original


@pytest.mark.parametrize('key,expected', [
    ('player-message', '§c[AntiDupe] Bundles cannot interact with this container. '
     'Store the Bundle in a normal chest or barrel first.'),
    ('dimension-transfer-kick-message', '[AntiDupe] Dimension transfer did not complete safely. Please reconnect.'),
])
@pytest.mark.parametrize('values', [None, 42, True, [], '', '   ', '\t\n'])
def test_missing_or_invalid_message_uses_english_default(tmp_path, key, expected, values):
    path, original = write_config(tmp_path, {} if values is None else {key: values})
    settings = load_settings(tmp_path)
    assert getattr(settings, key.replace('-', '_')) == expected
    assert path.read_bytes() == original


def test_custom_chinese_transfer_kick_is_used_by_deferred_callback(tmp_path):
    message = '  [AntiDupe] 维度切换未安全完成，请重新连接。  '
    path, original = write_config(tmp_path, {'dimension-transfer-kick-message': message})
    plugin = make_plugin(settings=load_settings(tmp_path))
    player = CountingPlayer()
    plugin.server.online_players = [player]
    start(plugin, player)
    plugin.server.scheduler.run_next()  # Timeout quarantines immediately.
    assert not player.kicks
    plugin.server.scheduler.run_next()
    assert player.kicks == [message]
    assert path.read_bytes() == original


def test_reload_changes_pending_kick_message_without_releasing_quarantine(tmp_path):
    write_config(tmp_path, {'dimension-transfer-kick-message': 'Original message'})
    plugin = make_plugin(settings=load_settings(tmp_path))
    plugin.data_folder = str(tmp_path)
    player = CountingPlayer()
    plugin.server.online_players = [player]
    start(plugin, player)
    plugin.server.scheduler.run_next()
    token, record = plugin._players[1], plugin._transfers[1]
    message = '[AntiDupe] 请重新连接服务器。'
    path, original = write_config(tmp_path, {'dimension-transfer-kick-message': message})
    plugin.on_command(player, None, ['reload'])
    assert plugin._players[1] is token and plugin._transfers[1] is record
    assert receive(plugin, player, 999).is_cancelled
    plugin.server.scheduler.run_next()
    assert player.kicks == [message]
    assert receive(plugin, player, 30).is_cancelled
    assert path.read_bytes() == original
