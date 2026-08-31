"""NBT 解析器测试 — 手工构造 big-endian NBT 字节验证 parse_nbt"""
import struct

import pytest

# conftest.py 已 mock config，可以安全导入
from mod.ezmatic.main import (
    TAG_BYTE,
    TAG_COMPOUND,
    TAG_END,
    TAG_INT,
    TAG_LIST,
    TAG_LONG,
    TAG_STRING,
    parse_nbt,
)


def _ntype(t):
    """构造 NBT root wrapper: root_type(1B) + name_len(2B) + name（空名）"""
    return bytes([t]) + struct.pack(">H", 0)  # 空名


def _ncomp_end():
    return bytes([TAG_END])


def _nint(name, value):
    """INT 标签: type(1B) + name_len(2B) + name + value(4B big-endian)"""
    nb = name.encode()
    return bytes([TAG_INT]) + struct.pack(">H", len(nb)) + nb + struct.pack(">i", value)


def _nstring(name, value):
    """STRING 标签: type(1B) + name_len(2B) + name + str_len(2B) + str_bytes"""
    nb = name.encode()
    encoded = value.encode()
    return bytes([TAG_STRING]) + struct.pack(">H", len(nb)) + nb + struct.pack(">H", len(encoded)) + encoded


class TestParseNbt:
    def test_empty_compound(self):
        buf = _ntype(TAG_COMPOUND) + _ncomp_end()
        result = parse_nbt(buf)
        assert result == {}

    def test_single_int(self):
        buf = _ntype(TAG_COMPOUND) + _nint("val", 42) + _ncomp_end()
        result = parse_nbt(buf)
        assert result == {"val": 42}

    def test_multiple_types(self):
        buf = (
            _ntype(TAG_COMPOUND)
            + _nint("a", -1)
            + _nint("b", 0)
            + _nstring("c", "hello")
            + _ncomp_end()
        )
        result = parse_nbt(buf)
        assert result == {"a": -1, "b": 0, "c": "hello"}

    def test_nested_compound(self):
        """compound 里嵌套 compound"""
        inner_payload = _nint("x", 99) + bytes([TAG_END])  # inner compound 内容 + END
        nb_inner = b"inner"
        inner_tag = bytes([TAG_COMPOUND]) + struct.pack(">H", len(nb_inner)) + nb_inner + inner_payload

        nb_outer = b"outer"
        buf = (
            _ntype(TAG_COMPOUND)
            + bytes([TAG_COMPOUND]) + struct.pack(">H", len(nb_outer)) + nb_outer + inner_tag
            + bytes([TAG_END])  # outer compound END
            + bytes([TAG_END])  # root compound END
        )
        result = parse_nbt(buf)
        assert result["outer"]["inner"]["x"] == 99

    def test_long_value(self):
        big = 2**33  # 超过 32 位
        nb = b"v"
        buf = (
            _ntype(TAG_COMPOUND)
            + bytes([TAG_LONG]) + struct.pack(">H", len(nb)) + nb + struct.pack(">q", big)
            + bytes([TAG_END])
        )
        result = parse_nbt(buf)
        assert result["v"] == big

    def test_list_of_ints(self):
        list_payload = bytes([TAG_INT]) + struct.pack(">i", 3) + struct.pack(">i", 10) + struct.pack(">i", 20) + struct.pack(">i", 30)
        nb = b"nums"
        buf = (
            _ntype(TAG_COMPOUND)
            + bytes([TAG_LIST]) + struct.pack(">H", len(nb)) + nb + list_payload
            + bytes([TAG_END])
        )
        result = parse_nbt(buf)
        assert result["nums"] == [10, 20, 30]

    def test_string_value(self):
        nb = b"name"
        buf = (
            _ntype(TAG_COMPOUND)
            + bytes([TAG_STRING]) + struct.pack(">H", len(nb)) + nb
            + struct.pack(">H", 10) + b"test_block"
            + bytes([TAG_END])
        )
        result = parse_nbt(buf)
        assert result["name"] == "test_block"

    def test_long_array_returns_dict_with_buffer(self):
        """LongArray 解析为 {isZeroCopyLongArray, buffer, offset, length}"""
        count = 2
        longs = struct.pack(">q", 100) + struct.pack(">q", 200)
        nb = b"arr"
        buf = (
            _ntype(TAG_COMPOUND)
            + bytes([12]) + struct.pack(">H", len(nb)) + nb + struct.pack(">i", count) + longs  # TAG_LONG_ARRAY
            + bytes([TAG_END])
        )
        result = parse_nbt(buf)
        assert "arr" in result
        arr = result["arr"]
        assert arr["isZeroCopyLongArray"] is True
        assert arr["length"] == 2
        assert isinstance(arr["buffer"], (bytes, bytearray))
