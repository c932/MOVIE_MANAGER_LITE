from __future__ import annotations

import hashlib
import re
import uuid
import warnings
from dataclasses import dataclass
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

try:
    import msilib
    from msilib import Dialog, add_data, schema, sequence
except ImportError as exc:
    raise RuntimeError("msilib is required; use Python 3.11 or 3.12 on Windows.") from exc


_VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


@dataclass(frozen=True)
class ProductConfig:
    root: Path
    product_name: str
    product_name_cn: str
    manufacturer: str
    upgrade_code: str
    distribution_name: str
    executable_name: str
    install_subdir: str
    app_data_dir: str
    output_prefix: str
    menu_folder: str
    shortcut_prefix: str
    default_version: str

    @property
    def dist_dir(self) -> Path:
        return self.root / "dist" / self.distribution_name

    @property
    def icon_path(self) -> Path:
        return self.root / "Movie_Manager_Lite.ico"

    def output_path(self, version: str) -> Path:
        return self.root / "dist" / f"{self.output_prefix}-{version}-win64.msi"


def validate_version(version: str) -> str:
    if not _VERSION_PATTERN.fullmatch(version):
        raise ValueError("MSI version must use three numeric components, for example 1.3.0.")
    return version


def _new_guid() -> str:
    return "{" + str(uuid.uuid4()).upper() + "}"


def _msi_id(prefix: str, value: str, max_length: int = 68) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not normalized:
        normalized = "item"
    if normalized[0].isdigit():
        normalized = "d_" + normalized
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    available = max_length - len(prefix) - len(digest) - 2
    return f"{prefix}_{normalized[:max(1, available)]}_{digest}"


def _add_payload_tree(db, cab, feature, parent_dir, physical_dir: Path, relative_dir: Path) -> None:
    files = sorted(path for path in physical_dir.iterdir() if path.is_file())
    if files:
        parent_dir.start_component(_msi_id("Comp", relative_dir.as_posix()), feature, flags=0)
        for file_path in files:
            parent_dir.add_file(str(file_path))

    for child in sorted(path for path in physical_dir.iterdir() if path.is_dir()):
        relative_child = relative_dir / child.name
        child_dir = msilib.Directory(
            db,
            cab,
            parent_dir,
            str(child),
            _msi_id("Dir", relative_child.as_posix()),
            child.name,
        )
        _add_payload_tree(db, cab, feature, child_dir, child, relative_child)


def _replace_sequence(entries: list[tuple[str, str | None, int]], action: str,
                      condition: str | None, sequence_number: int) -> list[tuple[str, str | None, int]]:
    updated = []
    found = False
    for current_action, current_condition, current_sequence in entries:
        if current_action == action:
            updated.append((action, condition, sequence_number))
            found = True
        else:
            updated.append((current_action, current_condition, current_sequence))
    if not found:
        updated.append((action, condition, sequence_number))
    return updated


def _add_standard_sequences(db) -> None:
    for table_name in sequence.tables:
        entries = list(getattr(sequence, table_name))
        if table_name in {"InstallUISequence", "InstallExecuteSequence"}:
            entries = _replace_sequence(entries, "FindRelatedProducts", None, 50)
            entries = _replace_sequence(
                entries,
                "SetInstallDirFromPrevious",
                "PREVIOUSINSTALLDIR",
                450,
            )
            entries = _replace_sequence(
                entries,
                "SetInstallDirFromPrevious64",
                "PREVIOUSINSTALLDIR64 AND NOT PREVIOUSINSTALLDIR",
                451,
            )
        if table_name == "InstallExecuteSequence":
            entries = _replace_sequence(
                entries,
                "RemoveExistingProducts",
                "OLDPRODUCTS AND NOT Installed",
                1590,
            )
            # RegisterProduct(6100) 依据 ARPINSTALLLOCATION 写卸载登记的 InstallLocation
            entries = _replace_sequence(
                entries,
                "SetArpInstallLocation",
                "NOT Installed",
                5950,
            )
        add_data(db, table_name, entries)


