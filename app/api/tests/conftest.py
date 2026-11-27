"""Shared set-up for the API tests."""

import pytest

from worldmodel_api import tiles


@pytest.fixture(autouse=True, scope="session")
def _no_starter_tiles():
    """The app's start-up queues the starter map copies 30 seconds after any test that runs the
    app's lifespan (`with TestClient(...)`). Left on, that timer can fire in the middle of a later
    test and download through whatever that test put in place of the network (the tile tests
    count downloads), so it is switched off for the whole run."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(tiles, "start_starter", lambda: dict(tiles._job))
        yield


@pytest.fixture(autouse=True, scope="session")
def _no_forecast_scoring_loop():
    """The same for the forecast scoring rounds, which start a minute after the app does."""
    from worldmodel_api import forecast_skill

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(forecast_skill, "start", lambda settings_fn: None)
        from worldmodel_api import forecast_scores

        mp.setattr(forecast_scores, "start", lambda *a, **k: None)  # the back-tests worked out after each new build
        yield


@pytest.fixture(autouse=True)
def _fresh_live_settings():
    """live.py keeps the settings for a few seconds; each test starts with them read afresh."""
    from worldmodel_api import live

    live.forget_settings()
    yield
    live.forget_settings()


@pytest.fixture(autouse=True)
def _warehouse_put_back():
    """Some tests point the app at a warehouse of their own; the next test gets the one before.
    Run in parallel, tests land on workers in a different order each time, so a test left
    pointing at a small warehouse failed whichever test happened to follow it."""
    from worldmodel_api import core

    before = core.warehouse
    yield
    core.warehouse = before
