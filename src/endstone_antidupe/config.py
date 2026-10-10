from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .constants import DEFAULT_REBUILD_CONTAINER_TYPES
import tomllib

DEFAULT_PLAYER_MESSAGE = (
    "§c[AntiDupe] 收纳袋不能与该类容器进行库存交互。"
    "请先将收纳袋存入普通箱子/木桶。"
)

DEFAULT_CONFIG = '''# antidupe 0.2.3
# Bundle / high-risk-container protection.

enabled = true
alert-ops = true
log-attempts = true
player-message = "§c[AntiDupe] 收纳袋不能与该类容器进行库存交互。请先将收纳袋存入普通箱子/木桶。"

block-open-with-bundle = true
guard-player-auth-input = true
quarantine-contaminated-session = true

# Destructive fail-safe. A confirmed Bundle inside one of these block containers
# is quarantined immediately and the block is replaced on the next tick.
rebuild-on-contamination = true
rebuild-container-types = ["minecraft:hopper"]
rebuild-delay-ticks = 1

alert-cooldown-seconds = 3.0
session-timeout-seconds = 60.0
candidate-timeout-seconds = 1.5

# Off by default: enabling it adds counters to every packet callback for profiling.
perf-counters = false
'''


@dataclass(frozen=True, slots=True)
class Settings:
    enabled: bool = True
    alert_ops: bool = True
    log_attempts: bool = True
    player_message: str = DEFAULT_PLAYER_MESSAGE
    block_open_with_bundle: bool = True
    guard_player_auth_input: bool = True
    quarantine_contaminated_session: bool = True
    rebuild_on_contamination: bool = True
    rebuild_container_types: tuple[str, ...] = DEFAULT_REBUILD_CONTAINER_TYPES
    rebuild_delay_ticks: int = 1
    alert_cooldown_seconds: float = 3.0
    session_timeout_seconds: float = 60.0
    candidate_timeout_seconds: float = 1.5
    perf_counters: bool = False


def _as_bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _as_float(value: object, default: float, minimum: float, maximum: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(minimum, min(float(value), maximum))
    return default


def _as_int(value: object, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return max(minimum, min(value, maximum))
    return default


def _as_container_types(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return DEFAULT_REBUILD_CONTAINER_TYPES
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        item = item.strip().lower()
        if item and item not in result:
            result.append(item)
    return tuple(result) if result else DEFAULT_REBUILD_CONTAINER_TYPES


def load_settings(data_folder: Path) -> Settings:
    data_folder.mkdir(parents=True, exist_ok=True)
    path = data_folder / "config.toml"
    if not path.exists():
        path.write_text(DEFAULT_CONFIG, encoding="utf-8")

    try:
        with path.open("rb") as fp:
            raw = tomllib.load(fp)
    except Exception:
        raw = {}

    msg = raw.get("player-message", DEFAULT_PLAYER_MESSAGE)
    if not isinstance(msg, str) or not msg:
        msg = DEFAULT_PLAYER_MESSAGE

    return Settings(
        enabled=_as_bool(raw.get("enabled"), True),
        alert_ops=_as_bool(raw.get("alert-ops"), True),
        log_attempts=_as_bool(raw.get("log-attempts"), True),
        player_message=msg,
        block_open_with_bundle=_as_bool(raw.get("block-open-with-bundle"), True),
        guard_player_auth_input=_as_bool(raw.get("guard-player-auth-input"), True),
        quarantine_contaminated_session=_as_bool(raw.get("quarantine-contaminated-session"), True),
        rebuild_on_contamination=_as_bool(raw.get("rebuild-on-contamination"), True),
        rebuild_container_types=_as_container_types(raw.get("rebuild-container-types")),
        rebuild_delay_ticks=_as_int(raw.get("rebuild-delay-ticks"), 1, 1, 20),
        alert_cooldown_seconds=_as_float(raw.get("alert-cooldown-seconds"), 3.0, 0.25, 30.0),
        session_timeout_seconds=_as_float(raw.get("session-timeout-seconds"), 60.0, 5.0, 600.0),
        candidate_timeout_seconds=_as_float(raw.get("candidate-timeout-seconds"), 1.5, 0.25, 5.0),
        perf_counters=_as_bool(raw.get("perf-counters"), False),
    )
