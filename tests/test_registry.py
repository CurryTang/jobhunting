import pytest

from jobhunter.sources.registry import PLATFORM_REGISTRY, build_platforms


def test_registry_tracks_planned_target_platforms():
    assert PLATFORM_REGISTRY["handshake"].status == "planned"


def test_linkedin_is_optional_jobspy_platform():
    assert PLATFORM_REGISTRY["linkedin"].status == "implemented-optional"
    assert build_platforms(["linkedin"])[0].name == "jobspy:linkedin"


def test_indeed_and_glassdoor_are_optional_jobspy_aggregators():
    for name in ("indeed", "glassdoor"):
        assert PLATFORM_REGISTRY[name].status == "implemented-optional"
    assert build_platforms(["indeed"])[0].name == "jobspy:indeed"
    assert build_platforms(["glassdoor"])[0].name == "jobspy:glassdoor"


def test_startup_boards_are_implemented():
    assert PLATFORM_REGISTRY["a16z"].status == "implemented"
    assert PLATFORM_REGISTRY["yc"].status == "implemented"
    assert [platform.name for platform in build_platforms(["a16z", "yc"])] == ["a16z", "yc"]


def test_build_platforms_rejects_planned_platforms():
    with pytest.raises(NotImplementedError):
        build_platforms(["handshake"])


def test_build_platforms_creates_implemented_platforms():
    platforms = build_platforms(["remotive", "hackernews"])

    assert [platform.name for platform in platforms] == ["remotive", "hackernews"]
