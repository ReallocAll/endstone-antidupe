import sys
import types


def _event_handler(func=None, *, priority=None, ignore_cancelled=False):
    def deco(f):
        f._is_event_handler = True
        f._priority = priority
        f._ignore_cancelled = ignore_cancelled
        return f
    return deco(func) if func is not None else deco


endstone = types.ModuleType('endstone')
command = types.ModuleType('endstone.command')
event = types.ModuleType('endstone.event')
plugin = types.ModuleType('endstone.plugin')


class Command: ...
class CommandSender: ...


class _BaseEvent: ...
class PacketReceiveEvent(_BaseEvent): ...
class PacketSendEvent(_BaseEvent): ...
class PlayerDimensionChangeEvent(_BaseEvent): ...
class PlayerInteractActorEvent(_BaseEvent): ...
class PlayerJoinEvent(_BaseEvent): ...
class PlayerQuitEvent(_BaseEvent): ...
class PlayerKickEvent(_BaseEvent): ...
class EventPriority:
    HIGHEST = 4


class PlayerInteractEvent(_BaseEvent):
    RIGHT_CLICK_BLOCK = 1


class Plugin:
    pass


command.Command = Command
command.CommandSender = CommandSender
for cls in [
    PacketReceiveEvent,
    PacketSendEvent,
    PlayerDimensionChangeEvent,
    PlayerInteractActorEvent,
    PlayerInteractEvent,
    PlayerJoinEvent,
    PlayerQuitEvent,
    PlayerKickEvent,
    EventPriority,
]:
    setattr(event, cls.__name__, cls)
event.event_handler = _event_handler
plugin.Plugin = Plugin

sys.modules.setdefault('endstone', endstone)
sys.modules.setdefault('endstone.command', command)
sys.modules.setdefault('endstone.event', event)
sys.modules.setdefault('endstone.plugin', plugin)
