import json
import re
import subprocess
import threading
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


def test_enumerate_names_returns_none_on_oserror(tmp_path, monkeypatch):
    """AssetStudio 不在 / 超时 → **None**（批次 C11）。

    为什么不是空列表：`[]` 的语义是「这作确实没有音频」，调用方会把 expected 算成 0、
    对账 0 差、验收 0 失败 —— 全绿。而「工具没起来」根本不代表没有音频。
    两种结局必须用两种值区分，否则就是本项目最忌讳的「无声的绿」。
    """
    def boom(args, **kwargs):
        raise OSError('no such exe')

    monkeypatch.setattr(collector.subprocess, 'run', boom)
    assert collector.enumerate_names(tmp_path, Path('missing.exe'), tmp_path / 'w') is None


def test_enumerate_names_returns_none_on_timeout(tmp_path, monkeypatch):
    """超时同样返回 None（不是「枚举到 0 个」）。"""
    import subprocess as sp

    def slow(args, **kwargs):
        raise sp.TimeoutExpired(cmd=args, timeout=1)

    monkeypatch.setattr(collector.subprocess, 'run', slow)
    assert collector.enumerate_names(tmp_path, Path('as.exe'), tmp_path / 'w') is None


def test_enumerate_names_returns_empty_when_archive_has_no_audio(tmp_path, monkeypatch):
    """枚举**成功**但确实没有 AudioClip → 空列表（区别于 None）。"""
    def export(args, **kwargs):
        return _completed(args)

    monkeypatch.setattr(collector.subprocess, 'run', export)
    assert collector.enumerate_names(tmp_path, Path('as.exe'), tmp_path / 'w') == []


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


# ------------------------------------------------ 并行补齐（2026-11-06 提速，§31）

def test_resolve_workers_param_env_default():
    """显式参数 > 环境变量 > 默认；非法值退默认不许抛（旋钮不能变成失败路径）。"""
    with pytest.MonkeyPatch.context() as mp:
        assert collector.resolve_workers(2) == 2
        assert collector.resolve_workers(0) == 1, '至少 1（1=串行）'
        mp.setenv('GALUNPACK_AUDIO_WORKERS', '2')
        assert collector.resolve_workers() == 2
        assert collector.resolve_workers(1) == 1, '显式参数压过环境变量'
        mp.setenv('GALUNPACK_AUDIO_WORKERS', 'junk')
        assert collector.resolve_workers() == collector.WORKERS
        mp.setenv('GALUNPACK_AUDIO_WORKERS', '-4')
        assert collector.resolve_workers() == 1


def test_cap_workers_by_memory(monkeypatch):
    """内存门：余量不足自动降回串行（压死机器比慢更糟），查询失败不动并行度。"""
    monkeypatch.setattr(collector, '_mem_avail_gib', lambda: 2.0)
    assert collector.cap_workers_by_memory(3) == 1, \
        '2.0 GiB 可用扣 1.5 GiB 预留后容不下 1 GiB/个 → 串行'
    monkeypatch.setattr(collector, '_mem_avail_gib', lambda: 5.5)
    assert collector.cap_workers_by_memory(3) == 3
    monkeypatch.setattr(collector, '_mem_avail_gib', lambda: 3.5)
    assert collector.cap_workers_by_memory(3) == 2
    monkeypatch.setattr(collector, '_mem_avail_gib', lambda: None)
    assert collector.cap_workers_by_memory(3) == 3, '查不到内存就不收紧'
    assert collector.cap_workers_by_memory(1) == 1, '串行请求不受内存影响'


def test_collect_runs_chunks_concurrently(tmp_path, monkeypatch):
    """workers>=2 时分片必须真的并发跑（串行退化会在这里现形）。

    用 Barrier 锁死：两个导出必须**同时**在跑才能都通过；若实现退化成串行，
    先到的那片等不到同伴就 BrokenBarrierError，测试红。
    """
    monkeypatch.setattr(collector, 'cap_workers_by_memory', lambda w, log=print: w)
    barrier = threading.Barrier(2)

    def export(args, **kwargs):
        barrier.wait(timeout=30)
        d = Path(args[2])
        d.mkdir(parents=True, exist_ok=True)
        (d / 'placeholder.wav').write_bytes(b'RIFF')   # 名字对不上名单 → 不计入
        return _completed(args)

    monkeypatch.setattr(collector.subprocess, 'run', export)
    res = collector.collect(tmp_path / 'data', tmp_path / 'Audio',
                            ['a', 'b', 'c', 'd'], Path('as.exe'),
                            batch=1, max_rounds=2, log=lambda *_: None, workers=2)
    assert res['workers'] == 2
    assert res['missing'] == ['a', 'b', 'c', 'd'], 'placeholder 不该被当成名单内的名字'
    assert res['runs'] == 8, '4 片（batch=1）× 2 轮 = 8 次导出'


def test_collect_single_chunk_stays_serial(tmp_path, monkeypatch):
    """单片时不再起线程池（省开销，也让旧语义的调用方行为不变）。"""
    calls = []
    orig_thread_pool = collector.ThreadPoolExecutor

    def spy_pool(*a, **kw):
        calls.append('pool')
        return orig_thread_pool(*a, **kw)

    monkeypatch.setattr(collector, 'ThreadPoolExecutor', spy_pool)

    def export(args, **kwargs):
        d = Path(args[2])
        d.mkdir(parents=True, exist_ok=True)
        (d / 'a.wav').write_bytes(b'RIFF')
        return _completed(args)

    monkeypatch.setattr(collector.subprocess, 'run', export)
    res = collector.collect(tmp_path / 'data', tmp_path / 'Audio', ['a'],
                            Path('as.exe'), log=lambda *_: None, workers=3)
    assert res['missing'] == [] and res['collected'] == 1
    assert calls == [], '1 片就该直接跑，不起线程池'
