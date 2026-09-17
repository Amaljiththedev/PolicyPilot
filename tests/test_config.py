import pytest
from app.core.config import Settings, settings


def test_settings_load_defaults_or_env():
    assert settings.DATABASE_URL is not None
    assert isinstance(settings.CHUNK_SIZE, int)
    assert settings.CHUNK_SIZE > 0
    assert isinstance(settings.TOP_K, int)
    assert settings.TOP_K > 0
    assert settings.JWT_SECRET is not None


def test_custom_settings_instantiation():
    custom_settings = Settings(
        DATABASE_URL="postgresql://user:pass@localhost:5432/testdb",
        CHUNK_SIZE=500,
        TOP_K=10,
        JWT_SECRET="testsecret"
    )
    assert custom_settings.DATABASE_URL == "postgresql://user:pass@localhost:5432/testdb"
    assert custom_settings.CHUNK_SIZE == 500
    assert custom_settings.TOP_K == 10
    assert custom_settings.JWT_SECRET == "testsecret"
