"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_main():
    path = Path(__file__).parents[2] / "services" / "core-api" / "main.py"
    spec = spec_from_file_location("nexuss_core_main", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_health_live() -> None:
    module = _load_main()
    assert module.health_live() == {"status": "alive"}


def test_health_ready() -> None:
    module = _load_main()
    assert module.health_ready()["mode"] == "foundation"
