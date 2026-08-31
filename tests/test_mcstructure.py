"""build_mc_structure + NBT 序列化构建器测试"""
import struct

from mod.ezmatic.main import (
    T_BYTE,
    T_INT,
    T_STRING,
    n_byte,
    n_comp,
    n_int,
    n_list,
    n_str,
    nbt_payload,
    nbt_root,
    to_state,
    build_mc_structure,
)


class TestNbtBuilders:
    def test_nbt_root_int(self):
        result = nbt_root("test", n_int(42))
        # root: TAG_INT(1B) + name_len(2B) + "test"(4B) + int payload(4B) = 11B
        assert len(result) == 11
        assert result[0] == T_INT

    def test_nbt_payload_byte(self):
        result = nbt_payload(n_byte(0xAB))
        assert result == b"\xab"

    def test_nbt_payload_int(self):
        result = nbt_payload(n_int(-1))
        assert struct.unpack("<i", result)[0] == -1

    def test_nbt_payload_string(self):
        result = nbt_payload(n_str("hi"))
        # LE string: 2B length + bytes
        length = struct.unpack("<H", result[:2])[0]
        assert length == 2
        assert result[2:] == b"hi"

    def test_nbt_payload_compound(self):
        payload = n_comp({"x": n_int(1)})
        result = nbt_payload(payload)
        # compound = (child_type + child_name + child_payload) + end_tag
        assert result[-1] == 0  # TAG_END


class TestToState:
    def test_bool_true(self):
        result = to_state(True)
        assert result == (T_BYTE, 1)

    def test_bool_false(self):
        result = to_state(False)
        assert result == (T_BYTE, 0)

    def test_int(self):
        result = to_state(42)
        assert result == (T_INT, 42)

    def test_float_to_int(self):
        result = to_state(3.14)
        assert result == (T_INT, 3)

    def test_string(self):
        result = to_state("hello")
        assert result == (T_STRING, "hello")


class TestBuildMcStructure:
    def test_basic_structure(self):
        data = {
            "sx": 1, "sy": 1, "sz": 1,
            "blocks": [
                {"x": 0, "y": 0, "z": 0, "identifier": "minecraft:stone", "state": {}, "cmd": "stone"},
            ],
        }
        result = build_mc_structure(data)
        assert isinstance(result, (bytes, bytearray))
        assert len(result) > 0

    def test_two_different_blocks(self):
        data = {
            "sx": 2, "sy": 1, "sz": 1,
            "blocks": [
                {"x": 0, "y": 0, "z": 0, "identifier": "minecraft:stone", "state": {}, "cmd": "stone"},
                {"x": 1, "y": 0, "z": 0, "identifier": "minecraft:dirt", "state": {}, "cmd": "dirt"},
            ],
        }
        result = build_mc_structure(data)
        assert isinstance(result, (bytes, bytearray))
        # 输出应包含两个不同的方块名
        assert b"stone" in result
        assert b"dirt" in result

    def test_structure_with_properties(self):
        data = {
            "sx": 1, "sy": 1, "sz": 1,
            "blocks": [
                {
                    "x": 0, "y": 0, "z": 0,
                    "identifier": "minecraft:oak_stairs",
                    "state": {"facing_direction": 2, "upside_down_bit": False},
                    "cmd": "oak_stairs",
                },
            ],
        }
        result = build_mc_structure(data)
        assert isinstance(result, (bytes, bytearray))
        assert b"oak_stairs" in result
