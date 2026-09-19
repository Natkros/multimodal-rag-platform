from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.config import get_settings
from app.services.caching import cache as cache_module
from app.services.caching.cache import CacheNotConfiguredError, cache_get, cache_set, get_redis_client


def _settings(**overrides):
    return get_settings().model_copy(update=overrides)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._cached_redis_client.cache_clear()
    yield
    cache_module._cached_redis_client.cache_clear()


def test_get_redis_client_raises_without_redis_url():
    settings = _settings(redis_url=None)
    with pytest.raises(CacheNotConfiguredError):
        get_redis_client(settings)


def test_cache_get_delegates_to_redis_client():
    settings = _settings(redis_url="redis://localhost:6379/0")
    mock_client = MagicMock()
    mock_client.get.return_value = "cached-value"
    with patch.object(cache_module, "_cached_redis_client", return_value=mock_client):
        result = cache_get(settings, "some-key")
    assert result == "cached-value"
    mock_client.get.assert_called_once_with("some-key")


def test_cache_set_delegates_with_ttl():
    settings = _settings(redis_url="redis://localhost:6379/0", cache_ttl_seconds=120)
    mock_client = MagicMock()
    with patch.object(cache_module, "_cached_redis_client", return_value=mock_client):
        cache_set(settings, "some-key", "some-value")
    mock_client.set.assert_called_once_with("some-key", "some-value", ex=120)
