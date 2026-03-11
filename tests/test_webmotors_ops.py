from app.scrapers.base import FetchBlocked
from app.scrapers.webmotors_ops import classify_webmotors_error, encode_webmotors_diag, extract_webmotors_diag


def test_classify_proxy_net_blocked_buckets():
    d_proxy = classify_webmotors_error(Exception("proxy connect failed: tunnel 407"), stage="browser_fetch", fetch_path="browser_proxy", attempt=1)
    assert d_proxy.bucket == "PROXY"

    d_net = classify_webmotors_error(Exception("dns timeout name or service not known"), stage="browser_fetch", fetch_path="browser_direct", attempt=2)
    assert d_net.bucket == "NET"

    d_block = classify_webmotors_error(Exception("HTTP 403 perimeterx challenge"), stage="browser_fetch", fetch_path="browser_direct", attempt=3)
    assert d_block.bucket == "BLOCKED"


def test_diag_roundtrip():
    diag = classify_webmotors_error(Exception("selector parse failed"), stage="parse_listings", fetch_path="browser_direct", attempt=2)
    enc = encode_webmotors_diag(diag)
    out = extract_webmotors_diag(f"RuntimeError: {enc}")
    assert out is not None
    assert out["bucket"] == "PARSER"
    assert out["stage"] == "parse_listings"


def test_classify_fetchblocked_as_blocked():
    diag = classify_webmotors_error(
        FetchBlocked(403, "https://www.webmotors.com.br/carros/estoque", reason="bot_challenge"),
        stage="browser_fetch",
        fetch_path="browser_direct",
        attempt=1,
    )
    assert diag.bucket == "BLOCKED"
    assert diag.blocked_likely is True


def test_classify_browser_error_bucket():
    diag = classify_webmotors_error(
        RuntimeError("Playwright Target page, context or browser has been closed"),
        stage="browser_fetch",
        fetch_path="browser_direct",
        attempt=2,
    )
    assert diag.bucket == "BROWSER"


def test_classification_with_unprintable_exception_never_breaks():
    class BrokenExc(Exception):
        def __str__(self):
            raise RuntimeError("broken_str")

    diag = classify_webmotors_error(
        BrokenExc(),
        stage="browser_fetch",
        fetch_path="browser_direct",
        attempt=3,
    )
    assert diag.bucket == "UNKNOWN"
    assert diag.reason in {"unclassified_failure", "diagnostic_mapping_error"}
    assert "BrokenExc" in diag.evidence
