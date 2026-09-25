---
applyTo: "**/packaging/**"
---

# Python Windows 打包 — PyInstaller + msilib 实战手册

基于实际项目（Python 3.11 + PyQt6，CJK Windows 环境）整理的踩坑记录和可用模板。

---

## 一、PyInstaller spec 模板（onedir）

```python
# -*- mode: python ; coding: utf-8 -*-
import os
ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))  # spec 在 packaging/ 子目录时

a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'styles'), 'styles'),
        (os.path.join(ROOT, 'logo'),   'logo'),
    ],
    hiddenimports=['PyQt6.sip'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,        # PyInstaller 6.x 已移除 block_cipher / cipher 参数
)

pyz = PYZ(a.pure)           # PyInstaller 6.x 已移除 a.zipped_data 和 cipher 参数

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='MyApp',           # !! 必须 ASCII !! CJK 名称会导致 msilib 编码崩溃
    icon=os.path.join(ROOT, 'app.ico'),
    console=False,
    upx=True,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    name='MyApp',           # 同上，必须 ASCII
    upx=True,
)
```

### 关键注意事项

| 问题 | 原因 | 解决 |
|---|---|---|
| 中文 exe/目录名 | msilib 在 GBK 系统读取时用 UTF-8 解码崩溃 | exe 和 COLLECT 的 `name=` 必须用 ASCII |
| `block_cipher` / `cipher` / `a.zipped_data` 报错 | PyInstaller 6.x 已移除 | 直接删除这些参数 |
| spec 文件在子目录时 `main.py` 找不到 | 相对路径基于 spec 文件目录 | 用 `SPECPATH` + `os.path.join` 拼绝对路径 |
| `icon=` 无效 | 相对路径问题 | 同样用 `os.path.join(ROOT, 'app.ico')` |

### 构建命令

```powershell
# 在项目根目录执行，--clean 清除 PyInstaller 缓存，-y 覆盖旧 dist
pyinstaller --clean -y packaging\MyApp.spec
```

---

## 二、msilib 生成 MSI 安装包

### 最常踩的坑

#### 1. `init_database` 参数顺序容易传反
```python
# ✅ 正确顺序：ProductName, ProductCode, ProductVersion, Manufacturer
db = msilib.init_database(
    str(output), schema,
    "My App",           # ProductName  (ASCII only)
    product_code,       # ProductCode  (GUID 字符串)
    version,            # ProductVersion
    "MyCompany",        # Manufacturer
)

# ❌ 常见错误：把 Manufacturer 和 ProductCode 传反
# 结果：ProductCode="MyCompany"（非 GUID），安装时 MSI 注册失败，error 1603
```

#### 2. `start_component` 必须传 `flags=0`
```python
# ✅
directory.start_component("CompId", feature, flags=0)

# ❌ 省略 flags，Python 3.11 下报 TypeError: NoneType |= int
directory.start_component("CompId", feature)
```

#### 3. Dialog 控件宽度不能超出对话框边界
```python
W = 370   # 对话框宽度

# ✅
d.line("BottomLine", 0, 234, W, 0)

# ❌ 超出 7 像素 → MSI error 2826
d.line("BottomLine", 0, 234, W + 4, 0)
```

#### 4. Dialog 控件 Tab 链必须成环
每个控件的 `next` 最终要绕回第一个控件，否则 MSI error 2810。

```python
# ✅ Back → Next → Cancel → PathEdit → Back（成环）
d.pushbutton("Back",   ..., next_ctrl="Next")
d.pushbutton("Next",   ..., next_ctrl="Cancel")
d.pushbutton("Cancel", ..., next_ctrl="PathEdit")
d.control("PathEdit", "PathEdit", ..., next_ctrl="Back")   # 回到 Back，成环

# ❌ Back 和 PathEdit 都指向 Next → 不成环 → error 2810
```

---

## 三、msilib 向导 UI 完整模板