def _add_upgrade_data(db, config: ProductConfig, version: str) -> None:
    registry_key = f"Software\\{config.manufacturer}\\{config.install_subdir}"
    add_data(db, "Property", [
        ("UpgradeCode", config.upgrade_code),
        ("ALLUSERS", "1"),
        ("ARPURLINFOABOUT", "https://github.com/c932/MOVIE_MANAGER_LITE"),
        ("ARPNOREPAIR", "1"),
        # 每机安装下，AppSearch 结果必须列为安全公共属性才能跨 UI/执行序列传递
        ("SecureCustomProperties", "PREVIOUSINSTALLDIR;PREVIOUSINSTALLDIR64"),
    ])
    add_data(db, "Upgrade", [
        (config.upgrade_code, "0.0.0", version, None, 256, None, "OLDPRODUCTS"),
        (config.upgrade_code, version, None, None, 256, None, "NEWERPRODUCTFOUND"),
    ])
    add_data(db, "LaunchCondition", [
        ("NOT NEWERPRODUCTFOUND", "A newer or identical version of [ProductName] is already installed."),
    ])
    add_data(db, "Registry", [
        ("InstallDirRegistry", 2, registry_key, "InstallDir", "[INSTALLDIR]", "MainComp"),
    ])
    # x64 包把注册表写入 64 位视图，32 位包写入 WOW6432Node：
    # 双视图各配一个 RegLocator，保证两种平台下都能读到上次安装位置
    add_data(db, "RegLocator", [
        ("PreviousInstallDir", 2, registry_key, "InstallDir", 2),
        ("PreviousInstallDir64", 2, registry_key, "InstallDir", 18),
    ])
    add_data(db, "AppSearch", [
        ("PREVIOUSINSTALLDIR", "PreviousInstallDir"),
        ("PREVIOUSINSTALLDIR64", "PreviousInstallDir64"),
    ])
    add_data(db, "CustomAction", [
        ("SetInstallDirFromPrevious", 51, "INSTALLDIR", "[PREVIOUSINSTALLDIR]"),
        ("SetInstallDirFromPrevious64", 51, "INSTALLDIR", "[PREVIOUSINSTALLDIR64]"),
        # Property 表不解析 [INSTALLDIR]，须经类型 51 动作赋值才会落成真实路径
        ("SetArpInstallLocation", 51, "ARPINSTALLLOCATION", "[INSTALLDIR]"),
    ])


