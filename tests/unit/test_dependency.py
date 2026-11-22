import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from models import ModuleInfo, InstanceInfo
from dependency_resolver import DependencyResolver

class DependencyTests(unittest.TestCase):
    def test_recursive_dependency_resolution(self):
        # Full adder (leaf)
        mod_fa = ModuleInfo(
            name="full_adder",
            file_path=Path("designs/common/full_adder.v"),
            ports={},
            instantiations=[]
        )
        # 4-bit ripple carry adder (instantiates full_adder)
        mod_rca = ModuleInfo(
            name="adder_rca",
            file_path=Path("designs/adder_rca.v"),
            ports={},
            instantiations=[
                InstanceInfo("fa0", "full_adder"),
                InstanceInfo("fa1", "full_adder"),
            ]
        )
        # Top chip (instantiates adder_rca)
        mod_top = ModuleInfo(
            name="top_chip",
            file_path=Path("designs/top_chip.v"),
            ports={},
            instantiations=[
                InstanceInfo("u_rca", "adder_rca")
            ]
        )

        all_mods = {
            "full_adder": mod_fa,
            "adder_rca": mod_rca,
            "top_chip": mod_top
        }

        resolver = DependencyResolver(all_mods)
        deps = resolver.resolve_dependencies(mod_top)
        # Should resolve adder_rca and full_adder
        dep_names = [p.name for p in deps]
        self.assertIn("adder_rca.v", dep_names)
        self.assertIn("full_adder.v", dep_names)

if __name__ == "__main__":
    unittest.main()
