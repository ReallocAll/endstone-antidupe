from __future__ import annotations

from .constants import (
    INPUT_PERFORM_ITEM_STACK_REQUEST,
    PACKET_INVENTORY_CONTENT,
    PACKET_INVENTORY_SLOT,
)

PLAYER_AUTH_INPUT_FLAGS_OFFSET = 32
_VARINT128_MAX_BYTES = 19
_VARUINT32_MAX_BYTES = 5


def _read_varuint(data: bytes, offset: int, max_bytes: int) -> tuple[int, int] | None:
    value = 0
    shift = 0
    end = min(len(data), offset + max_bytes)
    for index in range(offset, end):
        byte = data[index]
        value |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            return value, index + 1
        shift += 7
        if shift >= max_bytes * 7:
            return None
    return None


def _read_int8(value: int) -> int:
    return value - 256 if value >= 128 else value


def player_auth_input_flags(payload: bytes) -> int | None:
    if len(payload) <= PLAYER_AUTH_INPUT_FLAGS_OFFSET:
        return None
    parsed = _read_varuint(payload, PLAYER_AUTH_INPUT_FLAGS_OFFSET, _VARINT128_MAX_BYTES)
    if parsed is None:
        return None
    return parsed[0]


def player_auth_input_has_stack_request(payload: bytes) -> bool:
    flags = player_auth_input_flags(payload)
    if flags is None:
        return False
    return bool(flags & (1 << INPUT_PERFORM_ITEM_STACK_REQUEST))


def container_open_id(payload: bytes) -> int | None:
    """Parse ContainerOpen.container_id for Bedrock protocol >= 1.26.14.

    ContainerID is serialized as int8 in ContainerOpen.
    """
    if not payload:
        return None
    return _read_int8(payload[0])


def inventory_sync_container_id(packet_id: int, payload: bytes) -> int | None:
    """Return the target container id for InventoryContent/InventorySlot.

    On protocol 2193 (Bedrock 1.26.50/1.26.51):
      * InventoryContent(49): ContainerID is encoded as uvarint32.
      * InventorySlot(50): ContainerID is encoded as int8.
    """
    if not payload:
        return None

    if packet_id == PACKET_INVENTORY_CONTENT:
        parsed = _read_varuint(payload, 0, _VARUINT32_MAX_BYTES)
        return parsed[0] if parsed is not None else None

    if packet_id == PACKET_INVENTORY_SLOT:
        return _read_int8(payload[0])

    return None
