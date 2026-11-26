"""Tests that build a whole warehouse are marked `slow`, so the quick set (`pytest -m "not slow"`,
or `make quick`) runs everything else in under two minutes."""

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: builds a whole warehouse (left out of the quick set)")


def pytest_collection_modifyitems(config, items):
    for item in items:
        mod = getattr(item, "module", None)
        built = getattr(mod, "build", None)
        if built is not None and getattr(built, "__module__", "") == "worldmodel_data.build":
            item.add_marker(pytest.mark.slow)
