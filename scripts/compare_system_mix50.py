"""Supplement a saved system capture with mix50 / mix50+speech gain and PCM baseline."""
import argparse
import datetime
import hashlib
import html
import json
import sys
import time
import wave
from pathlib import Path
import numpy as np
from system_weak_voice_ab import WeakVoiceGain, save_wav, BASE

sys.path.insert(0,str(BASE/'app'))
from asr_stream import StreamRecognizer
from transcript_history import TranscriptHistory


def read(path):
    with wave.open(str(path)) as f:
        assert f.getframerate()==16000 and f.getnchannels()==1 and f.getsampwidth()==2
        return np.frombuffer(f.readframes(f.getnframes()),'<i2').astype(np.float32)/32768


def render(out,report,old):
    labels={'raw_pcm':'原版（本轮 PCM 基线）','mix50':'50% 原音＋50% GTCRN','mix50_gain':'50% 混合＋弱语音动态增益'}
    parts=['''<!doctype html><meta charset="utf-8"><title>十分钟 50% mix 补测</title><style>body{font:16px system-ui;max-width:1200px;margin:24px auto;padding:16px;background:#f2f5f9;color:#18253b}section{background:white;padding:18px;margin:18px 0;border-radius:12px}audio{width:100%}p{line-height:1.8}button{padding:10px;margin:5px}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #ccd4df}</style><h1>同一十分钟系统录音：50% mix 补测</h1><p>复用上次保存的原音与 GTCRN PCM16 音频，等权相加，不做额外音量匹配；增益版在混合后进行语音检测和增益，沿用原参数。额外重跑原版 PCM 基线，避免把上轮 float32 与本轮 PCM16 输入差异误算成增强效果。本轮为文件回放解码，不是重新采集或实时积压测试。无人工真值，词数不是准确率。</p>
<section><h2>同位置切换试听</h2><audio id="player" controls src="raw_pcm.wav"></audio><p id="label">原版</p>''']
    for key,label in labels.items():
        parts.append(f'<button onclick="choose(\'{key}.wav\',\'{label}\')">{label}</button>')
    parts.append('''<script>const a=document.getElementById('player');function choose(src,label){const t=a.currentTime,playing=!a.paused;a.pause();a.src=src;document.getElementById('label').textContent=label;a.addEventListener('loadedmetadata',()=>{a.currentTime=Math.min(t,a.duration);if(playing)a.play().catch(()=>{});},{once:true});a.load();}</script></section>''')
    parts.append('<table><tr><th>方案</th><th>词数（不是正确词数）</th><th>解码秒数</th></tr>')
    for key,label in labels.items():
        d=report['asr'].get(key)
        parts.append(f'<tr><td>{label}</td><td>{d["words"] if d else "处理中"}</td><td>{round(d["seconds"],1) if d else "—"}</td></tr>')
    parts.append('</table>')
    for key,label in labels.items():
        if key in report['asr']:
            d=report['asr'][key]
            parts.append(f'<section><h2>{label}</h2><audio controls src="{key}.wav"></audio><p>{html.escape(d["text"])}</p><a href="{key}.txt">完整 TXT</a></section>')
    parts.append('<section><h2>上轮参照（输入精度不同，不作严格配对）</h2>')
    for key,label in [('raw','原版 float32'),('enhanced','100% GTCRN＋动态增益 float32')]:
        d=old['asr'][key]
        parts.append(f'<details><summary>{label}：{d["words"]} 词</summary><p>{html.escape(d["text"])}</p></details>')
    parts.append('<p><a href="../compare.html">上轮完整系统采集对比页</a></p></section>')
    (out/'compare.html').write_text('\n'.join(parts),encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path)
    source=p.parse_args().source.resolve()
    assert source.is_relative_to(BASE/'diagnostics')
    out=source/('mix50-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    old=json.loads((source/'results.json').read_text(encoding='utf-8'))
    raw=read(source/'raw.wav');gt=read(source/'gtcrn.wav')
    assert len(raw)==len(gt)==9630720
    mix=(raw*.5+gt*.5).astype(np.float32)
    gain=WeakVoiceGain(BASE/'diagnostics/enhancement-models/silero_vad.onnx')
    started=time.perf_counter();parts=[]
    for i in range(0,len(mix),1600):parts.append(gain.process(mix[i:i+1600]))
    parts.append(gain.process(np.empty(0,np.float32),final=True))
    enhanced=np.concatenate(parts)
    report=dict(source=str(source),audio_seconds=len(raw)/16000,
        input_precision='Saved PCM16 from original system capture; new ASR inputs saved losslessly as npy',
        mixing='0.5 * raw + 0.5 * GTCRN, no RMS renormalization; previous alignment measured zero',
        source_sha256={n:hashlib.sha256((source/(n+'.wav')).read_bytes()).hexdigest() for n in ['raw','gtcrn']},
        gain_dsp_seconds=time.perf_counter()-started,gain_parameters=old['parameters'],
        boosted_frames=sum(r['gain']>1.001 for r in gain.rows),gain_frames=len(gain.rows),
        mean_boosted_db=float(np.mean([20*np.log10(r['gain']) for r in gain.rows if r['gain']>1.001])),
        max_gain_db=float(20*np.log10(max(r['gain'] for r in gain.rows))),asr={})
    assert len(enhanced)==len(raw) and np.isfinite(enhanced).all()
    assert all(r['gain']==1 for r in gain.rows if not r['weak'])
    assert np.count_nonzero(abs(enhanced)>=32767/32768)<=np.count_nonzero(abs(mix)>=32767/32768)
    arrays={'raw_pcm':raw,'mix50':mix,'mix50_gain':enhanced}
    for key,x in arrays.items():save_wav(out/(key+'.wav'),x);np.save(out/(key+'-asr-input.npy'),x)
    (out/'gain-metrics.json').write_text(json.dumps(gain.rows),encoding='utf-8')
    def save():
        (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        render(out,report,old)
    save();print(out,flush=True)
    recognizer=StreamRecognizer()
    try:
        for k,(key,x) in enumerate(arrays.items()):
            if k:recognizer.reset_stream()
            history=TranscriptHistory();finals=0;processed=0.;started=time.monotonic()
            with (out/(key+'-events.jsonl')).open('w',encoding='utf-8') as log:
                def consume(results):
                    nonlocal finals,processed
                    for r in results:
                        history.observe(r['text'],r['final']);finals+=int(r['final']);processed=r['processed']
                        log.write(json.dumps(r,ensure_ascii=False)+'\n');log.flush()
                for i in range(0,len(x),1600):
                    consume(recognizer.results());recognizer.push(x[i:i+1600],16000)
                    if i%960000==0:print(key,round(i/16000),flush=True)
                consume(recognizer.finish())
            assert abs(processed-len(x)/16000)<.1
            (out/(key+'.txt')).write_text(history.text,encoding='utf-8')
            report['asr'][key]=dict(words=len(history.text.split()),text=history.text,
                seconds=time.monotonic()-started,final_events=finals,processed_seconds=processed)
            save();print(key,'DONE',report['asr'][key]['words'],flush=True)
    finally:recognizer.close()
    parent=source/'compare.html';page=parent.read_text(encoding='utf-8')
    page+=f'<section><h2>补测：50% 混合与动态增益</h2><a href="{out.name}/compare.html">查看同一十分钟录音的 50% mix 完整对照</a></section>'
    parent.write_text(page,encoding='utf-8')
    print('DONE',out,flush=True)


if __name__=='__main__':main()