def _add_installer_ui(db, config: ProductConfig) -> None:
    width, height = 370, 270
    modal = 3

    add_data(db, "TextStyle", [
        ("TitleFont", "Verdana", 13, None, 1),
        ("NormalFont", "Verdana", 9, None, None),
    ])

    dialog = Dialog(db, "WelcomeDlg", 0, 0, width, height, modal,
                    "Welcome", "Next", "Next", "Cancel")
    dialog.text("Title", 15, 15, 340, 27, 3,
                r"{\TitleFont}Welcome to [ProductName] Setup")
    dialog.text("Body", 15, 55, 340, 100, 3,
                "This wizard will guide you through the installation of "
                "[ProductName] [ProductVersion].\r\n\r\n"
                "Click Next to continue, or Cancel to exit.")
    dialog.line("BottomLine", 0, 234, width, 0)
    (dialog.pushbutton("Next", 236, 243, 56, 17, 3, "Next >", "Cancel")
     .event("NewDialog", "SelectDirDlg"))
    (dialog.pushbutton("Cancel", 304, 243, 56, 17, 3, "Cancel", "Next")
     .event("SpawnDialog", "CancelDlg"))

    dialog = Dialog(db, "SelectDirDlg", 0, 0, width, height, modal,
                    "Choose Install Location", "PathEdit", "Next", "Cancel")
    dialog.text("Title", 15, 15, 340, 27, 3,
                r"{\TitleFont}Choose Install Location")
    dialog.text("Desc", 15, 50, 340, 30, 3,
                "Choose the folder in which to install [ProductName].")
    dialog.text("PathLabel", 15, 95, 340, 15, 3, "Destination Folder:")
    dialog.text("Note", 15, 148, 340, 30, 3,
                "Configuration and data are stored separately in "
                f"%APPDATA%\\{config.app_data_dir}\\data\\")
    dialog.line("BottomLine", 0, 234, width, 0)
    dialog.control("PathEdit", "PathEdit", 15, 112, 320, 18, 3,
                   "INSTALLDIR", None, "Back", None)
    (dialog.pushbutton("Back", 176, 243, 56, 17, 3, "< Back", "Next")
     .event("NewDialog", "WelcomeDlg"))
    next_button = dialog.pushbutton("Next", 236, 243, 56, 17, 3, "Next >", "Cancel")
    next_button.event("SetTargetPath", "INSTALLDIR", "1", 1)
    next_button.event("NewDialog", "VerifyReadyDlg", "1", 2)
    (dialog.pushbutton("Cancel", 304, 243, 56, 17, 3, "Cancel", "PathEdit")
     .event("SpawnDialog", "CancelDlg"))

    dialog = Dialog(db, "VerifyReadyDlg", 0, 0, width, height, modal,
                    "Ready to Install", "Install", "Install", "Cancel")
    dialog.text("Title", 15, 15, 340, 27, 3, r"{\TitleFont}Ready to Install")
    dialog.text("Desc", 15, 55, 340, 80, 3,
                "[ProductName] is ready to be installed.\r\n\r\n"
                "Destination: [INSTALLDIR]\r\n\r\n"
                "Click Install to begin, or Back to change settings.")
    dialog.line("BottomLine", 0, 234, width, 0)
    (dialog.pushbutton("Back", 176, 243, 56, 17, 3, "< Back", "Install")
     .event("NewDialog", "SelectDirDlg"))
    (dialog.pushbutton("Install", 236, 243, 56, 17, 3, "Install", "Cancel")
     .event("EndDialog", "Return"))
    (dialog.pushbutton("Cancel", 304, 243, 56, 17, 3, "Cancel", "Back")
     .event("SpawnDialog", "CancelDlg"))

    dialog = Dialog(db, "ProgressDlg", 0, 0, width, height, 1,
                    "Installing [ProductName]", "Cancel", "Cancel", "Cancel")
    dialog.text("Title", 15, 15, 340, 27, 3, r"{\TitleFont}Installing [ProductName]")
    dialog.text("Desc", 15, 55, 340, 20, 3,
                "Please wait while [ProductName] is installed.")
    dialog.control("ActionText", "Text", 15, 90, 340, 18, 3,
                   None, "[ActionText]", None, None)
    dialog.control("ProgressBar", "ProgressBar", 15, 118, 340, 14, 65539,
                   "Progress", None, None, None)
    dialog.line("BottomLine", 0, 234, width, 0)
    (dialog.pushbutton("Cancel", 304, 243, 56, 17, 3, "Cancel", "Cancel")
     .event("SpawnDialog", "CancelDlg"))

    dialog = Dialog(db, "ExitDialog", 0, 0, width, height, modal,
                    "Installation Complete", "Finish", "Finish", "Finish")
    dialog.text("Title", 15, 15, 340, 27, 3,
                r"{\TitleFont}Installation Complete")
    dialog.text("Desc", 15, 55, 340, 115, 3,
                "[ProductName] [ProductVersion] has been successfully installed.\r\n\r\n"
                "Shortcuts have been added to your Desktop and Start Menu.\r\n\r\n"
                "Your configuration and data are stored in:\r\n"
                f"  %APPDATA%\\{config.app_data_dir}\\data\\\r\n\r\n"
                "Click Finish to exit this wizard.")
    dialog.line("BottomLine", 0, 234, width, 0)
    (dialog.pushbutton("Finish", 304, 243, 56, 17, 3, "Finish", "Finish")
     .event("EndDialog", "Return"))

    dialog = Dialog(db, "CancelDlg", 55, 15, 260, 85, modal,
                    "Cancel Setup", "No", "No", "No")
    dialog.text("Text", 48, 15, 194, 35, 3,
                "Are you sure you want to cancel [ProductName] Setup?")
    (dialog.pushbutton("Yes", 72, 57, 56, 17, 3, "Yes", "No")
     .event("EndDialog", "Exit"))
    (dialog.pushbutton("No", 132, 57, 56, 17, 3, "No", "Yes")
     .event("EndDialog", "Return"))

    dialog = Dialog(db, "UserExit", 0, 0, width, height, modal,
                    "Setup Cancelled", "Finish", "Finish", "Finish")
    dialog.text("Title", 15, 15, 340, 27, 3, r"{\TitleFont}Setup Cancelled")
    dialog.text("Desc", 15, 55, 340, 60, 3,
                "[ProductName] was not installed. Click Finish to exit this wizard.")
    dialog.line("BottomLine", 0, 234, width, 0)
    (dialog.pushbutton("Finish", 304, 243, 56, 17, 3, "Finish", "Finish")
     .event("EndDialog", "Exit"))

    dialog = Dialog(db, "FatalError", 0, 0, width, height, modal,
                    "Installation Failed", "Finish", "Finish", "Finish")
    dialog.text("Title", 15, 15, 340, 27, 3, r"{\TitleFont}Installation Failed")
    dialog.text("Desc", 15, 55, 340, 70, 3,
                "[ProductName] could not be installed.\r\n\r\n[ErrorMessage]")
    dialog.line("BottomLine", 0, 234, width, 0)
    (dialog.pushbutton("Finish", 304, 243, 56, 17, 3, "Finish", "Finish")
     .event("EndDialog", "Exit"))

    add_data(db, "InstallUISequence", [
        ("WelcomeDlg", "NOT Installed", 1250),
        ("ProgressDlg", "NOT Installed", 1280),
    ])


