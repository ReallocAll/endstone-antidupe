import time
from pathlib import Path
from typing import Any

from endstone.command import Command, CommandSender
from endstone.event import (
    PacketReceiveEvent,
    PacketSendEvent,
    PlayerDimensionChangeEvent,
    PlayerInteractActorEvent,
    PlayerInteractEvent,
    PlayerJoinEvent,
    PlayerQuitEvent,
    event_handler,
)
from endstone.plugin import Plugin

from .config import Settings, load_settings
from .constants import (
    DIRECT_TRANSACTION_PACKET_IDS,
    PACKET_CONTAINER_CLOSE,
    PACKET_CONTAINER_OPEN,
    PACKET_PLAYER_AUTH_INPUT,
    RECEIVE_RELEVANT_PACKET_IDS,
    RESTRICTED_BLOCK_CONTAINERS,
    RESTRICTED_ENTITY_CONTAINERS,
    SEND_RELEVANT_PACKET_IDS,
    is_bundle_type,
)
from .protocol import (
    container_open_id,
    inventory_sync_container_id,
    player_auth_input_has_stack_request,
)
from .rebuild import rebuild_block
from .state import (
    ContainerCandidate,
    ContainerSession,
    Counters,
    PerfCounters,
    PlayerRuntimeState,
)

PlayerKey = int
BlockKey = tuple[str, int, int, int]
ReportKey = tuple[PlayerKey, str, str, int, int, int]


