"""format_block_state 格式化方块属性测试"""
from mod.ezmatic.main import format_block_state


class TestFormatBlockState:
    def test_empty_state(self):
        assert format_block_state({}) == ""

    def test_none_state(self):
        assert format_block_state(None) == ""

    def test_single_property(self):
        result = format_block_state({"facing": "north"})
        assert result == '["facing"="north"]'

    def test_multiple_properties_sorted(self):
        result = format_block_state({"z": "1", "a": "2"})
        assert result == '["a"="2","z"="1"]'

    def test_bool_property(self):
        result = format_block_state({"lit_bit": True})
        assert result == '["lit_bit"=true]'

    def test_bool_false(self):
        result = format_block_state({"waterlogged_bit": False})
        assert result == '["waterlogged_bit"=false]'

    def test_numeric_property(self):
        result = format_block_state({"age": 3})
        assert result == '["age"=3]'

    def test_mixed_types(self):
        result = format_block_state({"facing": "east", "lit_bit": True, "age": 7})
        assert result == '["age"=7,"facing"="east","lit_bit"=true]'
