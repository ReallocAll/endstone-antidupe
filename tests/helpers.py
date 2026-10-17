from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID

from endstone_antidupe.config import Settings
from endstone_antidupe.plugin import AntiDupe
from endstone_antidupe.state import Counters, PerfCounters


class NullLogger:
    def __init__(self):
        self.messages = []
    def info(self, msg): self.messages.append(('info', msg))
    def warning(self, msg): self.messages.append(('warning', msg))
    def error(self, msg): self.messages.append(('error', msg))


class FakeScheduler:
    def __init__(self):
        self.tasks = []
    def run_task(self, plugin, task, delay=0, period=None):
        self.tasks.append((task, delay, period))
        return task

    def cancel_tasks(self, plugin):
        self.tasks.clear()

    def run_next(self):
        task, delay, _ = self.tasks.pop(0)
        task()
        return delay


class FakeServer:
    def __init__(self):
        self.online_players = []
        self.scheduler = FakeScheduler()
        self.level = SimpleNamespace(dimensions=[])
        self.protocol_version = 2193


class CountingPlayer:
    def __init__(self, runtime_id=1, unique_id=None, name='p', inventory=None, is_op=False):
        self._runtime_id = runtime_id
        self._unique_id = unique_id or UUID(int=runtime_id)
        self._name = name
        self._inventory = list(inventory or [])
        self._is_op = is_op
        self.runtime_reads = 0
        self.uuid_reads = 0
        self.name_reads = 0
        self.inventory_reads = 0
        self.messages = []
        self.kicks = []

    @property
    def runtime_id(self):
        self.runtime_reads += 1
        return self._runtime_id

    @property
    def unique_id(self):
        self.uuid_reads += 1
        return self._unique_id

    @property
    def name(self):
        self.name_reads += 1
        return self._name

    @property
    def inventory(self):
        self.inventory_reads += 1
        return SimpleNamespace(contents=self._inventory)

    @property
    def is_op(self):
        return self._is_op

    def send_message(self, msg):
        self.messages.append(msg)

    def kick(self, msg):
        self.kicks.append(msg)


class PacketEvent:
    def __init__(self, packet_id, player=None, payload=b''):
        self._packet_id = packet_id
        self._player = player
        self._payload = payload
        self.packet_id_reads = 0
        self.player_reads = 0
        self.payload_reads = 0
        self.is_cancelled = False

    @property
    def packet_id(self):
        self.packet_id_reads += 1
        return self._packet_id

    @property
    def player(self):
        self.player_reads += 1
        return self._player

    @property
    def payload(self):
        self.payload_reads += 1
        return self._payload


@dataclass
class FakeItemType:
    id: str


class FakeItem:
    def __init__(self, type_id):
        self.type = FakeItemType(type_id)


def make_plugin(*, perf=False, settings=None):
    p = object.__new__(AntiDupe)
    p._candidates = {}
    p._sessions = {}
    p._players = {}
    p._transfers = {}
    p._transfer_guard_enabled = True
    p._stats = Counters()
    p._perf = PerfCounters()
    p._report_state = {}
    p._quarantined_blocks = set()
    p._pending_rebuilds = set()
    p._settings = settings or Settings(perf_counters=perf, alert_ops=False, log_attempts=False)
    p._perf_enabled = p._settings.perf_counters
    p.server = FakeServer()
    p.logger = NullLogger()
    p.data_folder = '/tmp/antidupe-test'
    return p


def auth_input_2193(flags=(), optionals=b'\x00\x00\x00'):
    return (bytes(32) + encode_varuint(len(flags))
            + b''.join(encode_varuint((f << 1) ^ (f >> 31)) for f in flags)
            + b'\x02\x00\x02' + bytes(8) + b'\x01' + bytes(12)
            + optionals + bytes(2 + 28))


def encode_varuint(value: int) -> bytes:
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def auth_input_payload(*, stack_request: bool) -> bytes:
    flags = (1 << 36) if stack_request else 0
    return b'\x00' * 32 + encode_varuint(flags)
