import struct
import zlib

import pytest

import _xp3_carve as carve


def chunk(name, data):
    return name + struct.pack('<Q', len(data)) + data


def fixture(tmp_path, name='folder/a.txt', data=b'hello', checksum=None):
    archive = tmp_path / 'data.xp3'
    archive.write_bytes(b'header' + data)
    encoded = name.encode('utf-16le')
    info = struct.pack('<IQQH', 0, len(data), len(data), len(encoded) // 2) + encoded
    segm = struct.pack('<IQQQ', 0, 6, len(data), len(data))
    adlr = struct.pack('<I', zlib.adler32(data) if checksum is None else checksum)
    index = tmp_path / 'data.xp3.index'
    index.write_bytes(chunk(b'File', chunk(b'info', info) + chunk(b'segm', segm) + chunk(b'adlr', adlr)))
    return archive, index


def test_carves_and_checks_content(tmp_path):
    archive, index = fixture(tmp_path)
    assert carve.extract(archive, index, tmp_path / 'out') == 1
    assert (tmp_path / 'out/folder/a.txt').read_bytes() == b'hello'


def test_rejects_checksum_mismatch(tmp_path):
    archive, index = fixture(tmp_path, checksum=0)
    with pytest.raises(ValueError, match='Adler32'):
        carve.extract(archive, index, tmp_path / 'out')
    assert not (tmp_path / 'out/folder/a.txt').exists()


def test_rejects_path_traversal(tmp_path):
    archive, index = fixture(tmp_path, name='../escape.txt')
    with pytest.raises(ValueError, match='path'):
        carve.extract(archive, index, tmp_path / 'out')
    assert not (tmp_path / 'escape.txt').exists()
