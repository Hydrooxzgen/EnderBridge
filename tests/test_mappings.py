"""load_mappings 映射表加载测试"""
from mod.ezmatic.main import load_mappings


class TestLoadMappings:
    def test_returns_dict(self):
        result = load_mappings()
        assert isinstance(result, dict)

    def test_has_fallback_map(self):
        result = load_mappings()
        assert "fallbackMap" in result
        assert isinstance(result["fallbackMap"], dict)

    def test_fallback_map_has_minecraft_prefix(self):
        result = load_mappings()
        for key in result["fallbackMap"]:
            assert key.startswith("minecraft:")

    def test_mapping_entries_have_required_keys(self):
        result = load_mappings()
        for key, val in result.items():
            if key == "fallbackMap":
                continue
            assert "identifier" in val, f"Missing 'identifier' in mapping for {key}"
            assert "state" in val, f"Missing 'state' in mapping for {key}"
            assert isinstance(val["state"], dict), f"State should be dict for {key}"

    def test_hardcoded_chain_exists(self):
        result = load_mappings()
        assert "minecraft:chain" in result["fallbackMap"]

    def test_hardcoded_grass_exists(self):
        result = load_mappings()
        assert "minecraft:grass" in result["fallbackMap"]
