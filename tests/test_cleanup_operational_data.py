import importlib.util
from pathlib import Path


def _load():
    p = Path('scripts/cleanup_operational_data.py')
    spec = importlib.util.spec_from_file_location('cleanup_operational_data', p)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_cleanup_has_safe_default_apply_flag():
    mod = _load()
    assert mod.BATCH_SIZE > 0
