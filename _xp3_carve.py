"""Extract uncompressed XP3 entries from a KrkrExtract index dump."""
import ntpath
import struct
import tempfile
import zlib
from pathlib import Path


def chunks(data):
    pos = 0
    while pos < len(data):
        if len(data) - pos < 12:
            raise ValueError('truncated chunk header')
        name, size = struct.unpack_from('<4sQ', data, pos)
        pos += 12
        end = pos + size
        if end > len(data):
            raise ValueError('truncated chunk')
        yield name, data[pos:end]
        pos = end


def read_index(index):
    entries = []
    names = set()
    for tag, body in chunks(Path(index).read_bytes()):
        if tag != b'File':
            raise ValueError('unexpected index chunk')
        parts = dict(chunks(body))
        info, segm, adlr = parts[b'info'], parts[b'segm'], parts[b'adlr']
        if len(info) < 22 or len(segm) != 28 or len(adlr) != 4:
            raise ValueError('unsupported XP3 entry')
        flags, size, packed, length = struct.unpack_from('<IQQH', info)
        if len(info) != 22 + 2 * length:
            raise ValueError('invalid name length')
        name = info[22:].decode('utf-16le')
        normalized = name.replace('\\', '/')
        components = normalized.split('/')
        if (not name or ntpath.isabs(name) or ntpath.splitdrive(name)[0]
                or any(p in ('', '.', '..') or ':' in p for p in components)):
            raise ValueError('unsafe path: ' + name)
        key = normalized.casefold()
        if key in names:
            raise ValueError('duplicate path: ' + name)
        names.add(key)
        segment_flags, offset, original, stored = struct.unpack('<IQQQ', segm)
        if flags or segment_flags or original != stored or size != original or packed != stored:
            raise ValueError('compressed or unsupported XP3 entry: ' + name)
        entries.append((components, offset, stored, struct.unpack('<I', adlr)[0]))
    if not entries:
        raise ValueError('empty XP3 index')
    return entries


def extract(archive, index, out_dir):
    archive, out_dir = Path(archive), Path(out_dir)
    entries = read_index(index)
    archive_size = archive.stat().st_size
    with archive.open('rb') as source:
        for parts, offset, size, checksum in entries:
            if offset > archive_size or size > archive_size - offset:
                raise ValueError('segment outside archive')
            dest = out_dir.joinpath(*parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            source.seek(offset)
            remaining, actual = size, 1
            temp_name = None
            try:
                with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as out:
                    temp_name = Path(out.name)
                    while remaining:
                        block = source.read(min(1024 * 1024, remaining))
                        if not block:
                            raise ValueError('truncated segment')
                        out.write(block)
                        actual = zlib.adler32(block, actual)
                        remaining -= len(block)
                if actual != checksum:
                    raise ValueError('Adler32 mismatch: ' + '/'.join(parts))
                temp_name.replace(dest)
            finally:
                if temp_name is not None:
                    temp_name.unlink(missing_ok=True)
    return len(entries)
