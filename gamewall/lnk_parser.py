"""
Windows .lnk 快捷方式二进制解析器（MS-SHLLINK 子集）

只提取启动目标路径：
1. 优先 LinkInfo.LocalBasePath（ANSI，最可靠）
2. 兜底「快捷方式目录 + RelativePath 字符串」拼接
IDList-only（如 MSI 广告式快捷方式）无法解析目标时返回 None，调用方静默跳过。
"""
import os
import struct

_HEADER_SIZE = 0x4C
# LinkFlags
_HAS_ID_LIST = 0x01
_HAS_LINK_INFO = 0x02
_HAS_NAME = 0x04
_HAS_RELATIVE_PATH = 0x08
_HAS_WORKING_DIR = 0x10
_HAS_ARGUMENTS = 0x20
_HAS_ICON = 0x40
IsUnicode = 0x80
# LinkInfoFlags
_VOLUME_ID_AND_LOCAL_BASE_PATH = 0x01

_STRING_FLAGS = (_HAS_NAME, _HAS_RELATIVE_PATH, _HAS_WORKING_DIR,
                 _HAS_ARGUMENTS, _HAS_ICON)


def parse_lnk(path: str):
    """
    解析 .lnk，返回目标 exe 绝对路径；失败返回 None。
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if len(data) < _HEADER_SIZE:
        return None
    try:
        header_size, _clsid, link_flags = struct.unpack_from("<I16sI", data, 0)
        if header_size != _HEADER_SIZE:
            return None

        pos = _HEADER_SIZE
        if link_flags & _HAS_ID_LIST:
            (id_list_size,) = struct.unpack_from("<H", data, pos)
            pos += 2 + id_list_size
            if pos > len(data):
                return None

        target = None
        if link_flags & _HAS_LINK_INFO and pos + 0x1C <= len(data):
            target = _parse_link_info(data, pos)

        if not target and link_flags & _HAS_RELATIVE_PATH:
            target = _target_from_strings(data, pos, link_flags, path)

        if not target:
            return None
        target = os.path.normpath(target)
        if not target.lower().endswith(".exe") or not os.path.exists(target):
            return None
        return target
    except (struct.error, IndexError, UnicodeDecodeError, OSError):
        return None


def _parse_link_info(data: bytes, pos: int):
    (li_size, li_header_size, li_flags, _vol_off, local_off,
     _net_off, _suffix_off) = struct.unpack_from("<7I", data, pos)
    if li_size <= 0 or pos + li_size > len(data):
        return None
    if not (li_flags & _VOLUME_ID_AND_LOCAL_BASE_PATH) or local_off < li_header_size:
        return None
    abs_off = pos + local_off
    if abs_off >= len(data):
        return None
    end = data.find(b"\x00", abs_off)
    if end < 0:
        return None
    # ANSI 路径按系统代码页解码（简中系统为 GBK）
    return data[abs_off:end].decode("mbcs", "replace")


def _target_from_strings(data: bytes, pos: int, link_flags: int, lnk_path: str):
    """跳过各字符串段并取 RelativePath/WorkingDir 拼出目标路径"""
    relative_path = working_dir = None
    is_unicode = bool(link_flags & IsUnicode)
    for flag in _STRING_FLAGS:
        if not link_flags & flag:
            continue
        if pos + 2 > len(data):
            return None
        (char_count,) = struct.unpack_from("<H", data, pos)
        pos += 2
        if is_unicode:
            byte_count = char_count * 2
            if pos + byte_count > len(data):
                return None
            text = data[pos:pos + byte_count].decode("utf-16-le", "replace")
        else:
            byte_count = char_count
            if pos + byte_count > len(data):
                return None
            text = data[pos:pos + byte_count].decode("mbcs", "replace")
        pos += byte_count
        if flag == _HAS_RELATIVE_PATH:
            relative_path = text.rstrip("\x00")
        elif flag == _HAS_WORKING_DIR:
            working_dir = text.rstrip("\x00")

    if relative_path:
        base = os.path.dirname(lnk_path)
        return os.path.join(base, relative_path)
    if working_dir and working_dir.lower().endswith(".exe"):
        return working_dir
    return None
