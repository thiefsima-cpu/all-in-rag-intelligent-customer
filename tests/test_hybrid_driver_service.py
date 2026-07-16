from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rag_modules.retrieval.hybrid_driver_service import HybridDriverService


class _UnexpectedManagerAccess:
    @property
    def driver(self) -> object:
        raise AssertionError("manager driver must not be accessed")


class _FailingManagerLookup:
    def __init__(self, error: RuntimeError) -> None:
        self.error = error

    @property
    def driver(self) -> object:
        raise self.error


def test_ensure_driver_reuses_existing_driver_without_changing_ownership() -> None:
    existing = object()
    state = SimpleNamespace(driver=existing, owns_driver=True)

    result = HybridDriverService(
        storage=object(),
        neo4j_manager=_UnexpectedManagerAccess(),
    ).ensure_driver(state)

    assert result is existing
    assert state.driver is existing
    assert state.owns_driver is True


def test_ensure_driver_reuses_injected_manager_driver_without_taking_ownership() -> None:
    injected = object()
    state = SimpleNamespace(driver=None, owns_driver=True)
    service = HybridDriverService(
        storage=object(),
        neo4j_manager=SimpleNamespace(driver=injected),
    )

    result = service.ensure_driver(state)

    assert result is injected
    assert state.driver is injected
    assert state.owns_driver is False


def test_ensure_driver_requires_injected_manager() -> None:
    with pytest.raises(RuntimeError, match="injected Neo4j manager"):
        HybridDriverService(storage=object()).ensure_driver(
            SimpleNamespace(driver=None, owns_driver=False)
        )


def test_ensure_driver_propagates_manager_lookup_failure_without_changing_state() -> None:
    error = RuntimeError("driver unavailable")
    state = SimpleNamespace(driver=None, owns_driver=True)

    with pytest.raises(RuntimeError, match="driver unavailable") as exc_info:
        HybridDriverService(
            storage=object(),
            neo4j_manager=_FailingManagerLookup(error),
        ).ensure_driver(state)

    assert exc_info.value is error
    assert state.driver is None
    assert state.owns_driver is True


def test_close_closes_owned_non_empty_driver() -> None:
    driver = Mock()

    HybridDriverService.close(SimpleNamespace(driver=driver, owns_driver=True))

    driver.close.assert_called_once_with()


@pytest.mark.parametrize(
    ("driver", "owns_driver"),
    [(Mock(), False), (None, True)],
)
def test_close_skips_unowned_or_empty_driver(driver: Mock | None, owns_driver: bool) -> None:
    HybridDriverService.close(SimpleNamespace(driver=driver, owns_driver=owns_driver))

    if driver is not None:
        driver.close.assert_not_called()


def test_close_propagates_owned_driver_failure() -> None:
    error = RuntimeError("close failed")
    driver = Mock()
    driver.close.side_effect = error

    with pytest.raises(RuntimeError, match="close failed") as exc_info:
        HybridDriverService.close(SimpleNamespace(driver=driver, owns_driver=True))

    assert exc_info.value is error
    driver.close.assert_called_once_with()
