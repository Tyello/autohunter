from app.health.classify import classify_error
from app.health.models import RunStatus


class HttpError(Exception):
    def __init__(self, status_code: int, message: str = "boom"):
        super().__init__(message)
        self.status_code = status_code


def test_classify_error_status_and_buckets():
    c403 = classify_error(HttpError(403, "forbidden"))
    assert c403[1] == RunStatus.BLOCKED
    assert c403[4] == "blocked_403"

    c429 = classify_error(HttpError(429, "rate limit"))
    assert c429[1] == RunStatus.BLOCKED
    assert c429[4] == "blocked_429"

    cproxy = classify_error(Exception("proxy connect failed"))
    assert cproxy[1] == RunStatus.PROXY
    assert cproxy[4] == "proxy_error"

    ctimeout = classify_error(Exception("request timeout after 10s"))
    assert ctimeout[1] == RunStatus.NET
    assert ctimeout[4] == "timeout"

    cparse = classify_error(Exception("selector parse failed"))
    assert cparse[1] == RunStatus.PARSE
    assert cparse[4] == "parse_error"
