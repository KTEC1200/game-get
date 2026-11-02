import json
import re
import subprocess
from pathlib import Path

import pytest

import _as_audio_collect2 as collector


def _completed(cmd):
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def test_numeric_names_are_refined_after_first_round():
    """兜底路径（拿不到名字清单时）仍要能细分数字名。"""
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
        return _completed(args)

    monkeypatch.setattr(collector.subprocess, 'run', export)
    assert collector.main([str(tmp_path), str(dest)]) == 0
    assert sorted(p.name for p in dest.glob('*.wav')) == ['first.wav', 'second.wav']


def test_existing_work_directory_is_never_deleted(tmp_path, monkeypatch):
    work = tmp_path / 'Audio_work'
    work.mkdir()
    (work / 'important.txt').write_text('keep')
    monkeypatch.setattr(collector, 'rounds', lambda: [])
    monkeypatch.setattr('toolbridge.find_tool', lambda key: Path('configured.exe'))

    def export(args, **kwargs):
        return _completed(args)

    monkeypatch.setattr(collector.subprocess, 'run', export)
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
        return _completed(args)

    monkeypatch.setattr(collector.subprocess, 'run', export)
    with pytest.raises(ValueError, match='conflict'):
        collector.main([str(tmp_path), str(dest)])
    assert [(p.name, p.read_bytes()) for p in dest.glob('*.wav')] == [('clip.wav', b'original')]


# ------------------------------------------------ 按名字对账（2026-11-02 新契约）

def test_enumerate_names_reads_json_m_name(tmp_path, monkeypatch):
    """地面真相：JSON 枚举里的 m_Name。"""
    def export(args, **kwargs):
        d = Path(args[2]) / 'resources.assets_export'
        d.mkdir(parents=True, exist_ok=True)
        for i, name in enumerate(['100.0', 'Voice_A', 'SE01']):
            (d / f'AudioClip_{i}.json').write_text(
                json.dumps({'m_Name': name}), encoding='utf-8')
        return _completed(args)

    monkeypatch.setattr(collector.subprocess, 'run', export)
    names = collector.enumerate_names(tmp_path / 'data', Path('as.exe'), tmp_path / 'w')
    assert sorted(names) == ['100.0', 'SE01', 'Voice_A']


def test_enumerate_names_returns_empty_on_oserror(tmp_path, monkeypatch):
    """AssetStudio 不在 → 空列表（调用方据此退回前缀分组，而不是崩）。"""
    def boom(args, **kwargs):
        raise OSError('no such exe')

    monkeypatch.setattr(collector.subprocess, 'run', boom)
    assert collector.enumerate_names(tmp_path, Path('missing.exe'), tmp_path / 'w') == []


def test_enumerate_names_uses_bysource_grouping(tmp_path, monkeypatch):
    """ByType 会让同名 JSON 互相覆盖 → 枚举必须走 BySource。"""
    captured = {}

    def export(args, **kwargs):
        captured['args'] = args
        return _completed(args)

    monkeypatch.setattr(collector.subprocess, 'run', export)
    collector.enumerate_names(tmp_path, Path('as.exe'), tmp_path / 'w')
    i = captured['args'].index('--group_assets')
    assert captured['args'][i + 1] == 'BySource'
    assert 'JSON' in captured['args']


def test_collect_retries_only_missing_names_with_anchored_pattern(tmp_path, monkeypatch):
    """第一次批量只出一半 → 第二轮只补缺的名字，且正则是锚定 + 转义。"""
    names = ['100.0', '101.0', '102.0', '103.0']
    seen_patterns = []
    state = {'call': 0}

    def export(args, **kwargs):
        pat = args[args.index('--names') + 1]
        seen_patterns.append(pat)
        d = Path(args[2])
        d.mkdir(parents=True, exist_ok=True)
        listed = [n.replace('\\', '') for n in pat[2:-2].split('|')]   # ^( a|b )$
        state['call'] += 1
        out = listed if state['call'] > 1 else listed[:2]      # 首轮故意只出一半
        for n in out:
            (d / f'{n}.wav').write_bytes(b'RIFF' + n.encode())
        return _completed(args)

    monkeypatch.setattr(collector.subprocess, 'run', export)
    dest = tmp_path / 'Audio'
    res = collector.collect(tmp_path / 'data', dest, names, Path('as.exe'),
                            log=lambda *_: None)

    assert res['missing'] == [] and res['collected'] == 4
    assert len(seen_patterns) >= 2
    assert seen_patterns[0] == '^(' + '|'.join(re.escape(n) for n in names) + ')$'
    assert '100\\.0' in seen_patterns[0], '点号必须转义，否则 ^100.0$ 会误配 100x0'


def test_collect_reports_missing_instead_of_silently_passing(tmp_path, monkeypatch):
    """补不齐时必须报出来（对账靠它，不许静默当成功）。"""
    def export(args, **kwargs):
        Path(args[2]).mkdir(parents=True, exist_ok=True)
        return _completed(args)                                  # 一个都不落盘

    monkeypatch.setattr(collector.subprocess, 'run', export)
    res = collector.collect(tmp_path / 'data', tmp_path / 'Audio', ['a', 'b'],
                            Path('as.exe'), batch=1, max_rounds=2,
                            log=lambda *_: None)
    assert res['collected'] == 0
    assert res['missing'] == ['a', 'b']
    assert res['unique'] == 2 and res['expected'] == 2


def test_collect_skips_already_collected_names(tmp_path, monkeypatch):
    """已落盘的不再重跑（--reuse-raw / 断点续跑都靠这个）。"""
    dest = tmp_path / 'Audio'
    dest.mkdir()
    (dest / 'a.wav').write_bytes(b'RIFF')
    calls = []

    def export(args, **kwargs):
        calls.append(args[args.index('--names') + 1])
        d = Path(args[2])
        d.mkdir(parents=True, exist_ok=True)
        (d / 'b.wav').write_bytes(b'RIFFb')
        return _completed(args)

    monkeypatch.setattr(collector.subprocess, 'run', export)
    res = collector.collect(tmp_path / 'data', dest, ['a', 'b'], Path('as.exe'),
                            log=lambda *_: None)
    assert res['missing'] == [] and res['collected'] == 2
    assert len(calls) == 1 and 'a' not in calls[0]


def test_main_accepts_names_file(tmp_path, monkeypatch):
    """--names-file：调用方已有地面真相时不必重复枚举。"""
    names_file = tmp_path / 'names.txt'
    names_file.write_text('x.0\ny.0\n', encoding='utf-8')
    dest = tmp_path / 'Audio'
    calls = []

    def export(args, **kwargs):
        calls.append(args[args.index('--names') + 1])
        d = Path(args[2])
        d.mkdir(parents=True, exist_ok=True)
        for n in ('x.0', 'y.0'):
            (d / f'{n}.wav').write_bytes(b'RIFF')
        return _completed(args)

    monkeypatch.setattr(collector.subprocess, 'run', export)
    monkeypatch.setattr('toolbridge.find_tool', lambda key: Path('configured.exe'))
    assert collector.main([str(tmp_path), str(dest), '--names-file', str(names_file)]) == 0
    assert sorted(p.name for p in dest.glob('*.wav')) == ['x.0.wav', 'y.0.wav']
    assert len(calls) == 1, '给了名字清单就不该再去 JSON 枚举'
