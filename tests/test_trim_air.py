"""trim_air 底部空气裁剪测试"""
from mod.ezmatic.main import trim_air


class TestTrimAir:
    def _make_data(self, min_y, blocks, unmapped=None):
        return {
            "sx": 1, "sy": 10, "sz": 1,
            "totalCoords": 10,
            "blocks": blocks,
            "minY": min_y,
            "maxY": 9,
            "unmappedBlocks": unmapped or [],
        }

    def test_no_trim_when_min_y_zero(self):
        blocks = [{"x": 0, "y": 5, "z": 0, "identifier": "stone", "state": {}, "cmd": "stone"}]
        data = self._make_data(0, blocks)
        result = trim_air(data)
        assert result["trimmedAir"] == 0
        assert result["blocks"][0]["y"] == 5
        assert result["sy"] == 10

    def test_trim_shifts_blocks_down(self):
        blocks = [
            {"x": 0, "y": 3, "z": 0, "identifier": "stone", "state": {}, "cmd": "stone"},
            {"x": 0, "y": 5, "z": 0, "identifier": "dirt", "state": {}, "cmd": "dirt"},
        ]
        data = self._make_data(3, blocks)
        result = trim_air(data)
        assert result["trimmedAir"] == 3
        assert result["blocks"][0]["y"] == 0  # 3 - 3
        assert result["blocks"][1]["y"] == 2  # 5 - 3
        assert result["sy"] == 7  # 9 - 3 + 1

    def test_trim_updates_total_coords(self):
        blocks = [{"x": 0, "y": 2, "z": 0, "identifier": "stone", "state": {}, "cmd": "stone"}]
        data = {"sx": 2, "sy": 5, "sz": 3, "totalCoords": 30, "blocks": blocks, "minY": 2, "maxY": 4, "unmappedBlocks": []}
        result = trim_air(data)
        assert result["totalCoords"] == 2 * 3 * 3  # sx * new_sy * sz

    def test_trim_shifts_unmapped_blocks(self):
        blocks = [{"x": 0, "y": 4, "z": 0, "identifier": "stone", "state": {}, "cmd": "stone"}]
        unmapped = [{"x": 0, "y": 4, "z": 0, "name": "mod:block"}]
        data = self._make_data(4, blocks, unmapped)
        result = trim_air(data)
        assert result["unmappedBlocks"][0]["y"] == 0
