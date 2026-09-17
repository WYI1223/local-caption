"""Offline gain/EQ ablation for quiet classroom audio; not source separation."""
import datetime
import argparse
import hashlib
import html
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from compare_denoise_methods import BASE, read
from compare_noise_profile import write

EQ = 'highpass=f=80,equalizer=f=250:t=q:w=0.7:g=-2,equalizer=f=2000:t=q:w=0.7:g=3'


def rms(x):
    return float(np.sqrt(np.mean(x*x)))


def gain(x):
    # Whole-clip peak guard is an offline experiment, not a causal live limiter.
    return min(2.0, .95/max(1e-10,float(np.max(np.abs(x)))))


def adaptive_level(x):
    """10 ms buffered peak guard, slow level increase; no denoising claim."""
    out=np.empty_like(x)
    level_gain=1.0
    for start in range(0,len(x),160):
        frame=x[start:start+160]
        energy=rms(frame)
        desired=min(3.0,.08/max(energy,1e-10)) if energy>=.004 else 1.0
        tau=1.5 if desired>level_gain else .1
        next_gain=level_gain+(desired-level_gain)*(1-np.exp(-len(frame)/16000/tau))
        ramp=np.linspace(level_gain,next_gain,len(frame))
        ramp=np.minimum(ramp,.95/max(1e-10,float(np.max(np.abs(frame)))))
        out[start:start+len(frame)]=frame*ramp
        level_gain=next_gain
    return out


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume',type=Path)
    args=parser.parse_args()
    inputs=BASE/'diagnostics/noisy106-multisegment-20260916'
    out=args.resume.resolve() if args.resume else BASE/'diagnostics'/('farfield-gain-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    if not out.is_relative_to(BASE/'diagnostics'): parser.error('Output must be inside diagnostics')
    out.mkdir(parents=True,exist_ok=bool(args.resume))
    report={'source_recording':'Recording 20260916184820.m4a','ground_truth':None,
            'scope':'offline peak-guarded gain and EQ, not dereverberation or speech separation',
            'eq':EQ,'results':[]}
    if args.resume:
        report=json.loads((out/'results.json').read_text(encoding='utf-8'))
    print(out,flush=True)
    for label,stamp in [('front','10:00'),('middle','50:00'),('late65','65:00')]:
        source=inputs/f'{label}-speech.wav'
        raw=read(source)
        if not len(raw): raise ValueError('Empty input')
        started=time.perf_counter()
        run=subprocess.run(['ffmpeg','-v','error','-i',str(source),'-af',EQ,'-f','f64le','-acodec','pcm_f64le','-'],
                           capture_output=True,check=True,timeout=30)
        eq=np.frombuffer(run.stdout,'<f8').copy()
        assert len(eq)==len(raw) and np.isfinite(eq).all()
        eq *= rms(raw)/max(1e-10,rms(eq))
        eq *= min(1.0,.95/max(1e-10,float(np.max(np.abs(eq)))))
        eq_seconds=time.perf_counter()-started
        variants=[('raw',raw,1,0),('gain',raw*gain(raw),gain(raw),0),
                  ('eq_matched_rms',eq,1,eq_seconds),('eq_gain',eq*gain(eq),gain(eq),eq_seconds),
                  ('adaptive_level',adaptive_level(raw),None,0)]
        for name,audio,boost,dsp in variants:
            if any(r['clip']==label and r['variant']==name for r in report['results']): continue
            stem=f'{label}-{name}'
            wav=out/(stem+'.wav'); txt=out/(stem+'.txt')
            # The engine refuses an existing output after an interrupted attempt.
            # Only this unrecorded experiment's generated TXT is replaced.
            if txt.exists(): txt.unlink()
            assert len(audio)==len(raw) and np.isfinite(audio).all()
            assert float(np.max(np.abs(audio))) <= 1 if name == 'raw' else float(np.max(np.abs(audio))) < 1
            write(wav,audio)
            # EQ-matched-level copies separate timbre change from louder playback.
            listen=audio*rms(raw)/max(1e-10,rms(audio))
            write(out/(stem+'-listen.wav'),listen)
            began=time.perf_counter()
            with (out/(stem+'.log')).open('wb') as log:
                subprocess.run([str(BASE/'runtime/bin/nemo-speech.exe'),'transcribe',str(wav),'--model',
                    str(BASE/'models/nemotron-speech-streaming-en-0.6b.q8_0.gguf'),'--device','cpu','--stream',
                    '--asr.streaming.rnnt_right_context','1','-o',str(txt)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
            saved=read(wav)
            row={'clip':label,'position':stamp,'variant':name,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                 'seconds':len(raw)/16000,'gain_db':20*np.log10(boost) if boost else 20*np.log10(rms(saved)/rms(raw)),
                 'gain_kind':'time-varying; dB is overall RMS change' if boost is None else 'constant after EQ level matching',
                 'rms_ratio':rms(saved)/rms(raw),
                 'peak':float(np.max(np.abs(saved))),'clipped_samples':int(np.count_nonzero(np.abs(saved)>=32767/32768)),
                 'eq_process_seconds':dsp,'asr_seconds_including_load':time.perf_counter()-began,
                 'audio':wav.name,'text':txt.read_text(encoding='utf-8').strip()}
            row['input_saturated_samples']=int(np.count_nonzero(np.abs(raw)>=32767/32768))
            if name!='raw': assert row['clipped_samples']==0
            report['results'].append(row)
            (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(stem,'gain_db',round(row['gain_db'],2),'words',len(row['text'].split()),flush=True)
    parts=['<!doctype html><meta charset="utf-8"><title>远处小声讲话：增益与频段实验</title><style>body{font:16px system-ui;max-width:1050px;margin:30px auto;padding:20px;background:#f4f6fa;color:#17263d}section{background:white;padding:18px;margin:14px 0;border-radius:10px}audio{width:100%}p{line-height:1.7}</style><h1>远处小声讲话：增益与频段实验</h1><p>源文件 Recording 20260916184820.m4a，106:51.656；约 10 / 50 / 65 分钟，每段实际 24.939 秒。固定 Nemotron Q8 CPU R=1。不是声源分离或去混响，未标注准确率。</p><p>每项上方播放器是实际送入识别的音频，下方可展开同 RMS 试听版，避免把更响直接当成更清楚。增益最高约 +6 dB，按整段峰值留余量；这是离线边界，不能直接当实时实现。频段调整：80 Hz 高通、250 Hz -2 dB、2 kHz +3 dB。adaptive_level 为 10 ms 缓冲的缓慢动态音量调整，最高 3 倍并保护峰值；其 dB 显示整体 RMS 变化，不是固定增益。原音已有的饱和样本不算处理新增削波。</p>']
    for row in report['results']:
        stem=Path(row['audio']).stem
        parts.append(f'<section><h2>{row["position"]} / {row["variant"]}</h2><audio controls preload="none" src="{row["audio"]}"></audio><details><summary>同 RMS 音量试听</summary><audio controls preload="none" src="{stem}-listen.wav"></audio></details><p>{html.escape(row["text"])}</p><small>增益 {row["gain_db"]:.2f} dB，RMS 比 {row["rms_ratio"]:.3f}，削波样本 {row["clipped_samples"]}</small></section>')
    (out/'compare.html').write_text('\n'.join(parts),encoding='utf-8')


if __name__=='__main__': main()
