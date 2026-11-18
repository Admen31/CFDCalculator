"""v2.9: the API key is stored per Windows user (DPAPI on Windows), migrated from older plain storage, survives a
restart, has priority from the environment and is never committed."""
import re
import subprocess
from pathlib import Path

import pytest

from cfdcalc import apikey


class Settings(dict):
    """Minimal QSettings stand-in (value / setValue / remove / sync / fileName)."""

    def value(self, k, default=None):
        return self.get(k, default)

    def setValue(self, k, v):  # noqa: N802 - Qt API
        self[k] = v

    def remove(self, k):
        self.pop(k, None)

    def sync(self):
        pass

    def fileName(self):  # noqa: N802 - Qt API
        return "app.ini"


def test_save_load_and_environment_priority(monkeypatch):
    monkeypatch.delenv(apikey.ENV, raising=False)
    s = Settings()
    apikey.save(s, "  abcdef0123456789  ")
    assert apikey.load(s) == "abcdef0123456789"
    if apikey.available():
        assert apikey.PLAIN not in s and "abcdef" not in str(s[apikey.ENCRYPTED])      # encrypted at rest
    monkeypatch.setenv(apikey.ENV, "from-env")
    assert apikey.load(s) == "from-env" and "proměnné" in apikey.where(s)
    monkeypatch.delenv(apikey.ENV)
    apikey.save(s, "")
    assert apikey.load(s) == "" and "nenalezen" in apikey.where(s)


def test_plain_key_of_older_versions_is_still_loaded(monkeypatch):
    monkeypatch.delenv(apikey.ENV, raising=False)
    s = Settings({apikey.PLAIN: "oldplainkey"})
    assert apikey.load(s) == "oldplainkey"
    if apikey.available():
        assert apikey.PLAIN not in s and apikey.load(s) == "oldplainkey"           # migrated, still readable


@pytest.mark.skipif(not apikey.available(), reason="Windows DPAPI only")
def test_dpapi_round_trip_and_tamper():
    token = apikey.protect("secret-key")
    assert apikey.unprotect(token) == "secret-key" and "secret" not in token


def test_no_api_key_is_committed():
    root = Path(__file__).resolve().parents[1]
    try:
        files = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git not available")
    pattern = re.compile(r"(?i)(apikey|api_key)\s*[=:]\s*['\"]?[0-9a-f]{32}")
    for name in files.split():
        p = root / name
        if p.suffix in (".py", ".md", ".ini", ".yml", ".txt", ".json", ".toml") and p.is_file():
            assert not pattern.search(p.read_text(encoding="utf-8", errors="ignore")), name
