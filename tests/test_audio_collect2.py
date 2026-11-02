import re
from pathlib import Path
import pytest

import _as_audio_collect2 as collector


def test_numeric_names_are_refined_after_first_round():
    rounds = dict(collector.rounds())
    assert any(re.search(p, '123456') for p in rounds['round2'])
    assert any(re.search(p, '123456') for p in rounds['round3'])


def test_collect_preserves_distinct_names_with_identical_content(tmp_path, monkeypatch):
    dest = tmp_path / 'Audio'
    dest.mkdir()
    (dest / 'first.wav').write_bytes(b'same')
    monkeypatch.setattr(collector, 'rounds', lambda: [('round1', ['x'])])
    monkeypatch.setattr('toolbridge.find_tool', lambda key: Path('configured.exe'))

    def export(args, **kwargs):
        assert args[0] == 'configured.exe'
        output = Path(args[2])
        (output / 'first.wav').write_bytes(b'same')
        (output / 'second.wav').write_bytes(b'same')

    monkeypatch.setattr(collector.subprocess, 'run', export)
    assert collector.main([str(tmp_path), str(dest)]) == 0
    assert sorted(p.name for p in dest.glob('*.wav')) == ['first.wav', 'second.wav']


def test_existing_work_directory_is_never_deleted(tmp_path, monkeypatch):
    work = tmp_path / 'Audio_work'
    work.mkdir()
    (work / 'important.txt').write_text('keep')
    monkeypatch.setattr(collector, 'rounds', lambda: [])
    monkeypatch.setattr('toolbridge.find_tool', lambda key: Path('configured.exe'))
    collector.main([str(tmp_path), str(tmp_path / 'Audio')])
    assert (work / 'important.txt').read_text() == 'keep'


def test_conflicting_same_name_fails_without_creating_duplicates(tmp_path, monkeypatch):
    dest = tmp_path / 'Audio'
    dest.mkdir()
    (dest / 'clip.wav').write_bytes(b'original')
    monkeypatch.setattr(collector, 'rounds', lambda: [('round1', ['x'])])
    monkeypatch.setattr('toolbridge.find_tool', lambda key: Path('configured.exe'))
    def export(args, **kwargs):
        (Path(args[2]) / 'clip.wav').write_bytes(b'different')
    monkeypatch.setattr(collector.subprocess, 'run', export)
    with pytest.raises(ValueError, match='conflict'):
        collector.main([str(tmp_path), str(dest)])
    assert [(p.name, p.read_bytes()) for p in dest.glob('*.wav')] == [('clip.wav', b'original')]
