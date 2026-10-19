"""Focused tests for the standalone SVG benchmark renderer."""
import json
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import visualize


class VisualizeTests(unittest.TestCase):
    def test_performance_groups_scenarios_rounds_and_failures(self):
        rows = [
            {"scenario": "election", "nodes": 3, "round": 1, "result": "PASS", "elapsed_seconds": 2.0},
            {"scenario": "election", "nodes": 3, "round": 2, "result": "PASS", "elapsed_seconds": 4.0},
            {"scenario": "election", "nodes": 3, "round": 3, "result": "FAIL", "elapsed_seconds": 100.0},
            {"scenario": "election", "nodes": 5, "round": 1, "result": "FAIL", "elapsed_seconds": None},
            {"scenario": "catchup", "nodes": 3, "round": 1, "result": "PASS", "elapsed_seconds": 1.0},
        ]
        svg = visualize.performance_svg(rows, None)
        ET.fromstring(svg)
        self.assertIn("2/3 pass", svg)
        self.assertIn("no successful timing", svg)
        self.assertIn("catchup", svg)
        self.assertIn("3.000s", svg)
        self.assertNotIn("100.0", svg)

    def test_batch_size_separates_groups(self):
        rows = [
            {"scenario": "run", "nodes": 3, "batch_size": 10, "result": "PASS", "elapsed_seconds": 1},
            {"scenario": "run", "nodes": 3, "batch_size": 20, "result": "PASS", "elapsed_seconds": 2},
        ]
        svg = visualize.performance_svg(rows, None)
        self.assertEqual(svg.count("b10"), 1)
        self.assertIn("b20", svg)
        self.assertEqual(len(visualize.group_rows(rows)), 2)

    def test_zero_timing_and_missing_batch_group(self):
        rows = [dict(scenario='x', nodes=3, batch_size=64, result='PASS', elapsed_seconds=0),
                dict(scenario='x', nodes=5, batch_size=128, result='FAIL', elapsed_seconds=None)]
        ET.fromstring(visualize.performance_svg(rows, None))

    def test_timeline_uses_offsets_and_marks_missing_events(self):
        self.assertIn("no events recorded", visualize.timeline_svg([]))
        svg = visualize.timeline_svg([({"scenario": "x<&", "nodes": 3, "round": 1}, [
            {"event": "processes_started", "offset_seconds": 1.25},
            {"event": "converged", "offset_seconds": 2.5},
        ])])
        ET.fromstring(svg)
        self.assertIn("1.25", svg)
        self.assertIn("not protocol-exact", svg)

    def test_cli_writes_outputs_and_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input"
            (source / "benchmark").mkdir(parents=True)
            (source / "benchmark" / "results.json").write_text(json.dumps([
                {"scenario": "a&b", "nodes": 3, "round": 1, "result": "PASS", "elapsed_seconds": 2}
            ]), encoding="utf-8")
            (source / "benchmark" / "environment.json").write_text('{"platform":"test"}', encoding="utf-8")
            dest = root / "out"
            self.assertEqual(visualize.main(["--input", str(source), "--output", str(dest)]), 0)
            self.assertEqual({p.name for p in dest.iterdir()}, {"performance.svg", "timeline.svg", "index.md"})
            ET.parse(dest / "performance.svg")
            ET.parse(dest / "timeline.svg")
            self.assertIn("not recorded", (dest / "index.md").read_text(encoding="utf-8"))
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                visualize.main(["--input", str(source), "--output", str(dest)])


if __name__ == "__main__":
    unittest.main()
