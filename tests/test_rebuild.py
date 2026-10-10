from types import SimpleNamespace

from endstone_antidupe.rebuild import rebuild_block


class FakeBlock:
    def __init__(self, dimension, block_type, data=None):
        self.dimension = dimension
        self.type = block_type
        self.data = data
        self.set_type_calls = []
        self.set_data_calls = []
    def set_type(self, block_type, apply_physics=True):
        self.set_type_calls.append((block_type, apply_physics))
        self.dimension.block = FakeBlock(self.dimension, block_type)
    def set_data(self, data, apply_physics=True):
        self.set_data_calls.append((data, apply_physics))
        # saved_data carries the intended type in this fake
        self.dimension.block = FakeBlock(self.dimension, data.type, data)


class FakeDimension:
    def __init__(self, block):
        self.block = block
        block.dimension = self
    def get_block_at(self, x, y, z):
        return self.block


def test_rebuild_restores_saved_block_data():
    saved = SimpleNamespace(type='minecraft:hopper', facing='east')
    initial = FakeBlock(None, 'minecraft:hopper', saved)
    dim = FakeDimension(initial)
    result = rebuild_block(dim, 1, 2, 3, 'minecraft:hopper', saved)
    assert result.status == 'rebuilt'
    assert dim.block.type == 'minecraft:hopper'
    assert dim.block.data is saved


def test_rebuild_does_not_overwrite_changed_block():
    initial = FakeBlock(None, 'minecraft:stone')
    dim = FakeDimension(initial)
    saved = SimpleNamespace(type='minecraft:hopper')
    result = rebuild_block(dim, 1, 2, 3, 'minecraft:hopper', saved)
    assert result.status == 'changed'
    assert dim.block.type == 'minecraft:stone'
