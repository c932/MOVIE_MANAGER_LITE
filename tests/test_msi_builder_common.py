import sys
from pathlib import Path

import pytest


PACKAGING_DIR = Path(__file__).resolve().parents[1] / "packaging"
if str(PACKAGING_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGING_DIR))

import msi_builder_common as builder
from build_game_msi import GAME_CONFIG
from build_msi import MOVIE_CONFIG


def _config(root: Path) -> builder.ProductConfig:
    return builder.ProductConfig(
        root=root,
        product_name="Fixture App",
        product_name_cn="Fixture App",
        manufacturer="FixtureMaker",
        upgrade_code="{11111111-2222-3333-4444-555555555555}",
        distribution_name="FixtureApp",
        executable_name="FixtureApp.exe",
        install_subdir="FixtureApp",
        app_data_dir="FixtureApp",
        output_prefix="fixture-app",
        menu_folder="FixtureApp",
        shortcut_prefix="FixtureApp",
        default_version="1.3.0",
    )


def _sequence_number(db, action: str) -> int:
    row = builder._single_row(
        db,
        "SELECT `Sequence` FROM `InstallExecuteSequence` "
        f"WHERE `Action` = '{action}'",
    )
    assert row is not None
    return row.GetInteger(1)


def _file_names(db) -> set[str]:
    view = db.OpenView("SELECT `FileName` FROM `File`")
    view.Execute(None)
    names = set()
    while row := view.Fetch():
        names.add(row.GetString(1).split("|")[-1])
    view.Close()
    return names


def test_validate_version_accepts_msi_three_part_versions():
    assert builder.validate_version("1.3.0") == "1.3.0"
    assert builder.validate_version("10.20.30") == "10.20.30"


@pytest.mark.parametrize("version", ["1", "1.2", "1.2.3.4", "01.2.3", "v1.2.3"])
def test_validate_version_rejects_invalid_msi_versions(version):
    with pytest.raises(ValueError):
        builder.validate_version(version)


def test_msi_ids_are_ascii_deterministic_and_collision_resistant():
    first = builder._msi_id("Dir", "plugins/a-b")
    second = builder._msi_id("Dir", "plugins/a:b")

    assert first == builder._msi_id("Dir", "plugins/a-b")
    assert first != second
    assert len(first) <= 68
    assert first.replace("_", "").isalnum()


def test_product_configs_keep_upgrade_chains_separate():
    assert GAME_CONFIG.upgrade_code != MOVIE_CONFIG.upgrade_code
    assert GAME_CONFIG.app_data_dir != MOVIE_CONFIG.app_data_dir
    assert GAME_CONFIG.distribution_name != MOVIE_CONFIG.distribution_name


def test_build_creates_upgradeable_msi_with_full_payload(tmp_path):
    config = _config(tmp_path)
    payload = config.dist_dir
    nested = payload / "assets" / "nested"
    nested.mkdir(parents=True)
    (payload / config.executable_name).write_bytes(b"fixture executable")
    (payload / "top-level.txt").write_text("top", encoding="utf-8")
    (nested / "payload.dat").write_bytes(b"payload")

    output = builder.build_product(config, "1.3.0")

    assert output.is_file()
    db = builder.msilib.OpenDatabase(str(output), builder.msilib.MSIDBOPEN_READONLY)
    try:
        assert _sequence_number(db, "FindRelatedProducts") < _sequence_number(
            db, "SetInstallDirFromPrevious"
        )
        assert _sequence_number(db, "SetInstallDirFromPrevious") < _sequence_number(
            db, "SetInstallDirFromPrevious64"
        )
        assert _sequence_number(db, "SetInstallDirFromPrevious64") < _sequence_number(
            db, "RemoveExistingProducts"
        )
        assert _sequence_number(db, "RemoveExistingProducts") < _sequence_number(db, "InstallFiles")
        assert _sequence_number(db, "SetArpInstallLocation") < _sequence_number(
            db, "RegisterProduct"
        )
        assert _file_names(db) == {config.executable_name, "top-level.txt", "payload.dat"}
        assert builder._single_row(
            db,
            "SELECT `Registry` FROM `Registry` "
            "WHERE `Registry` = 'InstallDirRegistry'",
        ) is not None
        for action in ("SetInstallDirFromPrevious", "SetInstallDirFromPrevious64",
                       "SetArpInstallLocation"):
            assert builder._single_row(
                db,
                "SELECT `Action` FROM `CustomAction` "
                f"WHERE `Action` = '{action}'",
            ) is not None
        for signature in ("PreviousInstallDir", "PreviousInstallDir64"):
            row = builder._single_row(
                db,
                "SELECT `Type` FROM `RegLocator` "
                f"WHERE `Signature_` = '{signature}'",
            )
            assert row is not None
        secure = builder._single_row(
            db,
            "SELECT `Value` FROM `Property` WHERE `Property` = 'SecureCustomProperties'",
        )
        assert secure is not None
        secure_value = secure.GetString(1)
        assert "PREVIOUSINSTALLDIR" in secure_value
        assert "PREVIOUSINSTALLDIR64" in secure_value
        progress_dialog = builder._single_row(
            db,
            "SELECT `Attributes` FROM `Dialog` WHERE `Dialog` = 'ProgressDlg'",
        )
        assert progress_dialog is not None
        assert progress_dialog.GetInteger(1) == 1
        assert builder._single_row(
            db,
            "SELECT `Event` FROM `ControlEvent` "
            "WHERE `Dialog_` = 'ProgressDlg' AND `Control_` = 'Cancel' "
            "AND `Event` = 'SpawnDialog' AND `Argument` = 'CancelDlg'",
        ) is not None
    finally:
        del db
