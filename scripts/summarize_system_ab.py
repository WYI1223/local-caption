"""Build an auditable listening page from completed system_weak_voice_ab output."""
import argparse
import difflib
import html
import json
import sys
import wave
from pathlib import Path

import numpy as np

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'app'))
from transcript_history import TranscriptHistory


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path)
    out=p.parse_args().directory.resolve()
    if not out.is_relative_to(BASE/'diagnostics'):raise ValueError('Expected diagnostics directory')
    r=json.loads((out/'results.json').read_text(encoding='utf-8'))
    gain=json.loads((out/'gain-metrics.json').read_text(encoding='utf-8'))
    queue=[json.loads(line) for line in (out/'capture-metrics.jsonl').read_text().splitlines()]
    lengths={}
    for name in ('raw','gtcrn','enhanced','device-raw'):
        with wave.open(str(out/(name+'.wav'))) as f:
            lengths[name]={'frames':f.getnframes(),'rate':f.getframerate(),'channels':f.getnchannels()}
    assert all(lengths[k]['frames']==lengths['raw']['frames'] for k in ('gtcrn','enhanced'))
    assert abs(lengths['device-raw']['frames']/48000-r['audio_seconds'])<.001
    assert not r['faults']
    assert all(g['gain']==1 for g in gain if not g['weak'])
    boosted=[g['gain'] for g in gain if g['gain']>1.001]
    summary=dict(verified_audio=lengths,frontend_rtf=r['frontend_seconds']/r['audio_seconds'],
        queue_p95_seconds=float(np.percentile([q['queued_seconds'] for q in queue],95)),
        max_queue_seconds=r['max_frontend_queue_seconds'],
        boosted_frame_fraction=len(boosted)/len(gain),
        mean_boosted_gain_db=float(np.mean(20*np.log10(boosted))) if boosted else 0,
        maximum_gain_db=float(20*np.log10(r['max_gain'])),
        nonweak_frames_unity=True,transcript_history_matches={})
    snapshots={}
    for name in ('raw','enhanced'):
        history=TranscriptHistory();snaps=[];boundary=60
        events=[json.loads(line) for line in (out/(name+'-events.jsonl')).read_text(encoding='utf-8').splitlines()]
        for e in events:
            history.observe(e['text'],e['final'])
            if e['processed']>=boundary:
                snaps.append((e['processed'],history.text));boundary+=60
        if not snaps or snaps[-1][1]!=history.text:snaps.append((events[-1]['processed'],history.text))
        summary['transcript_history_matches'][name]=history.text==(out/(name+'.txt')).read_text(encoding='utf-8')
        assert summary['transcript_history_matches'][name]
        assert abs(events[-1]['processed']-r['audio_seconds'])<.1
        snapshots[name]=snaps
    (out/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    esc=html.escape
    parts=['''<!doctype html><meta charset="utf-8"><title>10 分钟系统声音 A/B</title>
<style>body{font:16px system-ui;max-width:1200px;margin:25px auto;padding:15px;background:#f3f5f9;color:#172338}audio{width:100%}button{padding:10px;margin:5px}section,details{padding:18px;background:white;margin:15px 0;border-radius:10px}p{line-height:1.8}table{width:100%;table-layout:fixed;border-collapse:collapse}td,th{padding:12px;border:1px solid #dde3eb;vertical-align:top;overflow-wrap:anywhere}pre{white-space:pre-wrap}.diff_add{background:#d5f0dc}.diff_sub{background:#f7d6d6}.diff_chg{background:#fff0bd}</style>
<h1>连续十分钟：原版与弱语音增强</h1><p>同一次系统回环采集，增强实时处理；采集结束后依次进行 Nemotron Q8 CPU 流式识别。没有人工逐词参考，更多文字不等于更多正确内容。本页不能证明双路实时 ASR 或翻译无积压。</p>
<section><h2>保持播放位置切换试听</h2><p id="label">原版（无降噪／增益）</p><audio id="player" controls src="raw.wav"></audio>
<button onclick="choose('raw.wav','原版（无降噪／增益）')">原版</button><button onclick="choose('gtcrn.wav','仅 GTCRN')">仅 GTCRN</button><button onclick="choose('enhanced.wav','GTCRN＋弱语音增益')">完整增强</button>
<script>const a=document.getElementById('player');function choose(src,label){let t=a.currentTime,p=!a.paused;a.pause();a.src=src;document.getElementById('label').textContent=label;a.addEventListener('loadedmetadata',()=>{a.currentTime=Math.min(t,a.duration);if(p)a.play().catch(()=>{});},{once:true});a.load();}</script></section>''']
    parts.append(f'<section><h2>运行记录</h2><p>实际采集 {r["audio_seconds"]:.3f} 秒；前端最大排队 {summary["max_queue_seconds"]:.3f} 秒；前端 RTF {summary["frontend_rtf"]:.3f}。{summary["boosted_frame_fraction"]:.1%} 的帧得到增益，提升帧平均 {summary["mean_boosted_gain_db"]:.2f} dB，最大 {summary["maximum_gain_db"]:.2f} dB。正常／非语音门控帧增益均为 1；这是增益模块行为，不表示 GTCRN 未改变这些帧。</p><p>录音来自课堂文件约 10:00–20:00。原版包含与增强共用的采样率转换；设备原始 48 kHz 音频另存为 device-raw.wav。</p></section>')
    parts.append('<table><tr><th>原版</th><th>GTCRN＋弱语音增益</th></tr><tr>')
    for name in ('raw','enhanced'):
        d=r['asr'][name]
        parts.append(f'<td><b>{d["words"]} 词；离线解码 {d["seconds"]:.1f} 秒</b><p>{esc(d["text"])}</p><a href="{name}.txt">完整 TXT</a></td>')
    parts.append('</tr></table><h2>每分钟累计字幕快照</h2><p>快照包含截至该时刻的全部文字，仍可能被后续识别修订；时间是采集时间，不是逐词时间戳。</p>')
    for i in range(min(len(snapshots['raw']),len(snapshots['enhanced']))):
        t=snapshots['raw'][i][0]
        parts.append(f'<details><summary>采集约 {t/60:.1f} 分钟</summary><table><tr>')
        for name in ('raw','enhanced'):parts.append('<td>'+esc(snapshots[name][i][1])+'</td>')
        parts.append('</tr></table></details>')
    (out/'compare.html').write_text('\n'.join(parts),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
