import pytest

from brain import db


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    """Every test file needs the schema, whichever file pytest happens to run first."""
    db.migrate()