def _add_directories_and_payload(db, cab, feature, config: ProductConfig) -> None:
    target = msilib.Directory(db, cab, None, str(config.dist_dir.parent), "TARGETDIR", "SourceDir")
    program_files = msilib.Directory(
        db,
        cab,
        target,
        str(config.dist_dir.parent),
        "ProgramFilesFolder",
        "PFiles",
    )
    install_dir = msilib.Directory(
        db,
        cab,
        program_files,
        str(config.dist_dir),
        "INSTALLDIR",
        config.install_subdir,
    )
    add_data(db, "Directory", [
        ("ProgramMenuFolder", "TARGETDIR", "."),
        ("AppMenuFolder", "ProgramMenuFolder", config.menu_folder),
        ("DesktopFolder", "TARGETDIR", "."),
    ])

    executable = config.dist_dir / config.executable_name
    if not executable.is_file():
        raise FileNotFoundError(f"Expected executable not found: {executable}")

    install_dir.start_component("MainComp", feature, flags=0)
    install_dir.add_file(str(executable))
    for file_path in sorted(path for path in config.dist_dir.iterdir() if path.is_file()):
        if file_path != executable:
            install_dir.add_file(str(file_path))
    for child in sorted(path for path in config.dist_dir.iterdir() if path.is_dir()):
        child_dir = msilib.Directory(
            db,
            cab,
            install_dir,
            str(child),
            _msi_id("Dir", child.name),
            child.name,
        )
        _add_payload_tree(db, cab, feature, child_dir, child, Path(child.name))


def _add_icons_and_shortcuts(db, config: ProductConfig) -> None:
    icon_name = None
    if config.icon_path.is_file():
        icon_name = "AppIcon.ico"
        add_data(db, "Icon", [(icon_name, msilib.Binary(str(config.icon_path)))])
        add_data(db, "Property", [("ARPPRODUCTICON", icon_name)])

    add_data(db, "Shortcut", [
        (
            f"SM_{config.shortcut_prefix}",
            "AppMenuFolder",
            config.product_name,
            "MainComp",
            f"[INSTALLDIR]{config.executable_name}",
            None,
            config.product_name,
            None,
            icon_name,
            0,
            1,
            "INSTALLDIR",
        ),
        (
            f"Desktop_{config.shortcut_prefix}",
            "DesktopFolder",
            config.product_name,
            "MainComp",
            f"[INSTALLDIR]{config.executable_name}",
            None,
            config.product_name,
            None,
            icon_name,
            0,
            1,
            "INSTALLDIR",
        ),
    ])


def _single_row(db, query: str):
    view = db.OpenView(query)
    view.Execute(None)
    row = view.Fetch()
    view.Close()
    return row


