"""Paired, offline mild level control on previously verified GTCRN outputs."""
import datetime
import hashlib
import html
import json
import subprocess
import time
from pathlib import Path
import numpy as np
from compare_denoise_methods import BASE, read
from compare_noise_profile import write


def mild_level(x):
    y=np.empty_like(x); gain=1.0
    for start in range(0,len(x),160):
        frame=x[start:start+160]; rms=float(np.sqrt(np.mean(frame**2)))
        target=max(1.0,min(2.0,.063/max(1e-10,rms))) if rms>=.004 else 1.0
        tau=1.5 if target>gain else .2
        end=gain+(target-gain)*(1-np.exp(-len(frame)/16000/tau))
        ramp=np.linspace(gain,end,len(frame))
        # Quiet frames are passed at unity; this is not a speech detector.
        if rms<.004:ramp=np.ones_like(ramp)
        ramp=np.minimum(ramp,.95/max(1e-10,float(np.max(abs(frame)))))
        y[start:start+len(frame)]=frame*ramp;gain=end
    return y


def main():
    previous=BASE/'diagnostics/neural-wpe-20260916-205114'
    old=json.loads((previous/'results.json').read_text(encoding='utf-8'))
    out=BASE/'diagnostics'/('gtcrn-level-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    report={'baseline_report':str(previous/'results.json'),'parameters':{'target_rms':.063,'max_gain':2,'floor_rms':.004,'rise_seconds':1.5,'fall_seconds':.2,'frame_ms':10,'peak_ceiling':.95},'ground_truth':None,'results':[]}
    print(out,flush=True)
    for base in old['results']:
        if base['variant'] not in ('gtcrn','gtcrn_mix50'):continue
        source=previous/(base['stem']+'.wav'); x=read(source)
        began=time.perf_counter();y=mild_level(x);dsp=time.perf_counter()-began
        assert len(x)==len(y) and np.isfinite(y).all() and max(abs(y))<=.95+1e-12
        stem=base['stem']+'-level'; audio=out/(stem+'.wav'); txt=out/(stem+'.txt')
        write(audio,y)
        # Copies deliberately share the source path for baseline playback.
        began=time.perf_counter()
        with (out/(stem+'.log')).open('wb') as log:
            subprocess.run([str(BASE/'runtime/bin/nemo-speech.exe'),'transcribe',str(audio),'--model',
                str(BASE/'models/nemotron-speech-streaming-en-0.6b.q8_0.gguf'),'--device','cpu','--stream',
                '--asr.streaming.rnnt_right_context','1','-o',str(txt)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
        ratio=float(np.sqrt(np.mean(y*y)/np.mean(x*x)))
        listen=y/ratio;listen*=min(1,.98/max(1e-10,float(max(abs(listen)))))
        write(out/(stem+'-listen.wav'),listen)
        row={'clip':base['clip'],'position':base['position'],'variant':base['variant'],
             'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'source':str(source),'stem':stem,
             'dsp_seconds':dsp,'overall_gain_db':float(20*np.log10(ratio)),
             'peak':float(max(abs(y))),'saturated_samples':int(np.count_nonzero(abs(read(audio))>=32767/32768)),
             'asr_seconds':time.perf_counter()-began,'baseline_text':base['text'],
             'text':txt.read_text(encoding='utf-8').strip()}
        assert row['saturated_samples']==0
        report['results'].append(row)
        (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(stem,round(row['overall_gain_db'],2),len(row['text'].split()),flush=True)
    parts=['<!doctype html><meta charset="utf-8"><title>GTCRN 加轻度增益</title><style>body{font:16px system-ui;max-width:1000px;margin:30px auto;padding:20px;background:#f4f6fa;color:#17263d}section{background:white;padding:18px;margin:15px 0;border-radius:12px}audio{width:100%}p{line-height:1.7}</style><h1>GTCRN＋轻度动态增益</h1><p>同一 106 分钟课堂录音的约 10 / 50 / 65 分钟片段。对上一轮保存的 GTCRN 和 50% 回混输出加增益，上限 2 倍，缓慢提升、10 ms 峰值保护。仅低能量判断，不是语音检测；不能恢复模糊细节。基线文字复用上一轮同 WAV 的实际识别结果，本轮只重跑增益后的六段。</p>']
    for r in report['results']:
        original=Path(r['source']).name
        parts.append(f'<section><h2>{r["position"]} / {r["variant"]}</h2><b>仅 GTCRN / 回混基线</b><audio controls preload="none" src="../{previous.name}/{original}"></audio><p>{html.escape(r["baseline_text"])}</p><b>加轻度增益（整体 RMS {r["overall_gain_db"]:+.2f} dB）</b><audio controls preload="none" src="{r["stem"]}.wav"></audio><p>{html.escape(r["text"])}</p><details><summary>增益后音量匹配试听，带峰值保护</summary><audio controls preload="none" src="{r["stem"]}-listen.wav"></audio></details></section>')
    (out/'compare.html').write_text('\n'.join(parts),encoding='utf-8')


if __name__=='__main__':main()
