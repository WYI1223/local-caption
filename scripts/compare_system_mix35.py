"""Same captured PCM sources and native ASR as mix50; 35% GTCRN, no gain."""
import datetime
import hashlib
import html
import json
import time
import numpy as np
from compare_system_mix50 import BASE, read, save_wav, StreamRecognizer, TranscriptHistory


def main():
    source=BASE/'diagnostics/system-weak-ab-20260916-213339'
    previous=source/'mix50-20260916-215602'
    baseline=json.loads((previous/'results.json').read_text(encoding='utf-8'))
    hashes={n:hashlib.sha256((source/(n+'.wav')).read_bytes()).hexdigest() for n in ('raw','gtcrn')}
    assert hashes==baseline['source_sha256'], 'Sources changed since baseline'
    raw=read(source/'raw.wav');gt=read(source/'gtcrn.wav')
    assert np.array_equal(raw,np.load(previous/'raw_pcm-asr-input.npy'))
    assert np.array_equal(raw*.5+gt*.5,np.load(previous/'mix50-asr-input.npy'))
    x=(raw*.65+gt*.35).astype(np.float32)
    assert len(x)==len(raw)==len(gt) and np.isfinite(x).all()
    out=source/('mix35-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    np.save(out/'mix35-asr-input.npy',x);save_wav(out/'mix35.wav',x)
    report=dict(source_sha256=hashes,baseline_report=str(previous/'results.json'),
        mixing='0.65 * raw + 0.35 * GTCRN; no gain, no RMS matching',audio_seconds=len(x)/16000,
        baseline_arrays_exactly_reproduced=True,asr={})
    (out/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(out,flush=True)
    recognizer=StreamRecognizer();history=TranscriptHistory();finals=0;processed=0.
    began=time.monotonic()
    try:
        with (out/'mix35-events.jsonl').open('w',encoding='utf-8') as log:
            def consume(results):
                nonlocal finals,processed
                for r in results:
                    history.observe(r['text'],r['final']);finals+=int(r['final']);processed=r['processed']
                    log.write(json.dumps(r,ensure_ascii=False)+'\n');log.flush()
            for i in range(0,len(x),1600):
                consume(recognizer.results());recognizer.push(x[i:i+1600],16000)
                if i%960000==0:print('mix35',round(i/16000),flush=True)
            consume(recognizer.finish())
    finally:recognizer.close()
    assert finals and abs(processed-len(x)/16000)<.001
    report['asr']=dict(text=history.text,words=len(history.text.split()),seconds=time.monotonic()-began,
        final_events=finals,processed_seconds=processed)
    (out/'mix35.txt').write_text(history.text,encoding='utf-8')
    (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    options=[('原版',f'../{previous.name}/raw_pcm',baseline['asr']['raw_pcm']),
             ('35% GTCRN（65% 原音）','mix35',report['asr']),
             ('50% GTCRN（50% 原音）',f'../{previous.name}/mix50',baseline['asr']['mix50'])]
    p25=source/'mix25-20260916-224152'
    r25=json.loads((p25/'results.json').read_text(encoding='utf-8'))
    assert r25['source_sha256']==hashes
    options.insert(1,('25% GTCRN（75% 原音）',f'../{p25.name}/mix25',r25['asr']))
    parts=['''<!doctype html><meta charset="utf-8"><title>35% GTCRN 对照</title><style>body{font:16px system-ui;max-width:1150px;margin:30px auto;padding:15px;background:#f3f5f9;color:#17253a}section{padding:18px;background:white;margin:15px 0}audio{width:100%}p{line-height:1.8}button{padding:10px;margin:5px}td,th{padding:12px;border:1px solid #ddd}table{border-collapse:collapse;width:100%}</style><h1>同一十分钟录音：原版／25%／35%／50% GTCRN</h1><p>比例指 GTCRN 在波形混合中的占比，均不加动态增益。复用相同 PCM 源文件与相同 Nemotron Q8 CPU 流式配置，只新运行 35% 版本；原版、25% 和 50% 结果来自先前实测。没有人工真值，词数不是准确率；本轮不是实时采集或队列测试。</p><section><audio id="player" controls src="mix35.wav"></audio><p id="label">35% GTCRN</p>''']
    for label,path,d in options:parts.append(f'<button onclick="choose(\'{path}.wav\',\'{label}\')">{label}</button>')
    parts.append('''<script>const a=document.getElementById('player');function choose(src,label){const t=a.currentTime,p=!a.paused;a.pause();a.src=src;document.getElementById('label').textContent=label;a.addEventListener('loadedmetadata',()=>{a.currentTime=Math.min(t,a.duration);if(p)a.play().catch(()=>{});},{once:true});a.load();}</script></section><table><tr><th>方案</th><th>词数</th></tr>''')
    for label,path,d in options:parts.append(f'<tr><td>{label}</td><td>{d["words"]}</td></tr>')
    parts.append('</table>')
    for label,path,d in options:parts.append(f'<section><h2>{label}</h2><audio controls src="{path}.wav"></audio><p>{html.escape(d["text"])}</p><a href="{path}.txt">完整 TXT</a></section>')
    (out/'compare.html').write_text('\n'.join(parts),encoding='utf-8')
    for parent,link in [(source/'compare.html',out.name+'/compare.html'),(previous/'compare.html','../'+out.name+'/compare.html')]:
        with parent.open('a',encoding='utf-8') as f:f.write(f'<section><h2>35% 补测</h2><a href="{link}">查看原版／25%／35%／50% 对照</a></section>')
    print('DONE',report['asr']['words'],flush=True)


if __name__=='__main__':main()
