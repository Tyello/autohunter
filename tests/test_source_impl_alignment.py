from app.services.source_impl_alignment import evaluate_source_impl_alignment


def _eval(configured_impl, runtime_impl, *, canary_effective=False):
    return evaluate_source_impl_alignment(
        source="anysource",
        configured_impl=configured_impl,
        last_runtime_impl=runtime_impl,
        canary_enabled=canary_effective,
        canary_effective=canary_effective,
    )


def test_configured_v2_runtime_v2_ok():
    out = _eval("v2", "v2")
    assert out["impl_alignment"] == "ok"
    assert out["expected_runtime_impl"] == "v2"


def test_configured_v2_runtime_v1_warns():
    out = _eval("v2", "v1")
    assert out["impl_alignment"] == "warning"
    assert out["impl_alignment_reason"] == "configured_v2_but_runtime_v1"


def test_configured_v2_runtime_v2_canary_warns():
    out = _eval("v2", "v2_canary")
    assert out["impl_alignment"] == "warning"
    assert out["impl_alignment_reason"] == "configured_v2_but_runtime_v2_canary"


def test_configured_v1_canary_effective_runtime_v2_canary_ok():
    out = _eval("v1", "v2_canary", canary_effective=True)
    assert out["impl_alignment"] == "ok"
    assert out["expected_runtime_impl"] == "v2_canary"


def test_configured_v1_canary_effective_runtime_v1_warns():
    out = _eval("v1", "v1", canary_effective=True)
    assert out["impl_alignment"] == "warning"
    assert out["impl_alignment_reason"] == "canary_effective_but_runtime_v1"


def test_configured_v1_canary_disabled_runtime_v1_ok():
    out = _eval("v1", "v1", canary_effective=False)
    assert out["impl_alignment"] == "ok"
    assert out["expected_runtime_impl"] == "v1"


def test_configured_v1_canary_disabled_runtime_v2_warns():
    out = _eval("v1", "v2", canary_effective=False)
    assert out["impl_alignment"] == "warning"
    assert out["impl_alignment_reason"] == "configured_v1_but_runtime_v2"


def test_runtime_missing_is_unknown():
    out = _eval("v2", None)
    assert out["impl_alignment"] == "unknown"
    assert out["impl_alignment_reason"] == "runtime_impl_missing"
