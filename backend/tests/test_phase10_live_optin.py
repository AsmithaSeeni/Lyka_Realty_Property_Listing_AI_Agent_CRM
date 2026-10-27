"""Phase 10 — live-provider tests are deselected by default (opt-in only).

Proves the conftest `pytest_collection_modifyitems` contract directly:
- without RUN_LIVE_TESTS (default), `live`/`live_openai` items get a skip
  marker with a clear reason — even when API keys exist in the environment;
- with RUN_LIVE_TESTS=1, items are left untouched (credential checks inside
  the live modules provide the second, independent guard).
"""

import os

import pytest


class _StubItem:
    def __init__(self, keywords):
        self.keywords = keywords
        self.added = []

    def add_marker(self, marker):
        self.added.append(marker)


class _StubConfig:
    pass


def test_live_items_skipped_by_default(monkeypatch):
    import conftest

    monkeypatch.delenv("RUN_LIVE_TESTS", raising=False)
    live_item = _StubItem({"live_openai": True, "call": True})
    normal_item = _StubItem({"call": True})
    conftest.pytest_collection_modifyitems(_StubConfig(),
                                           [live_item, normal_item])
    assert len(live_item.added) == 1
    reason = str(live_item.added[0].kwargs["reason"])
    assert "RUN_LIVE_TESTS=1" in reason
    assert "offline" in reason
    assert normal_item.added == [], "ordinary tests must never be skipped"


def test_live_marker_also_covered(monkeypatch):
    import conftest

    monkeypatch.delenv("RUN_LIVE_TESTS", raising=False)
    item = _StubItem({"live": True})
    conftest.pytest_collection_modifyitems(_StubConfig(), [item])
    assert len(item.added) == 1


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
def test_opt_in_env_disables_skipping(monkeypatch, value):
    import conftest

    monkeypatch.setenv("RUN_LIVE_TESTS", value)
    item = _StubItem({"live_openai": True})
    conftest.pytest_collection_modifyitems(_StubConfig(), [item])
    assert item.added == [], "opt-in must leave live items runnable"


def test_live_test_module_still_declares_credential_guard():
    """Second, independent guard: the live module keeps its key-based skipif,
    so opting in WITHOUT a key yields a clear skip, not a network attempt."""
    import pathlib

    src = (pathlib.Path(__file__).parent / "test_phase3_live_openai.py").read_text(
        encoding="utf-8")
    assert "skipif" in src and "OPENAI_API_KEY" in src
    assert "live_openai" in src
