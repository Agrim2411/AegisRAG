import pytest

from aegis_rag.api import AppState
from aegis_rag.config import Settings


@pytest.fixture
def state(tmp_path):
    return AppState(Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}"))
