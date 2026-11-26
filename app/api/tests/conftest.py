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


@pytest.fixture(autouse=True)
def _fresh_live_settings():
    """live.py keeps the settings for a few seconds; each test starts with them read afresh."""
    from worldmodel_api import live

    live.forget_settings()
    yield
    live.forget_settings()
