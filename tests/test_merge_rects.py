"""merge_blocks_to_rects 矩形合并优化测试"""
from mod.ezmatic.main import merge_blocks_to_rects


class TestMergeBlocksToRects:
    def test_single_block(self):
        blocks = [{"x": 0, "y": 0, "z": 0, "cmd": "stone"}]
        result = merge_blocks_to_rects(blocks, sx=3, sz=3)
        assert len(result) == 1
        assert result[0]["type"] == "setblock"
        assert result[0]["cmd"] == "stone"

    def test_horizontal_fill(self):
        """同一行 3 个相同方块 → 1 个 fill"""
        blocks = [
            {"x": 0, "y": 0, "z": 0, "cmd": "stone"},
            {"x": 1, "y": 0, "z": 0, "cmd": "stone"},
            {"x": 2, "y": 0, "z": 0, "cmd": "stone"},
        ]
        result = merge_blocks_to_rects(blocks, sx=3, sz=3)
        fills = [r for r in result if r["type"] == "fill"]
        assert len(fills) == 1
        assert fills[0]["x1"] == 0
        assert fills[0]["x2"] == 2
        assert fills[0]["count"] == 3

    def test_square_fill(self):
        """2x2 相同方块 → 1 个 fill"""
        blocks = [
            {"x": 0, "y": 0, "z": 0, "cmd": "dirt"},
            {"x": 1, "y": 0, "z": 0, "cmd": "dirt"},
            {"x": 0, "y": 0, "z": 1, "cmd": "dirt"},
            {"x": 1, "y": 0, "z": 1, "cmd": "dirt"},
        ]
        result = merge_blocks_to_rects(blocks, sx=4, sz=4)
        fills = [r for r in result if r["type"] == "fill"]
        assert len(fills) == 1
        assert fills[0]["count"] == 4

    def test_different_cmds_not_merged(self):
        """不同 cmd 不合并"""
        blocks = [
            {"x": 0, "y": 0, "z": 0, "cmd": "stone"},
            {"x": 1, "y": 0, "z": 0, "cmd": "dirt"},
        ]
        result = merge_blocks_to_rects(blocks, sx=3, sz=3)
        assert len(result) == 2
        assert all(r["type"] == "setblock" for r in result)

    def test_empty_blocks(self):
        result = merge_blocks_to_rects([], sx=5, sz=5)
        assert result == []

    def test_full_layer_fill(self):
        """3x3 整层相同 → 1 个 fill"""
        blocks = [
            {"x": x, "y": 0, "z": z, "cmd": "glass"}
            for z in range(3) for x in range(3)
        ]
        result = merge_blocks_to_rects(blocks, sx=3, sz=3)
        fills = [r for r in result if r["type"] == "fill"]
        assert len(fills) == 1
        assert fills[0]["count"] == 9
