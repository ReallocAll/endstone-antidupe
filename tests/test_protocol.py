from endstone_antidupe.constants import PACKET_INVENTORY_CONTENT, PACKET_INVENTORY_SLOT
from endstone_antidupe.protocol import (
    container_open_id,
    inventory_sync_container_id,
    player_auth_input_has_stack_request,
)
from .helpers import auth_input_payload


def test_player_auth_input_stack_request_flag():
    assert not player_auth_input_has_stack_request(auth_input_payload(stack_request=False))
    assert player_auth_input_has_stack_request(auth_input_payload(stack_request=True))


def test_container_ids():
    assert container_open_id(bytes([5])) == 5
    assert container_open_id(bytes([255])) == -1
    assert inventory_sync_container_id(PACKET_INVENTORY_CONTENT, bytes([5])) == 5
    assert inventory_sync_container_id(PACKET_INVENTORY_SLOT, bytes([5])) == 5
