import os

# Test suite must choose an explicit safe environment rather than relying on
# Settings' production/staging fail-closed behavior.
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_trading.db")
os.environ.setdefault("BACKGROUND_RECONCILIATION_ENABLED", "false")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token-for-pytest-only")
