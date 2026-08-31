"""extract_block_indices 位索引提取测试"""
import struct

from mod.ezmatic.main import extract_block_indices


class TestExtractBlockIndices:
    def test_single_block_2bits(self):
        """1 个方块,2 bits — palette 索引 0"""
        # total_blocks=1, bits_per_index=2, 1 long = 8 bytes
        buf = struct.pack(">II", 0, 0)  # 全零 long
        block_states = {"buffer": buf, "offset": 0, "length": 1}
        result = extract_block_indices(block_states, 1, 2)
        assert result == [0]

    def test_two_blocks_2bits(self):
        """2 个方块,palette 索引 [1, 2]"""
        # bit layout (2 bits each): [01, 10] 在一个 long 低 4 位
        # 源码: words[0] = lo (buf后4B), words[1] = hi (buf前4B)
        buf = struct.pack(">II", 0, 9)  # hi=0, lo=9 → words[0]=9
        block_states = {"buffer": buf, "offset": 0, "length": 1}
        result = extract_block_indices(block_states, 2, 2)
        assert result == [1, 2]

    def test_four_blocks_3bits(self):
        """4 个方块,3 bits each — palette [0, 1, 2, 3]"""
        # bit layout: 000|001|010|011 = 0b011_010_001_000 = 0x118 (280)
        val = (0) | (1 << 3) | (2 << 6) | (3 << 9)
        buf = struct.pack(">II", 0, val)  # words[0] = val
        block_states = {"buffer": buf, "offset": 0, "length": 1}
        result = extract_block_indices(block_states, 4, 3)
        assert result == [0, 1, 2, 3]

    def test_cross_word_boundary(self):
        """索引跨越 32 位 word 边界: 12 blocks, 3 bits each = 36 bits"""
        # 所有索引值 = 1,跨 word 的是 block10 (bits 30-32)
        # word0 (lo): 索引 0-10 的前 2 位 → bit i*3 置位,共 bits 0-30
        # block10 = 1 → bit30=1, bit31=0, bit32(跨到word1)=0
        # word1 (hi): block11 (bits 33-35) 值 1 → bit1 置位 → words[1] = 0b10 = 2
        val0 = sum(1 << (i * 3) for i in range(11))  # bits 0,3,6,...,30
        buf = struct.pack(">II", 2, val0)  # hi=words[1]=2, lo=words[0]=val0
        block_states = {"buffer": buf, "offset": 0, "length": 1}
        result = extract_block_indices(block_states, 12, 3)
        assert result == [1] * 12

    def test_zero_palette(self):
        """所有方块都是 palette[0]（空气）"""
        buf = struct.pack(">II", 0, 0)
        block_states = {"buffer": buf, "offset": 0, "length": 1}
        result = extract_block_indices(block_states, 8, 2)
        assert result == [0] * 8

    def test_offset_not_zero(self):
        """buffer 有非零 offset"""
        # 前 8 字节填充垃圾, 真正数据在 offset=8
        garbage = b"\xff" * 8
        real_data = struct.pack(">II", 0, 0)
        buf = garbage + real_data
        block_states = {"buffer": buf, "offset": 8, "length": 1}
        result = extract_block_indices(block_states, 2, 2)
        assert result == [0, 0]