def verify_built_msi(path: Path, config: ProductConfig) -> None:
    db = msilib.OpenDatabase(str(path), msilib.MSIDBOPEN_READONLY)
    try:
        required_dialogs = {"WelcomeDlg", "ProgressDlg", "ExitDialog", "UserExit", "FatalError"}
        for dialog_name in required_dialogs:
            if _single_row(db, f"SELECT `Dialog` FROM `Dialog` WHERE `Dialog` = '{dialog_name}'") is None:
                raise RuntimeError(f"Missing required dialog: {dialog_name}")

        for action_name in {"SetInstallDirFromPrevious", "SetInstallDirFromPrevious64",
                            "SetArpInstallLocation", "RemoveExistingProducts"}:
            if _single_row(
                db,
                f"SELECT `Action` FROM `InstallExecuteSequence` WHERE `Action` = '{action_name}'",
            ) is None:
                raise RuntimeError(f"Missing execute action: {action_name}")

        for action_name in {"SetInstallDirFromPrevious", "SetInstallDirFromPrevious64"}:
            if _single_row(
                db,
                f"SELECT `Action` FROM `InstallUISequence` WHERE `Action` = '{action_name}'",
            ) is None:
                raise RuntimeError(f"Missing UI action: {action_name}")

        for action_name in {"WelcomeDlg", "ProgressDlg"}:
            if _single_row(
                db,
                f"SELECT `Action` FROM `InstallUISequence` WHERE `Action` = '{action_name}'",
            ) is None:
                raise RuntimeError(f"Missing UI action: {action_name}")

        for action_property in {"OLDPRODUCTS", "NEWERPRODUCTFOUND"}:
            if _single_row(
                db,
                "SELECT `ActionProperty` FROM `Upgrade` "
                f"WHERE `ActionProperty` = '{action_property}'",
            ) is None:
                raise RuntimeError(f"Missing upgrade detection: {action_property}")

        if _single_row(
            db,
            "SELECT `Condition` FROM `LaunchCondition` "
            "WHERE `Condition` = 'NOT NEWERPRODUCTFOUND'",
        ) is None:
            raise RuntimeError("Missing newer-version launch condition.")

        remove_row = _single_row(
            db,
            "SELECT `Sequence` FROM `InstallExecuteSequence` "
            "WHERE `Action` = 'RemoveExistingProducts'",
        )
        install_row = _single_row(
            db,
            "SELECT `Sequence` FROM `InstallExecuteSequence` WHERE `Action` = 'InstallFiles'",
        )
        if remove_row is None or install_row is None or remove_row.GetInteger(1) >= install_row.GetInteger(1):
            raise RuntimeError("RemoveExistingProducts must execute before InstallFiles.")

        for table_name, column_name, expected in [
            ("AppSearch", "Property", "PREVIOUSINSTALLDIR"),
            ("AppSearch", "Property", "PREVIOUSINSTALLDIR64"),
            ("RegLocator", "Signature_", "PreviousInstallDir"),
            ("RegLocator", "Signature_", "PreviousInstallDir64"),
            ("CustomAction", "Action", "SetInstallDirFromPrevious"),
            ("CustomAction", "Action", "SetInstallDirFromPrevious64"),
            ("CustomAction", "Action", "SetArpInstallLocation"),
            ("Registry", "Registry", "InstallDirRegistry"),
        ]:
            if _single_row(
                db,
                f"SELECT `{column_name}` FROM `{table_name}` WHERE `{column_name}` = '{expected}'",
            ) is None:
                raise RuntimeError(f"Missing {table_name} entry: {expected}")

        secure_row = _single_row(
            db, "SELECT `Value` FROM `Property` WHERE `Property` = 'SecureCustomProperties'")
        if secure_row is None:
            raise RuntimeError("Missing SecureCustomProperties property.")
        for expected_property in ("PREVIOUSINSTALLDIR", "PREVIOUSINSTALLDIR64"):
            if expected_property not in secure_row.GetString(1):
                raise RuntimeError(f"SecureCustomProperties must list {expected_property}.")

        file_view = db.OpenView("SELECT `FileName` FROM `File`")
        file_view.Execute(None)
        filenames = []
        while row := file_view.Fetch():
            filenames.append(row.GetString(1).split("|")[-1])
        file_view.Close()
        if config.executable_name not in filenames:
            raise RuntimeError(f"Missing executable payload: {config.executable_name}")

        expected_file_count = sum(1 for item in config.dist_dir.rglob("*") if item.is_file())
        if len(filenames) != expected_file_count:
            raise RuntimeError(
                f"Payload file count mismatch: expected {expected_file_count}, found {len(filenames)}."
            )
    finally:
        del db


def build_product(config: ProductConfig, version: str) -> Path:
    version = validate_version(version)
    if not config.dist_dir.is_dir():
        raise FileNotFoundError(
            f"Distribution directory not found: {config.dist_dir}\n"
            f"Build it with PyInstaller before creating the MSI."
        )

    output = config.output_path(version)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing MSI: {output}")

    db = msilib.init_database(
        str(output),
        schema,
        config.product_name,
        _new_guid(),
        version,
        config.manufacturer,
    )
    _add_standard_sequences(db)
    _add_upgrade_data(db, config, version)
    feature = msilib.Feature(db, "Complete", config.product_name, "All Files", 1)
    cab = msilib.CAB("files")
    _add_directories_and_payload(db, cab, feature, config)
    _add_icons_and_shortcuts(db, config)
    _add_installer_ui(db, config)
    cab.commit(db)
    db.Commit()
    del db

    verify_built_msi(output, config)
    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"MSI built: {output.name} ({size_mb:.1f} MB)")
    print(f"Location: {output}")
    return output
