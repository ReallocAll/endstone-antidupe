from __future__ import annotations

PACKET_INVENTORY_TRANSACTION = 30
PACKET_CONTAINER_OPEN = 46
PACKET_CONTAINER_CLOSE = 47
PACKET_INVENTORY_CONTENT = 49
PACKET_INVENTORY_SLOT = 50
PACKET_PLAYER_AUTH_INPUT = 144
PACKET_ITEM_STACK_REQUEST = 147

INPUT_PERFORM_ITEM_INTERACTION = 34
INPUT_PERFORM_ITEM_STACK_REQUEST = 36

RESTRICTED_BLOCK_CONTAINERS: frozenset[str] = frozenset({
    "minecraft:hopper",
    "minecraft:dropper",
    "minecraft:dispenser",
    "minecraft:furnace",
    "minecraft:blast_furnace",
    "minecraft:smoker",
    "minecraft:brewing_stand",
    "minecraft:crafter",
})

DEFAULT_REBUILD_CONTAINER_TYPES: tuple[str, ...] = ("minecraft:hopper",)

RESTRICTED_ENTITY_CONTAINERS: frozenset[str] = frozenset({
    "minecraft:hopper_minecart",
})

DIRECT_TRANSACTION_PACKET_IDS: frozenset[int] = frozenset({
    PACKET_INVENTORY_TRANSACTION,
    PACKET_ITEM_STACK_REQUEST,
})

INVENTORY_SYNC_PACKET_IDS: frozenset[int] = frozenset({
    PACKET_INVENTORY_CONTENT,
    PACKET_INVENTORY_SLOT,
})

# These are the only outbound packet types AntiDupe needs. Everything else,
# including ordinary actor-motion packets, returns before event.player/payload.
SEND_RELEVANT_PACKET_IDS: frozenset[int] = frozenset({
    PACKET_CONTAINER_OPEN,
    PACKET_CONTAINER_CLOSE,
    PACKET_INVENTORY_CONTENT,
    PACKET_INVENTORY_SLOT,
})

# These are the only inbound packet types AntiDupe needs.
RECEIVE_RELEVANT_PACKET_IDS: frozenset[int] = frozenset({
    PACKET_INVENTORY_TRANSACTION,
    PACKET_CONTAINER_CLOSE,
    PACKET_PLAYER_AUTH_INPUT,
    PACKET_ITEM_STACK_REQUEST,
})


def is_bundle_type(type_id: str) -> bool:
    value = (type_id or "").strip().lower()
    return value == "minecraft:bundle" or (
        value.startswith("minecraft:") and value.endswith("_bundle")
    )
