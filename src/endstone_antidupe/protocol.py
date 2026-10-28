from __future__ import annotations

from .constants import (
    PACKET_INVENTORY_CONTENT,
    PACKET_INVENTORY_SLOT,
    TRANSFER_MUTATION_FLAGS,
    TRANSFER_PLAYER_ACTIONS,
)

_VARUINT32_MAX_BYTES = 5


def _strict_varuint(data: bytes, offset: int, bits: int) -> tuple[int, int]:
    """Bounded, canonical integers for the protocol-2193/2225 transfer guard only."""
    value = 0
    for shift in range(0, bits, 7):
        if offset >= len(data):
            raise ValueError("truncated integer")
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if value >= 1 << bits:
            raise ValueError("integer overflow")
        if not byte & 128:
            if shift and byte == 0:
                raise ValueError("overlong integer")
            return value, offset
    raise ValueError("unterminated integer")


def _strict_varint(data: bytes, offset: int, bits: int = 32) -> tuple[int, int]:
    value, offset = _strict_varuint(data, offset, bits)
    return (value >> 1) ^ -(value & 1), offset


def change_dimension_target(payload: bytes) -> int | None:
    try:
        target, offset = _strict_varint(payload, 0)
        offset += 12  # destination position
        if len(payload) < offset + 2 or payload[offset] not in (0, 1) or payload[offset + 1] not in (0, 1):
            return None
        expected = offset + 2 + (4 if payload[offset + 1] else 0)
        if len(payload) != expected:
            return None
        return target
    except ValueError:
        return None


def transfer_terrain_packet_allowed(packet_id: int, payload: bytes) -> bool:
    try:
        if packet_id == 69:
            _, offset = _strict_varint(payload, 0)
            return offset + 1 == len(payload)
        if packet_id == 135:
            missing_count, offset = _strict_varuint(payload, 0, 32)
            if missing_count > (len(payload) - offset) // 8:
                return False
            offset += missing_count * 8
            found_count, offset = _strict_varuint(payload, offset, 32)
            if found_count > (len(payload) - offset) // 8:
                return False
            return offset + found_count * 8 == len(payload)
        if packet_id == 175:
            _, offset = _strict_varint(payload, 0)
            count, offset = _strict_varuint(payload, offset, 32)
            if count > (len(payload) - offset - 12) // 3:
                return False
            return offset + count * 3 + 12 == len(payload)
        return False
    except ValueError:
        return False


def transfer_loading_screen_allowed(payload: bytes) -> bool:
    try:
        packet_type, offset = _strict_varint(payload, 0)
        if packet_type not in (1, 2):
            return False
        if offset >= len(payload) or payload[offset] not in (0, 1):
            return False
        return len(payload) == offset + 1 + (4 if payload[offset] else 0)
    except ValueError:
        return False


def transfer_player_action_allowed(payload: bytes) -> bool:
    try:
        _, offset = _strict_varuint(payload, 0, 64)
        action, offset = _strict_varint(payload, offset)
        if action not in TRANSFER_PLAYER_ACTIONS:
            return False
        for _ in range(7):  # two BlockPos (six signed coordinates), then face
            _, offset = _strict_varint(payload, offset)
        return offset == len(payload)
    except ValueError:
        return False


def transfer_auth_input_allowed(payload: bytes) -> bool:
    """Prove all three independent mutation optionals absent in protocols 2193 and 2225.

    The flags are an enum list, not a legacy bitset.
    Movement, including zero displacement, is never evidence of completion.
    """
    try:
        count, offset = _strict_varuint(payload, 32, 32)
        if count > 66:
            return False
        for _ in range(count):
            flag, offset = _strict_varint(payload, offset)
            if not 0 <= flag < 66 or flag in TRANSFER_MUTATION_FLAGS:
                return False
        _, offset = _strict_varuint(payload, offset, 32)  # input mode
        _, offset = _strict_varuint(payload, offset, 32)  # play mode
        _, offset = _strict_varint(payload, offset)  # interaction model
        offset += 8  # interact rotation
        _, offset = _strict_varuint(payload, offset, 64)  # client tick
        offset += 12  # position delta
        # Presence is independent of flags. A present or invalid boolean denies
        # immediately, without parsing any attacker-controlled action body.
        for _ in range(3):
            if offset >= len(payload) or payload[offset] != 0:
                return False
            offset += 1
        if offset >= len(payload) or payload[offset] not in (0, 1):
            return False
        has_vehicle_rotation = payload[offset]
        offset += 1 + (8 if has_vehicle_rotation else 0)
        if offset >= len(payload) or payload[offset] not in (0, 1):
            return False
        has_predicted_vehicle = payload[offset]
        offset += 1
        if has_predicted_vehicle:
            _, offset = _strict_varint(payload, offset, 64)
        # Analog movement, camera orientation, raw movement: Vec2 + Vec3 + Vec2.
        return offset + 28 == len(payload)
    except ValueError:
        return False


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


def container_open_id(payload: bytes) -> int | None:
    """Parse ContainerOpen.container_id for Bedrock protocol >= 1.26.14.

    ContainerID is serialized as int8 in ContainerOpen.
    """
    if not payload:
        return None
    return _read_int8(payload[0])


def inventory_sync_container_id(packet_id: int, payload: bytes) -> int | None:
    """Return the target container id for InventoryContent/InventorySlot.

    On protocols 2193 and 2225 (Bedrock 1.26.50/1.26.60):
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