```python
from msilib import add_data, Dialog

def add_installer_ui(db, W=370, H=270):
    MODAL = 3  # Visible(1) + Modal(2)

    add_data(db, "TextStyle", [
        ("TitleFont",  "Verdana", 13, None, 1),   # bold
        ("NormalFont", "Verdana",  9, None, None),
    ])

    # ── 1. WelcomeDlg ─────────────────────────────────────────────────────────
    d = Dialog(db, "WelcomeDlg", 0, 0, W, H, MODAL,
               "Welcome", "Next", "Next", "Cancel")
    d.text("Title", 15, 15, 340, 27, 3,
           r"{\TitleFont}Welcome to [ProductName] Setup")
    d.text("Body",  15, 55, 340, 100, 3,
           "Click Next to continue, or Cancel to exit.")
    d.line("BottomLine", 0, 234, W, 0)
    (d.pushbutton("Next",   236, 243, 56, 17, 3, "Next >", "Cancel")
       .event("NewDialog", "SelectDirDlg"))
    (d.pushbutton("Cancel", 304, 243, 56, 17, 3, "Cancel", "Next")
       .event("SpawnDialog", "CancelDlg"))

    # ── 2. SelectDirDlg ───────────────────────────────────────────────────────
    d = Dialog(db, "SelectDirDlg", 0, 0, W, H, MODAL,
               "Choose Install Location", "Next", "Next", "Cancel")
    d.text("Title",     15, 15,  340, 27, 3,
           r"{\TitleFont}Choose Install Location")
    d.text("PathLabel", 15, 95,  340, 15, 3, "Destination Folder:")
    d.line("BottomLine", 0, 234, W, 0)
    # Tab 顺序：PathEdit → Back → Next → Cancel → PathEdit（成环）
    (d.pushbutton("Back",   176, 243, 56, 17, 3, "< Back", "Next")
       .event("NewDialog", "WelcomeDlg"))
    btn = d.pushbutton("Next", 236, 243, 56, 17, 3, "Next >", "Cancel")
    btn.event("SetTargetPath", "INSTALLDIR", "1", 1)
    btn.event("NewDialog", "VerifyReadyDlg", "1", 2)
    (d.pushbutton("Cancel", 304, 243, 56, 17, 3, "Cancel", "PathEdit")
       .event("SpawnDialog", "CancelDlg"))
    d.control("PathEdit", "PathEdit", 15, 112, 320, 18, 3,
              "INSTALLDIR", None, "Back", None)   # next="Back" 使链成环

    # ── 3. VerifyReadyDlg ─────────────────────────────────────────────────────
    d = Dialog(db, "VerifyReadyDlg", 0, 0, W, H, MODAL,
               "Ready to Install", "Install", "Install", "Cancel")
    d.text("Title", 15, 15, 340, 27, 3, r"{\TitleFont}Ready to Install")
    d.text("Desc",  15, 55, 340, 80, 3,
           "Destination: [INSTALLDIR]\r\nClick Install to begin.")
    d.line("BottomLine", 0, 234, W, 0)
    (d.pushbutton("Back",    176, 243, 56, 17, 3, "< Back", "Install")
       .event("NewDialog", "SelectDirDlg"))
    (d.pushbutton("Install", 236, 243, 56, 17, 3, "Install", "Cancel")
       .event("EndDialog", "Return"))   # EndDialog Return → 触发 ExecuteAction
    (d.pushbutton("Cancel",  304, 243, 56, 17, 3, "Cancel", "Back")
       .event("SpawnDialog", "CancelDlg"))

    # ── 4. ExitDlg ────────────────────────────────────────────────────────────
    d = Dialog(db, "ExitDlg", 0, 0, W, H, MODAL,
               "Installation Complete", "Finish", "Finish", "Finish")
    d.text("Title", 15, 15, 340, 27, 3, r"{\TitleFont}Installation Complete")
    d.text("Desc",  15, 55, 340, 80, 3,
           "[ProductName] has been successfully installed.\r\nClick Finish.")
    d.line("BottomLine", 0, 234, W, 0)
    (d.pushbutton("Finish", 304, 243, 56, 17, 3, "Finish", "Finish")
       .event("EndDialog", "Exit"))

    # ── 5. CancelDlg ──────────────────────────────────────────────────────────
    d = Dialog(db, "CancelDlg", 55, 15, 260, 85, MODAL,
               "Cancel Setup", "No", "No", "No")
    d.text("Text", 48, 15, 194, 35, 3,
           "Are you sure you want to cancel [ProductName] Setup?")
    (d.pushbutton("Yes",  72, 57, 56, 17, 3, "Yes", "No")
       .event("EndDialog", "Exit"))
    (d.pushbutton("No",  132, 57, 56, 17, 3, "No",  "Yes")
       .event("EndDialog", "Return"))

    # ── 注入 InstallUISequence ─────────────────────────────────────────────────
    # WelcomeDlg(1290) → 用户操作 → VerifyReadyDlg → EndDialog Return
    # → ExecuteAction(1300)（安装文件）→ ExitDlg(1301)
    add_data(db, "InstallUISequence", [
        ("WelcomeDlg", "NOT Installed", 1290),
        ("ExitDlg",    None,            1301),
    ])
```

---

## 四、快速诊断 MSI 错误

```powershell
# 带详细日志安装（不弹 UI 用 /qb，正常 UI 去掉 /qb）
Start-Process msiexec -ArgumentList '/i "path\to\app.msi" /l*v "install.log" /qb' -Wait

# 查关键错误
Get-Content install.log | Select-String "Return Value 3|error 2826|error 2810|error 2867|error 1603" | Select-Object -Last 20
```

| 错误码 | 含义 | 常见原因 |
|---|---|---|
| 2826 | 控件超出对话框边界 | `BottomLine` 宽度 `W+4` 应改为 `W` |
| 2810 | Tab 链不成环 | 某控件 `next` 指向错误，链无法回到起点 |
| 2867 | Error dialog property 未设置 | `init_database` 参数传反，ProductCode 非 GUID |
| 1603 | 通用安装失败 | 查日志 `Return Value 3` 前几行定位具体 action |
| 1602 | 用户取消 | 正常，用户点了 Cancel |

---

## 五、安装目录与数据目录策略

```
C:\Program Files\MyApp\        ← 程序文件（msilib INSTALLDIR）
    MyApp.exe
    _internal\                 ← PyInstaller 依赖
        PyQt6\
        ...

C:\Users\xxx\AppData\Roaming\MyApp\data\   ← 用户数据（%APPDATA%）
    config.json
    cache.json
    ...
```

- `Program Files` 是只读的（标准用户无写权限），运行时数据必须放 `%APPDATA%`。
- 分开存放的好处：卸载/升级程序时保留用户数据；多版本并存不互相干扰。
- 代码里用 `sys.frozen` 判断：见 `pyqt6-architecture.instructions.md` 第 5 节。
