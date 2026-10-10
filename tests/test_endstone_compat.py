import inspect

from endstone.event import (
    PacketReceiveEvent,
    PacketSendEvent,
    PlayerDimensionChangeEvent,
    PlayerInteractActorEvent,
    PlayerInteractEvent,
    PlayerJoinEvent,
    PlayerQuitEvent,
)
from endstone_antidupe.plugin import AntiDupe


def test_event_annotations_are_real_classes_not_strings():
    expected = {
        'on_packet_receive': PacketReceiveEvent,
        'on_packet_send': PacketSendEvent,
        'on_player_dimension_change': PlayerDimensionChangeEvent,
        'on_player_interact_actor': PlayerInteractActorEvent,
        'on_player_interact': PlayerInteractEvent,
        'on_player_join': PlayerJoinEvent,
        'on_player_quit': PlayerQuitEvent,
    }
    for name, cls in expected.items():
        fn = getattr(AntiDupe, name)
        annotation = inspect.signature(fn).parameters['event'].annotation
        assert annotation is cls
        assert inspect.isclass(annotation)
