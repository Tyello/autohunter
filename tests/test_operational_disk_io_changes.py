import inspect

from app.services import autopilot_service
from app.services import source_configs_service


def test_autopilot_no_group_by_message() -> None:
    src = inspect.getsource(autopilot_service._candidate_system_log_errors)
    assert "group_by(SystemLog.component, SystemLog.message)" not in src


def test_source_config_cache_invalidation() -> None:
    source_configs_service._SOURCE_CONFIG_CACHE["olx"] = (source_configs_service._utcnow(), None)
    source_configs_service.invalidate_source_config_cache("olx")
    assert "olx" not in source_configs_service._SOURCE_CONFIG_CACHE
