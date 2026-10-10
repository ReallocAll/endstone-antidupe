from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RebuildResult:
    status: str
    before_type: str
    after_type: str


def rebuild_block(
    dimension: Any,
    x: int,
    y: int,
    z: int,
    expected_type: str,
    saved_data: Any,
) -> RebuildResult:
    """Replace a block with air and restore the exact saved BlockData.

    The saved BlockData is a detached snapshot in Endstone 0.11, so this preserves
    block states such as hopper facing while discarding the old block entity.
    """
    block = dimension.get_block_at(x, y, z)
    before = str(block.type).lower()
    expected = expected_type.lower()
    if before != expected:
        return RebuildResult("changed", before, before)

    block.set_type("minecraft:air", apply_physics=False)
    replacement = dimension.get_block_at(x, y, z)
    replacement.set_data(saved_data, apply_physics=False)

    verify = dimension.get_block_at(x, y, z)
    after = str(verify.type).lower()
    return RebuildResult("rebuilt" if after == expected else "restore-mismatch", before, after)
