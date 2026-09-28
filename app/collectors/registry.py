from __future__ import annotations

from app.collectors.base import SourceUnavailable, TeamRef
from app.collectors.fixture import FixtureAdapter
from app.collectors.http import PoliteFetcher
from app.collectors.sidearm import SidearmAdapter
from app.settings import get_settings

_fetcher: PoliteFetcher | None = None
_fixture: FixtureAdapter | None = None


def shared_fetcher() -> PoliteFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = PoliteFetcher()
    return _fetcher


def fixture_adapter() -> FixtureAdapter:
    global _fixture
    if _fixture is None:
        _fixture = FixtureAdapter()
    return _fixture


def set_fixture_adapter(a: FixtureAdapter | None) -> None:
    """Test hook."""
    global _fixture
    _fixture = a


def get_adapter(adapter_name: str, team: TeamRef):
    s = get_settings()
    if s.test_mode:
        fx = fixture_adapter()
        if fx.has(team):
            return fx
        raise SourceUnavailable(team.base_url, "TEST_MODE: no saved fixture for this team (live fetching disabled)")
    if adapter_name == "sidearm":
        return SidearmAdapter(shared_fetcher())
    if adapter_name == "fixture":
        return fixture_adapter()
    raise SourceUnavailable(team.base_url, f"no adapter named '{adapter_name}'")
