from __future__ import annotations

from app.models_qt import dataset_padlock_tooltip, dataset_shows_padlock
from geonorge.catalog import _extract_access_flags
from geonorge.models import DatasetAvailability


def test_extract_access_flags_open_dataset() -> None:
    flags = _extract_access_flags(
        {
            "AccessIsOpendata": True,
            "AccessIsRestricted": False,
            "AccessIsProtected": False,
            "DataAccess": "Åpne data",
        }
    )
    assert flags.access_is_opendata is True
    assert flags.access_is_restricted is False
    assert flags.access_is_protected is False
    assert flags.data_access == "Åpne data"


def test_extract_access_flags_restricted_dataset() -> None:
    flags = _extract_access_flags(
        {
            "AccessIsOpendata": False,
            "AccessIsRestricted": True,
            "AccessIsProtected": False,
            "DataAccess": "Norge digitalt begrenset",
        }
    )
    assert flags.access_is_opendata is False
    assert flags.access_is_restricted is True
    assert flags.data_access == "Norge digitalt begrenset"


def test_extract_access_flags_is_open_data_alias() -> None:
    flags = _extract_access_flags({"IsOpenData": True})
    assert flags.access_is_opendata is True


def test_dataset_shows_padlock_for_restricted_and_login_required() -> None:
    restricted = DatasetAvailability(
        metadata_uuid="a",
        title="Restricted",
        access_is_restricted=True,
    )
    protected = DatasetAvailability(
        metadata_uuid="b",
        title="Protected",
        access_is_protected=True,
    )
    login = DatasetAvailability(metadata_uuid="c", title="Login", login_required=True)
    open_ds = DatasetAvailability(
        metadata_uuid="d",
        title="Open",
        access_is_opendata=True,
    )

    assert dataset_shows_padlock(restricted) is True
    assert dataset_shows_padlock(protected) is True
    assert dataset_shows_padlock(login) is True
    assert dataset_shows_padlock(open_ds) is False


def test_dataset_padlock_tooltip_prefers_data_access() -> None:
    ds = DatasetAvailability(
        metadata_uuid="a",
        title="Matrikkel",
        access_is_restricted=True,
        data_access="Norge digitalt begrenset",
    )
    assert dataset_padlock_tooltip(ds) == "Norge digitalt begrenset"


def test_dataset_padlock_tooltip_login_fallback() -> None:
    ds = DatasetAvailability(metadata_uuid="a", title="Secret", login_required=True)
    assert dataset_padlock_tooltip(ds) == "Krever innlogging"
