import struct
import zlib

import pytest
import krkr_auto_extract as kae
import orchestrator as orch


def chunk(tag, data):
    return tag + struct.pack('<Q', len(data)) + data


def archive(stage, checksum=None):
    payload = b'synthetic payload'
    (stage / 'data.xp3').write_bytes(b'header' + payload)
    name = 'folder/a.txt'.encode('utf-16le')
    info = struct.pack('<IQQH', 0, len(payload), len(payload), len(name) // 2) + name
    segm = struct.pack('<IQQQ', 0, 6, len(payload), len(payload))
    adlr = struct.pack('<I', zlib.adler32(payload) if checksum is None else checksum)
    (stage / 'data.xp3.index').write_bytes(chunk(b'File', chunk(b'info', info) + chunk(b'segm', segm) + chunk(b'adlr', adlr)))


@pytest.fixture
def setup_fallback(tmp_path, monkeypatch):
    game = tmp_path / 'game'
    game.mkdir()
    stage = tmp_path / 'stage' / 'auto'
    stage.mkdir(parents=True)
    (stage / 'game.exe').write_bytes(b'fake')
    monkeypatch.setattr(kae, 'STAGE_ROOT', str(stage.parent))
    monkeypatch.setattr(kae, 'log', lambda *args: None)
    monkeypatch.setattr(kae, 'pids_by_name', lambda name: [123])
    monkeypatch.setattr(kae, 'find_ui_window', lambda pid: None)
    monkeypatch.setattr(kae.subprocess, 'Popen', lambda *a, **kw: None)
    monkeypatch.setattr(kae.subprocess, 'run', lambda *a, **kw: None)
    monkeypatch.setattr(kae.time, 'sleep', lambda *a: None)
    return game, stage, tmp_path / 'out'


def test_missing_ui_carves_verified_synthetic_index(setup_fallback):
    game, stage, out = setup_fallback
    archive(stage)
    assert kae.main([str(game), '--reuse-stage', '--out', str(out)]) == 0
    assert (out / 'KrkrExtract_Output/data/data/folder/a.txt').read_bytes() == b'synthetic payload'


def test_existing_destination_is_preserved(setup_fallback):
    game, stage, out = setup_fallback
    archive(stage)
    sentinel = out / 'KrkrExtract_Output' / 'keep.txt'
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b'keep')
    with pytest.raises(RuntimeError, match='exist'):
        kae.main([str(game), '--reuse-stage', '--out', str(out)])
    assert sentinel.read_bytes() == b'keep'


def test_existing_stage_output_is_preserved(setup_fallback):
    game, stage, out = setup_fallback
    archive(stage)
    sentinel = stage / 'KrkrExtract_Output/data/data/folder/a.txt'
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b'keep')
    with pytest.raises(RuntimeError, match='exist'):
        kae.main([str(game), '--reuse-stage', '--out', str(out)])
    assert sentinel.read_bytes() == b'keep'


@pytest.mark.parametrize('failure', ['missing', 'checksum'])
def test_fallback_failure_is_not_reported_as_success(setup_fallback, failure):
    game, stage, out = setup_fallback
    archive(stage, checksum=0 if failure == 'checksum' else None)
    if failure == 'missing':
        (stage / 'other.xp3').write_bytes(b'other')
    with pytest.raises(RuntimeError):
        kae.main([str(game), '--reuse-stage', '--out', str(out)])
    assert not (out / 'KrkrExtract_Output').exists()


def test_orchestrator_propagates_output_without_claiming_reconciliation(setup_fallback, monkeypatch):
    game, stage, out = setup_fallback
    archive(stage)
    (game / 'data.xp3').write_bytes(b'fake archive')
    monkeypatch.setattr(orch.tb, 'garbro_list', lambda path: (False, 0, 'unavailable'))
    original = kae.main
    monkeypatch.setattr(kae, 'main', lambda argv: original(argv + ['--reuse-stage']))
    ctx = orch.Ctx(game, out, out / '_work', out / 'manifest.json', allow_gui=True)
    result = orch.stage_extract_kirikiri(ctx)
    assert result.ok
    assert (ctx.raw_dir / 'data/folder/a.txt').read_bytes() == b'synthetic payload'
    report = orch.build_manifest(ctx, [result], 'KiriKiri')
    assert report['reconcile']['expected'] is None
    assert report['reconcile']['diff'] is None
    assert report['reconcile']['actual'] == 1
