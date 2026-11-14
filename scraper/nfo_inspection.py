"""只读检查 NFO，区分说明文件、异常 XML 和不可读取的原文件。"""
from __future__ import annotations

import hashlib
import os
import xml.etree.ElementTree as ET

from .scrape_models import VideoTarget


def inspect_nfo(target: VideoTarget) -> ET.Element | None:
    """记录同一份原始字节的版本及分类；正常 XML 不受文本猜测影响。"""
    try:
        stamp = target.nfo_path.stat()
        target.nfo_stamp = (stamp.st_mtime_ns, stamp.st_size)
        with target.nfo_path.open('rb') as stream:
            before = os.fstat(stream.fileno())
            content = stream.read()
            after = os.fstat(stream.fileno())
        current = target.nfo_path.stat()
        versions = {(s.st_mtime_ns, s.st_size, s.st_ino) for s in (stamp, before, after, current)}
        if len(versions) != 1:
            raise OSError('文件在读取期间发生改变，请重新扫描')
    except OSError as exc:
        target.error_kind = 'unreadable'
        target.error_detail = f'无法读取原 NFO：{exc}'
        target.error = target.error_detail
        return None

    target.nfo_fingerprint = hashlib.sha256(content).hexdigest()
    target.version_captured = True
    try:
        root = ET.fromstring(content)
    except (ET.ParseError, ValueError, LookupError) as exc:
        # 先尝试 XML，保证 UTF-16、声明编码的正常旧 XML 不被 UTF-8 猜测误判。
        try:
            encoding = ('utf-32' if content.startswith((b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff'))
                        else 'utf-16' if content.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
            text = content.decode(encoding).strip()
        except UnicodeError as decode_error:
            target.error_kind = 'invalid_xml'
            target.error_detail = f'原 NFO 编码无效：{decode_error}'
        else:
            if text and not text.startswith('<'):
                target.error_kind = 'not_metadata'
                target.error_detail = '原 NFO 是发布说明或其他非电影元数据，不是 movie XML'
            else:
                target.error_kind = 'invalid_xml'
                target.error_detail = f'原 NFO XML 无效或内容为空：{exc}'
        target.error = target.error_detail
        return None
    if root.tag != 'movie':
        target.error_kind = 'not_metadata'
        target.error_detail = f'原 NFO 不是电影元数据：XML 根元素为 {root.tag}，不是 movie'
        target.error = target.error_detail
        return None
    return root
