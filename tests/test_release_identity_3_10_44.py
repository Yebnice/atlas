from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_identity_is_consistent_across_runtime_and_android():
    config = (ROOT / "app/config.py").read_text()
    init = (ROOT / "app/__init__.py").read_text()
    android = (ROOT / "android/app/build.gradle.kts").read_text()
    assert 'app_version: str = "3.10.45"' in config
    assert '__version__ = "3.10.45"' in init
    assert 'versionCode = 1045' in android
    assert 'versionName = "3.10.45"' in android


def test_replay_schema_version_remains_independent():
    replay = (ROOT / "app/trade_learning.py").read_text()
    assert 'REPLAY_VERSION = "3.10.42-replay-v1"' in replay
