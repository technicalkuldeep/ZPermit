import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.delenv("ZPERMIT_DATABASE_URL", raising=False)
    monkeypatch.delenv("ZPERMIT_CORS_ORIGINS", raising=False)


def test_safe_defaults():
    settings = Settings(_env_file=None)
    assert settings.database_url == "sqlite:///./zpermit.db"
    assert settings.cors_origins == []


def test_environment_overrides(monkeypatch):
    monkeypatch.setenv("ZPERMIT_DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("ZPERMIT_CORS_ORIGINS", '["https://app.example"]')
    settings = Settings(_env_file=None)
    assert settings.database_url == "sqlite:///./test.db"
    assert settings.cors_origins == ["https://app.example"]


def test_dotenv_and_environment_precedence(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        'ZPERMIT_DATABASE_URL=sqlite:///./local.db\n'
        'ZPERMIT_CORS_ORIGINS=["http://localhost:3000"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ZPERMIT_DATABASE_URL", "sqlite:///./override.db")
    settings = Settings(_env_file=env_file)
    assert settings.database_url == "sqlite:///./override.db"
    assert settings.cors_origins == ["http://localhost:3000"]


@pytest.mark.parametrize(
    "origin",
    ["*", "https://*.example", "ftp://example.com", "https://example.com/path",
     "https://user:secret@example.com", "https://example.com:invalid"],
)
def test_rejects_invalid_cors_origins(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins=[origin])


def test_rejects_empty_database_url():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=" ")
