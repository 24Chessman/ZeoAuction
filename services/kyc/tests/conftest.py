import pytest

from tests.support import Harness


@pytest.fixture
def harness() -> Harness:
    return Harness()
