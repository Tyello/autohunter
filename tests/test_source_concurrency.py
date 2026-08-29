"""
Tests for app.services.source_concurrency module.
Etapa 2: Testes de semáforo por-source
"""

import pytest

from app.services.source_concurrency import get_source_semaphore, _semaphores, _lock


@pytest.fixture(autouse=True)
def clear_semaphore_cache():
    """Clear the semaphore cache before each test."""
    with _lock:
        _semaphores.clear()
    yield
    with _lock:
        _semaphores.clear()


class TestSourceConcurrency:
    def test_same_source_returns_same_instance(self):
        """(a) Calling get_source_semaphore("olx") twice returns the same instance."""
        semaphore1 = get_source_semaphore("olx")
        semaphore2 = get_source_semaphore("olx")
        assert semaphore1 is semaphore2

    def test_normalized_case_insensitive(self):
        """(b) Calling with "OLX" and "olx" returns the same instance (case-insensitive)."""
        semaphore_upper = get_source_semaphore("OLX")
        semaphore_lower = get_source_semaphore("olx")
        assert semaphore_upper is semaphore_lower

    def test_different_sources_different_instances(self):
        """(c) Different sources get different semaphore instances."""
        semaphore_olx = get_source_semaphore("olx")
        semaphore_webmotors = get_source_semaphore("webmotors")
        assert semaphore_olx is not semaphore_webmotors

    def test_semaphore_size_from_settings(self, monkeypatch):
        """
        (d) When settings.source_max_concurrent_per_source is 3,
        a new semaphore for a fresh source should have capacity 3.
        Verify by acquiring 3 times (should succeed) and 4th should fail.
        """
        # Monkeypatch settings before creating the semaphore
        monkeypatch.setattr("app.services.source_concurrency.settings", type("MockSettings", (), {"source_max_concurrent_per_source": 3})())

        # Create a new semaphore for a source that doesn't exist yet
        semaphore = get_source_semaphore("mercadolivre_test_size")

        # Acquire 3 times - should all succeed
        assert semaphore.acquire(blocking=False) is True, "1st acquire should succeed"
        assert semaphore.acquire(blocking=False) is True, "2nd acquire should succeed"
        assert semaphore.acquire(blocking=False) is True, "3rd acquire should succeed"

        # 4th acquire should fail because we hit the capacity
        assert semaphore.acquire(blocking=False) is False, "4th acquire should fail (capacity exceeded)"

    def test_normalized_with_whitespace(self):
        """Test that leading/trailing whitespace is stripped during normalization."""
        semaphore1 = get_source_semaphore("  olx  ")
        semaphore2 = get_source_semaphore("olx")
        assert semaphore1 is semaphore2

    def test_normalized_mixed_case_and_whitespace(self):
        """Test normalization with both case and whitespace."""
        semaphore1 = get_source_semaphore("  OLX  ")
        semaphore2 = get_source_semaphore("olx")
        assert semaphore1 is semaphore2

    def test_none_source_normalized(self):
        """Test that None source is normalized to empty string."""
        semaphore1 = get_source_semaphore(None)
        semaphore2 = get_source_semaphore("")
        assert semaphore1 is semaphore2

    def test_minimum_size_is_one(self, monkeypatch):
        """Test that semaphore size is at least 1 even if settings is 0 or negative."""
        # Monkeypatch settings to 0
        monkeypatch.setattr("app.services.source_concurrency.settings", type("MockSettings", (), {"source_max_concurrent_per_source": 0})())

        # Create a new semaphore
        semaphore = get_source_semaphore("minimum_size_test")

        # Should be able to acquire at least once
        assert semaphore.acquire(blocking=False) is True, "Should be able to acquire once (minimum size is 1)"
        # Should NOT be able to acquire a second time
        assert semaphore.acquire(blocking=False) is False, "Should not be able to acquire twice (size is 1)"
