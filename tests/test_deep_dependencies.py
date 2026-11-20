from __future__ import annotations
import sys
import shutil
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from parser import VerilogASTParser
from dependency_resolver import DependencyResolver

class DeepDependencyTests(unittest.TestCase):
    """
    Tests advanced dependency resolution:
    - Multi-level submodule hierarchies (A -> B -> C)
    - Diamond/shared submodules (A -> B & C, B -> D, C -> D)
    - Include files (`include "defs.vh"`)
    - Circular dependency detection
    - Missing dependency reporting
    """

    def setUp(self):
        self.parser = VerilogASTParser()
        self.temp_dir = Path(tempfile.mkdtemp(prefix="rtl_test_dep_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_three_level_dependency_chain(self):
        """Top -> Middle -> Leaf. Ordered files must be [Leaf, Middle, Top]."""
        leaf_file = self.temp_dir / "leaf.v"
        leaf_file.write_text("module leaf (input wire in, output wire out); assign out = ~in; endmodule")

        mid_file = self.temp_dir / "middle.v"
        mid_file.write_text("module middle (input wire in, output wire out); leaf u1 (.in(in), .out(out)); endmodule")

        top_file = self.temp_dir / "top.v"
        top_file.write_text("module top (input wire in, output wire out); middle u2 (.in(in), .out(out)); endmodule")

        all_mods = {}
        for f in (leaf_file, mid_file, top_file):
            for m in self.parser.parse_file(f):
                all_mods[m.name] = m

        resolver = DependencyResolver(all_mods)
        res = resolver.resolve_dependencies(all_mods["top"])

        # Dependencies for 'top' are middle and leaf (top itself is not in required_source_files)
        dep_names = [f.name for f in res.required_source_files]
        self.assertIn("leaf.v", dep_names)
        self.assertIn("middle.v", dep_names)
        # Leaf must precede Middle in compilation order
        self.assertLess(dep_names.index("leaf.v"), dep_names.index("middle.v"))
        self.assertEqual(len(res.missing_dependencies), 0)
        self.assertEqual(len(res.circular_dependencies), 0)

    def test_shared_diamond_dependency(self):
        """Diamond: Top -> Left, Right; Left -> Base; Right -> Base. Base must appear once, first."""
        base_file = self.temp_dir / "base.v"
        base_file.write_text("module base; endmodule")

        left_file = self.temp_dir / "left.v"
        left_file.write_text("module left; base b1 (); endmodule")

        right_file = self.temp_dir / "right.v"
        right_file.write_text("module right; base b2 (); endmodule")

        top_file = self.temp_dir / "top_diamond.v"
        top_file.write_text("module top_diamond; left l (); right r (); endmodule")

        all_mods = {}
        for f in (base_file, left_file, right_file, top_file):
            for m in self.parser.parse_file(f):
                all_mods[m.name] = m

        resolver = DependencyResolver(all_mods)
        res = resolver.resolve_dependencies(all_mods["top_diamond"])

        dep_names = [f.name for f in res.required_source_files]
        self.assertEqual(dep_names.count("base.v"), 1, "Base must appear exactly once")
        self.assertEqual(dep_names[0], "base.v", "Base must be compiled first")
        self.assertIn("left.v", dep_names)
        self.assertIn("right.v", dep_names)

    def test_missing_dependency_reported(self):
        """When an instantiated submodule is nowhere in the codebase, report it."""
        top_file = self.temp_dir / "top_missing.v"
        top_file.write_text("module top_missing; non_existent_submod u_missing (); endmodule")

        mods = self.parser.parse_file(top_file)
        resolver = DependencyResolver({m.name: m for m in mods})
        res = resolver.resolve_dependencies(mods[0])

        self.assertIn("non_existent_submod", res.missing_dependencies)

    def test_circular_dependency_detected(self):
        """Cycle: ModA instantiates ModB, ModB instantiates ModA."""
        mod_a_file = self.temp_dir / "mod_a.v"
        mod_a_file.write_text("module mod_a; mod_b u_b (); endmodule")

        mod_b_file = self.temp_dir / "mod_b.v"
        mod_b_file.write_text("module mod_b; mod_a u_a (); endmodule")

        all_mods = {}
        for f in (mod_a_file, mod_b_file):
            for m in self.parser.parse_file(f):
                all_mods[m.name] = m

        resolver = DependencyResolver(all_mods)
        res = resolver.resolve_dependencies(all_mods["mod_a"])

        self.assertTrue(len(res.circular_dependencies) > 0, "Circular dependency must be detected")
        cycle = res.circular_dependencies[0]
        self.assertIn("mod_a", cycle)
        self.assertIn("mod_b", cycle)

if __name__ == "__main__":
    unittest.main()
