from app.updates import (
    GITHUB_OWNER,
    GITHUB_REPO,
    build_latest_release_api_url,
    build_latest_release_web_url,
    is_newer_version,
)


def test_is_newer_version_detects_patch_bump() -> None:
    assert is_newer_version("1.5.0", "1.5.1")
    assert not is_newer_version("1.5.1", "1.5.0")


def test_is_newer_version_detects_major_bump() -> None:
    assert is_newer_version("1.5.0", "2.0.0")
    assert not is_newer_version("2.0.0", "1.9.9")


def test_is_newer_version_handles_v_prefix() -> None:
    assert is_newer_version("1.0.0", "v1.0.1")


def test_is_newer_version_rejects_unknown_formats() -> None:
    assert not is_newer_version("1.0.0", "latest")
    assert not is_newer_version("dev", "1.0.0")


def test_github_repo_constants() -> None:
    assert GITHUB_OWNER == "SebastianArnesen"
    assert GITHUB_REPO == "Map_Data_Fetcher"


def test_build_release_urls() -> None:
    assert build_latest_release_api_url(owner="o", repo="r") == (
        "https://api.github.com/repos/o/r/releases/latest"
    )
    assert build_latest_release_web_url(owner="o", repo="r") == (
        "https://github.com/o/r/releases/latest"
    )
