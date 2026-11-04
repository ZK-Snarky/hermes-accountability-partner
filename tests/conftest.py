"""Load the repo root as the package ``accountability_partner`` (Hermes loads it the same way)."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "accountability_partner", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
module = importlib.util.module_from_spec(spec)
sys.modules["accountability_partner"] = module
spec.loader.exec_module(module)
