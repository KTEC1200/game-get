import hashlib
import struct

import _pfs_extract as pfs


def test_index_starts_at_offset_seven(tmp_path):
    name = b'a.txt'
    data = b'hello'
    index_size = 4 + 4 + len(name) + 12
    offset = 7 + index_size
    index = struct.pack('<II', 1, len(name)) + name + struct.pack('<III', 0, offset, len(data))
    key = hashlib.sha1(index).digest()
    archive = tmp_path / 'data.pfs'
    archive.write_bytes(b'pf8' + struct.pack('<I', index_size) + index + bytes(x ^ key[i % 20] for i, x in enumerate(data)))
    info = pfs.read_index(archive)
    assert info['entries'] == [('a.txt', offset, len(data))]
    assert info['key'] == key
