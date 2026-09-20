"""tests/test_metrics.py — 系统资源指标与实时性能监控单元测试"""

import unittest
from lib.sys_metrics import MetricsCollector


class TestSysMetrics(unittest.TestCase):
    def test_collector_basic_sample(self):
        """测试指标采样器单次采样与环形队列"""
        collector = MetricsCollector(history_len=10, interval=0.1)
        point = collector.sample_once(clients_count=3)

        self.assertIn("time", point)
        self.assertIn("cpu", point)
        self.assertIn("proc_cpu", point)
        self.assertIn("mem_percent", point)
        self.assertIn("mem_used_mb", point)
        self.assertIn("mem_total_mb", point)
        self.assertIn("proc_mem_mb", point)
        self.assertEqual(point["clients"], 3)
        self.assertIsInstance(point["cpu"], float)
        self.assertIsInstance(point["mem_percent"], float)

        # 检查快照返回
        snap = collector.get_snapshot()
        self.assertTrue(snap["ok"])
        self.assertEqual(len(snap["history"]), 1)
        self.assertEqual(snap["current"]["clients"], 3)
        self.assertIn("system", snap)
        self.assertIn("platform", snap["system"])
        self.assertIn("cpu_count", snap["system"])

    def test_message_counter_throughput(self):
        """测试消息吞吐计数打点"""
        collector = MetricsCollector(history_len=5, interval=0.1)
        collector.record_message(5)
        collector.record_message(3)

        point = collector.sample_once()
        self.assertEqual(point["msg_rate"], 8.0)

        # 再次采样时计数器重置
        point2 = collector.sample_once()
        self.assertEqual(point2["msg_rate"], 0.0)

    def test_history_capacity_overflow(self):
        """测试超过 history_len 时队列保持最大长度"""
        collector = MetricsCollector(history_len=5, interval=0.1)
        for i in range(12):
            collector.sample_once(clients_count=i)

        snap = collector.get_snapshot()
        self.assertEqual(len(snap["history"]), 5)
        self.assertEqual(snap["current"]["clients"], 11)


if __name__ == "__main__":
    unittest.main()