class AntiDupe(Plugin):
    api_version = "0.11"
    description = "Bundle/container anti-dupe guard for Endstone."

    commands = {
        "antidupe": {
            "description": "AntiDupe status/reload/perf.",
            "usages": [
                "/antidupe",
                "/antidupe (status|reload)<action: AntidupeAction>",
                "/antidupe (perf)<action: AntidupePerfAction> (reset)[perf_action: AntidupePerfReset]",
            ],
            "permissions": ["antidupe.command"],
        }
    }

    permissions = {
        "antidupe.command": {
            "description": "Manage AntiDupe.",
            "default": "op",
        }
    }

    def on_enable(self) -> None:
        self._candidates: dict[PlayerKey, ContainerCandidate] = {}
        self._sessions: dict[PlayerKey, ContainerSession] = {}
        self._players: dict[PlayerKey, PlayerRuntimeState] = {}
        self._stats = Counters()
        self._perf = PerfCounters()
        self._report_state: dict[ReportKey, tuple[float, int]] = {}
        self._quarantined_blocks: set[BlockKey] = set()
        self._pending_rebuilds: set[BlockKey] = set()
        self._settings = self._load_settings_with_log()
        self._perf_enabled = self._settings.perf_counters

        self.register_events(self)
        self.server.scheduler.run_task(self, self._cleanup_expired, delay=100, period=100)

        # This also handles plugin reload while players are already online.
        try:
            for player in self.server.online_players:
                self._register_player(player, reset_existing=True)
        except Exception:
            pass

        state = "ON" if self._settings.enabled else "OFF"
        auth_guard = "ON" if self._settings.guard_player_auth_input else "OFF"
        rebuild_guard = "ON" if self._settings.rebuild_on_contamination else "OFF"
        self.logger.info(
            f"antidupe 0.2.3 enabled: Bundle/container guard is {state}; "
            f"PlayerAuthInput guard={auth_guard}; rebuild fail-safe={rebuild_guard}; "
            f"perf counters={'ON' if self._perf_enabled else 'OFF'}."
        )

    def on_disable(self) -> None:
        self._candidates.clear()
        self._sessions.clear()
        self._players.clear()
        self._report_state.clear()
        self._quarantined_blocks.clear()
        self._pending_rebuilds.clear()
        self.logger.info("antidupe disabled.")

    @event_handler
    def on_player_join(self, event: PlayerJoinEvent) -> None:
        if not self._settings.enabled:
            return
        self._register_player(event.player, reset_existing=True)

    @event_handler(ignore_cancelled=True)
    def on_player_interact(self, event: PlayerInteractEvent) -> None:
        if not self._settings.enabled:
            return
        if event.action != PlayerInteractEvent.RIGHT_CLICK_BLOCK:
            return
        if not event.has_block or event.block is None:
            return

        block = event.block
        block_type = str(block.type).lower()
        player = event.player

        if block_type not in RESTRICTED_BLOCK_CONTAINERS:
            # Most interactions never need any player identity lookup.
            if self._candidates:
                key = self._player_key(player)
                self._candidates.pop(key, None)
            return

        key = self._player_key(player)
        dimension_name = self._dimension_name(block.dimension)
        x, y, z = int(block.x), int(block.y), int(block.z)
        block_key = self._make_block_key(dimension_name, x, y, z)

        if block_key in self._quarantined_blocks:
            event.is_cancelled = True
            self._stats.blocked_opens += 1
            self._report(
                player,
                "blocked-open-quarantined",
                block_type,
                x,
                y,
                z,
                notify_player=True,
                player_key=key,
            )
            return

        if self._settings.block_open_with_bundle and self._player_has_bundle(player):
            event.is_cancelled = True
            self._candidates.pop(key, None)
            self._sessions.pop(key, None)
            self._stats.blocked_opens += 1
            self._report(
                player,
                "blocked-open",
                block_type,
                x,
                y,
                z,
                notify_player=True,
                player_key=key,
            )
            return

        self._candidates[key] = ContainerCandidate(
            kind="block",
            target_type=block_type,
            dimension=dimension_name,
            x=x,
            y=y,
            z=z,
            created_at=time.monotonic(),
        )

    @event_handler(ignore_cancelled=True)
    def on_player_interact_actor(self, event: PlayerInteractActorEvent) -> None:
        if not self._settings.enabled:
            return

        player = event.player
        actor = event.actor
        actor_type = str(actor.type).lower()

        if actor_type not in RESTRICTED_ENTITY_CONTAINERS:
            if self._candidates:
                key = self._player_key(player)
                self._candidates.pop(key, None)
            return

        key = self._player_key(player)
        loc = actor.location
        x, y, z = int(loc.x), int(loc.y), int(loc.z)
        if self._settings.block_open_with_bundle and self._player_has_bundle(player):
            event.is_cancelled = True
            self._candidates.pop(key, None)
            self._sessions.pop(key, None)
            self._stats.blocked_opens += 1
            self._report(
                player,
                "blocked-open",
                actor_type,
                x,
                y,
                z,
                notify_player=True,
                player_key=key,
            )
            return

        self._candidates[key] = ContainerCandidate(
            kind="entity",
            target_type=actor_type,
            dimension=self._dimension_name(actor.dimension),
            x=x,
            y=y,
            z=z,
            created_at=time.monotonic(),
        )

    @event_handler(ignore_cancelled=True)
    def on_packet_send(self, event: PacketSendEvent) -> None:
        if not self._settings.enabled:
            return

        # CRITICAL HOT PATH: packet_id must be the first native property read.
        # Do not touch event.player, event.payload, UUID, inventory, or world state
        # until this filter has accepted the packet.
        packet_id = event.packet_id
        if self._perf_enabled:
            perf = self._perf
            perf.packet_send_calls += 1
            perf.send_by_packet_id[packet_id] = perf.send_by_packet_id.get(packet_id, 0) + 1

        if packet_id not in SEND_RELEVANT_PACKET_IDS:
            if self._perf_enabled:
                self._perf.send_fast_returns += 1
            return

        if self._perf_enabled:
            self._perf.send_relevant += 1

        # Global-state guards avoid even event.player for relevant packet IDs when
        # there is no AntiDupe state that could consume them.
        if packet_id == PACKET_CONTAINER_OPEN:
            if not self._candidates:
                if self._perf_enabled:
                    self._perf.send_fast_returns += 1
                return
        elif packet_id == PACKET_CONTAINER_CLOSE:
            if not self._sessions and not self._candidates:
                if self._perf_enabled:
                    self._perf.send_fast_returns += 1
                return
        else:  # InventoryContent / InventorySlot
            if not self._sessions:
                if self._perf_enabled:
                    self._perf.send_fast_returns += 1
                return

        player = event.player
        if player is None:
            return
        key = self._player_key(player)

        if packet_id == PACKET_CONTAINER_CLOSE:
            self._clear_session_state(key)
            return

        if packet_id == PACKET_CONTAINER_OPEN:
            candidate = self._candidates.pop(key, None)
            if candidate is None:
                return
            now = time.monotonic()
            if now - candidate.created_at > self._settings.candidate_timeout_seconds:
                return
            if self._perf_enabled:
                self._perf.payload_reads += 1
            try:
                window_id = container_open_id(event.payload)
            except Exception:
                window_id = None
            self._sessions[key] = ContainerSession(
                kind=candidate.kind,
                target_type=candidate.target_type,
                dimension=candidate.dimension,
                x=candidate.x,
                y=candidate.y,
                z=candidate.z,
                opened_at=now,
                last_activity=now,
                container_id=window_id,
            )
            return

        session = self._sessions.get(key)
        if session is None:
            return

        if self._perf_enabled:
            self._perf.payload_reads += 1
        try:
            payload = event.payload
            sync_id = inventory_sync_container_id(packet_id, payload)
        except Exception:
            return

        # Destructive action must only be based on the inventory belonging to
        # the exact window that was opened. This prevents a player-inventory
        # sync containing a bundle from causing the hopper to be rebuilt.
        if session.container_id is None or sync_id != session.container_id:
            return

        session.last_activity = time.monotonic()

        # Minecraft identifiers are lowercase. Avoid payload.lower(), which used
        # to allocate/copy the entire packet on every relevant inventory sync.
        if b"bundle" not in payload:
            return

        first_contamination = not session.contaminated
        if first_contamination:
            session.contaminated = True
            self._stats.contaminated_sessions += 1

        if not session.contamination_alerted:
            session.contamination_alerted = True
            self._report(
                player,
                "container-has-bundle",
                session.target_type,
                session.x,
                session.y,
                session.z,
                notify_player=True,
                player_key=key,
            )

        if first_contamination and session.kind == "block":
            self._quarantine_and_schedule_rebuild(player, key, session)

    @event_handler(ignore_cancelled=True)
    def on_packet_receive(self, event: PacketReceiveEvent) -> None:
        if not self._settings.enabled:
            return

        # Same rule as outbound: irrelevant packet IDs must never touch player,
        # UUID, payload, inventory, or world state.
        packet_id = event.packet_id
        if self._perf_enabled:
            perf = self._perf
            perf.packet_receive_calls += 1
            perf.receive_by_packet_id[packet_id] = perf.receive_by_packet_id.get(packet_id, 0) + 1

        if packet_id not in RECEIVE_RELEVANT_PACKET_IDS:
            if self._perf_enabled:
                self._perf.receive_fast_returns += 1
            return

        if self._perf_enabled:
            self._perf.receive_relevant += 1

        if packet_id == PACKET_CONTAINER_CLOSE:
            if not self._sessions and not self._candidates:
                if self._perf_enabled:
                    self._perf.receive_fast_returns += 1
                return
        elif not self._sessions:
            # This catches ordinary PlayerAuthInput(144) before player/payload.
            if self._perf_enabled:
                self._perf.receive_fast_returns += 1
            return

        player = event.player
        if player is None:
            return
        key = self._player_key(player)

        if packet_id == PACKET_CONTAINER_CLOSE:
            self._clear_session_state(key)
            return

        session = self._sessions.get(key)
        if session is None:
            return

        if packet_id == PACKET_PLAYER_AUTH_INPUT:
            if not self._settings.guard_player_auth_input:
                return
            if self._perf_enabled:
                self._perf.payload_reads += 1
            try:
                if not player_auth_input_has_stack_request(event.payload):
                    return
            except Exception:
                return

            if not self._session_is_unsafe(player, session):
                return

            event.is_cancelled = True
            session.last_activity = time.monotonic()
            session.blocked_count += 1
            self._stats.blocked_auth_input_requests += 1
            self._report(
                player,
                "blocked-auth-input-request",
                session.target_type,
                session.x,
                session.y,
                session.z,
                notify_player=False,
                player_key=key,
            )
            return

        if packet_id not in DIRECT_TRANSACTION_PACKET_IDS:
            return
        if not self._session_is_unsafe(player, session):
            return

        event.is_cancelled = True
        session.last_activity = time.monotonic()
        session.blocked_count += 1
        self._stats.blocked_direct_transactions += 1
        self._report(
            player,
            "blocked-inventory-request",
            session.target_type,
            session.x,
            session.y,
            session.z,
            notify_player=False,
            player_key=key,
        )

    @event_handler
    def on_player_dimension_change(self, event: PlayerDimensionChangeEvent) -> None:
        if not self._settings.enabled:
            return
        try:
            key = int(event.player.runtime_id)
        except Exception:
            return
        # Container windows cannot remain valid across dimensions. Keep the
        # connection identity cache, but drop all transient container state.
        self._clear_session_state(key)

    @event_handler
    def on_player_quit(self, event: PlayerQuitEvent) -> None:
        # runtime_id is a cheap uint64 pybind getter and is connection-local.
        try:
            key = int(event.player.runtime_id)
        except Exception:
            return
        self._clear_player_all(key)

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if not args:
            sender.send_message("§6antidupe §f0.2.3")
            sender.send_message("§e/antidupe status §7- 查看状态")
            sender.send_message("§e/antidupe reload §7- 重载配置")
            sender.send_message("§e/antidupe perf §7- 查看性能计数器")
            return True

        sub = args[0].lower()
        if sub == "status":
            sender.send_message("§6=== AntiDupe ===")
            sender.send_message(f"§7状态: {'§a启用' if self._settings.enabled else '§c关闭'}")
            sender.send_message(
                f"§7PlayerAuthInput 防护: "
                f"{'§a启用' if self._settings.guard_player_auth_input else '§c关闭'}"
            )
            sender.send_message(
                f"§7污染后重建: "
                f"{'§a启用' if self._settings.rebuild_on_contamination else '§c关闭'}"
            )
            sender.send_message(
                f"§7性能计数器: {'§a启用' if self._perf_enabled else '§8关闭'}"
            )
            sender.send_message(f"§7连接缓存: §f{len(self._players)}")
            sender.send_message(f"§7活动高风险容器会话: §f{len(self._sessions)}")
            sender.send_message(f"§7全局隔离方块: §f{len(self._quarantined_blocks)}")
            sender.send_message(f"§7已阻止打开: §f{self._stats.blocked_opens}")
            sender.send_message(f"§7污染会话: §f{self._stats.contaminated_sessions}")
            sender.send_message(f"§7已重建容器: §f{self._stats.rebuilt_containers}")
            sender.send_message(f"§7重建失败: §f{self._stats.rebuild_failures}")
            sender.send_message(
                f"§7已阻止直接库存请求: §f{self._stats.blocked_direct_transactions}"
            )
            sender.send_message(
                f"§7已阻止 144 内嵌库存请求: §f{self._stats.blocked_auth_input_requests}"
            )
            return True

        if sub == "perf":
            if len(args) > 1 and args[1].lower() == "reset":
                self._perf.reset()
                sender.send_message("§aAntiDupe 性能计数器已清零。")
                return True
            self._send_perf_status(sender)
            return True

        if sub == "reload":
            self._settings = self._load_settings_with_log()
            self._perf_enabled = self._settings.perf_counters
            self._candidates.clear()
            self._sessions.clear()
            self._players.clear()
            self._report_state.clear()
            self._quarantined_blocks.clear()
            self._pending_rebuilds.clear()
            self._perf.reset()
            try:
                for player in self.server.online_players:
                    self._register_player(player, reset_existing=True)
            except Exception:
                pass
            sender.send_message("§aAntiDupe 配置已重载。")
            return True

        sender.send_message("§c用法: /antidupe [status|reload|perf [reset]]")
        return False

    def _send_perf_status(self, sender: CommandSender) -> None:
        if not self._perf_enabled:
            sender.send_message("§7AntiDupe 性能计数器当前关闭。设置 perf-counters = true 后 reload。")
            return
        p = self._perf
        sender.send_message("§6=== AntiDupe Perf ===")
        sender.send_message(
            f"§7send callbacks/relevant/fast-return: §f{p.packet_send_calls}/"
            f"{p.send_relevant}/{p.send_fast_returns}"
        )
        sender.send_message(
            f"§7recv callbacks/relevant/fast-return: §f{p.packet_receive_calls}/"
            f"{p.receive_relevant}/{p.receive_fast_returns}"
        )
        sender.send_message(
            f"§7player key calls/hit/miss: §f{p.player_key_calls}/"
            f"{p.player_cache_hits}/{p.player_cache_misses}"
        )
        sender.send_message(
            f"§7UUID constructs/to-str: §f{p.uuid_constructs}/{p.uuid_to_str}"
        )
        sender.send_message(
            f"§7deep checks/inventory queries: §f{p.deep_checks}/{p.inventory_queries}"
        )
        sender.send_message(
            f"§7payload reads/world-block queries/db accesses: §f"
            f"{p.payload_reads}/{p.world_block_queries}/{p.database_accesses}"
        )
        top_send = sorted(p.send_by_packet_id.items(), key=lambda item: item[1], reverse=True)[:8]
        top_recv = sorted(p.receive_by_packet_id.items(), key=lambda item: item[1], reverse=True)[:8]
        sender.send_message(f"§7send top IDs: §f{top_send}")
        sender.send_message(f"§7recv top IDs: §f{top_recv}")

    def _quarantine_and_schedule_rebuild(
        self, player: Any, player_key: PlayerKey, session: ContainerSession
    ) -> None:
        block_key = self._session_block_key(session)
        if block_key is None:
            return

        # Quarantine is immediate; rebuild happens a tick later. Any other
        # viewer/session touching the same block becomes unsafe during the gap.
        self._quarantined_blocks.add(block_key)

        if not self._settings.rebuild_on_contamination:
            return
        if session.target_type not in self._settings.rebuild_container_types:
            return
        if block_key in self._pending_rebuilds:
            return

        dimension = self._find_dimension(session.dimension)
        if dimension is None:
            self._stats.rebuild_failures += 1
            self.logger.error(
                f"[AntiDupe] Cannot rebuild {session.target_type} at "
                f"({session.x}, {session.y}, {session.z}): dimension {session.dimension!r} not found."
            )
            return

        if self._perf_enabled:
            self._perf.world_block_queries += 1
        block = dimension.get_block_at(session.x, session.y, session.z)
        current_type = str(block.type).lower()
        if current_type != session.target_type:
            self._quarantined_blocks.discard(block_key)
            return

        try:
            saved_data = block.data
        except Exception as exc:
            self._stats.rebuild_failures += 1
            self.logger.error(
                f"[AntiDupe] Failed to snapshot {session.target_type} at "
                f"({session.x}, {session.y}, {session.z}); keeping it quarantined: {exc}"
            )
            return

        self._pending_rebuilds.add(block_key)
        self._report(
            player,
            "rebuild-scheduled",
            session.target_type,
            session.x,
            session.y,
            session.z,
            notify_player=False,
            player_key=player_key,
        )

        expected_type = session.target_type
        dimension_name = session.dimension
        x, y, z = session.x, session.y, session.z

        def task() -> None:
            self._perform_rebuild(
                block_key, dimension_name, x, y, z, expected_type, saved_data
            )

        self.server.scheduler.run_task(
            self,
            task,
            delay=self._settings.rebuild_delay_ticks,
        )

    def _perform_rebuild(
        self,
        block_key: BlockKey,
        dimension_name: str,
        x: int,
        y: int,
        z: int,
        expected_type: str,
        saved_data: Any,
    ) -> None:
        try:
            dimension = self._find_dimension(dimension_name)
            if dimension is None:
                raise RuntimeError(f"dimension {dimension_name!r} not found")

            if self._perf_enabled:
                # rebuild_block performs get_block_at three times.
                self._perf.world_block_queries += 3
            result = rebuild_block(dimension, x, y, z, expected_type, saved_data)
            if result.status == "changed":
                self.logger.warning(
                    f"[AntiDupe] Rebuild skipped at ({x}, {y}, {z}): "
                    f"target changed from {expected_type} to {result.before_type}."
                )
                self._quarantined_blocks.discard(block_key)
                return
            if result.status != "rebuilt":
                raise RuntimeError(
                    f"restored block type mismatch: expected {expected_type}, got {result.after_type}"
                )

            self._stats.rebuilt_containers += 1
            self.logger.warning(
                f"§c[AntiDupe] rebuilt contaminated {expected_type} at ({x}, {y}, {z}); "
                "original BlockData restored."
            )
            self._clear_sessions_for_block(block_key)
            self._quarantined_blocks.discard(block_key)
        except Exception as exc:
            # Fail closed: if rebuilding failed after contamination, leave the
            # location globally quarantined until an admin fixes it or reloads.
            self._stats.rebuild_failures += 1
            self.logger.error(
                f"[AntiDupe] Failed to rebuild contaminated {expected_type} at "
                f"({x}, {y}, {z}); location remains quarantined: {exc}"
            )
        finally:
            self._pending_rebuilds.discard(block_key)

    def _session_is_unsafe(self, player: Any, session: ContainerSession) -> bool:
        if self._perf_enabled:
            self._perf.deep_checks += 1
        block_key = self._session_block_key(session)
        if block_key is not None and block_key in self._quarantined_blocks:
            return True
        if self._settings.quarantine_contaminated_session and session.contaminated:
            return True
        # This inventory scan now runs only for an actual inventory request in
        # an active high-risk-container session, never for ordinary movement.
        return self._player_has_bundle(player)

    def _load_settings_with_log(self) -> Settings:
        path = Path(self.data_folder) / "config.toml"
        try:
            return load_settings(Path(self.data_folder))
        except Exception as exc:
            self.logger.warning(f"Failed to load {path}; using safe defaults: {exc}")
            return Settings()

    def _register_player(self, player: Any, *, reset_existing: bool) -> PlayerKey:
        runtime_id = int(player.runtime_id)
        if reset_existing:
            self._clear_player_all(runtime_id)

        # Endstone's UUID type caster constructs a Python uuid.UUID object.
        # This is deliberately paid once per connection / lazy registration,
        # never once per packet.
        unique_id = player.unique_id
        if self._perf_enabled:
            self._perf.uuid_constructs += 1
        try:
            name = str(player.name)
        except Exception:
            name = "?"
        self._players[runtime_id] = PlayerRuntimeState(
            runtime_id=runtime_id,
            unique_id=unique_id,
            name=name,
            created_at=time.monotonic(),
        )
        return runtime_id

    def _player_key(self, player: Any) -> PlayerKey:
        # Actor.runtime_id is exposed by Endstone as a uint64. It avoids the
        # uuid.UUID constructor and str(UUID) path entirely.
        if self._perf_enabled:
            self._perf.player_key_calls += 1
        runtime_id = int(player.runtime_id)
        if runtime_id in self._players:
            if self._perf_enabled:
                self._perf.player_cache_hits += 1
            return runtime_id

        if self._perf_enabled:
            self._perf.player_cache_misses += 1
        return self._register_player(player, reset_existing=False)

    @staticmethod
    def _dimension_name(dimension: Any) -> str:
        name = getattr(dimension, "name", None)
        return str(name) if name is not None else str(dimension)

    @staticmethod
    def _make_block_key(dimension: str, x: int, y: int, z: int) -> BlockKey:
        return (dimension, x, y, z)

    def _session_block_key(self, session: ContainerSession) -> BlockKey | None:
        if session.kind != "block":
            return None
        return self._make_block_key(session.dimension, session.x, session.y, session.z)

    def _find_dimension(self, dimension_name: str) -> Any | None:
        try:
            for dimension in self.server.level.dimensions:
                if self._dimension_name(dimension) == dimension_name:
                    return dimension
        except Exception:
            pass
        return None

    @staticmethod
    def _item_type_id(item: Any) -> str:
        if item is None:
            return ""
        try:
            return str(item.type.id)
        except Exception:
            try:
                return str(item.type)
            except Exception:
                return ""

    def _player_has_bundle(self, player: Any) -> bool:
        if self._perf_enabled:
            self._perf.inventory_queries += 1
        try:
            for item in player.inventory.contents:
                if item is not None and is_bundle_type(self._item_type_id(item)):
                    return True
        except Exception as exc:
            # Exception-only path: no formatting/logging exists on normal packets.
            self.logger.warning(
                f"Failed to inspect inventory for {getattr(player, 'name', '?')}: {exc}"
            )
        return False

    def _clear_session_state(self, key: PlayerKey) -> None:
        self._candidates.pop(key, None)
        self._sessions.pop(key, None)

    def _clear_sessions_for_block(self, block_key: BlockKey) -> None:
        for player_key, session in list(self._sessions.items()):
            if self._session_block_key(session) == block_key:
                self._sessions.pop(player_key, None)
        for player_key, candidate in list(self._candidates.items()):
            candidate_key = self._make_block_key(
                candidate.dimension, candidate.x, candidate.y, candidate.z
            )
            if candidate.kind == "block" and candidate_key == block_key:
                self._candidates.pop(player_key, None)

    def _clear_player_all(self, key: PlayerKey) -> None:
        self._clear_session_state(key)
        self._players.pop(key, None)
        for report_key in [k for k in self._report_state if k[0] == key]:
            self._report_state.pop(report_key, None)

    def _cleanup_expired(self) -> None:
        now = time.monotonic()
        for key, candidate in list(self._candidates.items()):
            if now - candidate.created_at > self._settings.candidate_timeout_seconds:
                self._candidates.pop(key, None)

        for key, session in list(self._sessions.items()):
            if now - session.last_activity > self._settings.session_timeout_seconds:
                self._clear_session_state(key)

        stale = max(self._settings.alert_cooldown_seconds * 4.0, 15.0)
        for report_key, (last, _suppressed) in list(self._report_state.items()):
            if now - last > stale:
                self._report_state.pop(report_key, None)

    def _report(
        self,
        player: Any,
        reason: str,
        target_type: str,
        x: int,
        y: int,
        z: int,
        *,
        notify_player: bool,
        player_key: PlayerKey | None = None,
    ) -> None:
        now = time.monotonic()
        if player_key is None:
            player_key = self._player_key(player)
        report_key: ReportKey = (player_key, reason, target_type, x, y, z)
        last, suppressed = self._report_state.get(report_key, (0.0, 0))
        cooldown = self._settings.alert_cooldown_seconds
        if now - last < cooldown:
            self._report_state[report_key] = (last, suppressed + 1)
            return

        self._report_state[report_key] = (now, 0)
        name = getattr(player, "name", "?")
        suffix = f" (+{suppressed} suppressed)" if suppressed else ""
        message = (
            f"§c[AntiDupe] {name}: {reason} @ {target_type} "
            f"({x}, {y}, {z}){suffix}"
        )

        if self._settings.log_attempts:
            self.logger.warning(message)

        if notify_player:
            try:
                player.send_message(self._settings.player_message)
            except Exception:
                pass

        if self._settings.alert_ops:
            try:
                for online in self.server.online_players:
                    if online.is_op and int(online.runtime_id) != player_key:
                        online.send_message(message)
            except Exception:
                pass
