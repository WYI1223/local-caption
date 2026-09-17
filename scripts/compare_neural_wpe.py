"""Isolated offline GTCRN/DPDFNet2/single-channel WPE comparison."""
import argparse
import datetime
import hashlib
import html
import importlib.metadata
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from scipy.signal import correlate, correlation_lags
import sherpa_onnx as sh
from nara_wpe.utils import stft, istft
from nara_wpe.wpe import wpe
from compare_denoise_methods import BASE, read
from compare_noise_profile import write


def energy(x): return float(np.sqrt(np.mean(x*x)))


def alignment(raw, enhanced):
    c=correlate(enhanced,raw,method='fft')
    lags=correlation_lags(len(enhanced),len(raw))
    keep=np.abs(lags)<=1600
    lag=int(lags[keep][np.argmax(c[keep])])
    return lag


def render(out, report):
    parts=['<!doctype html><meta charset="utf-8"><title>GTCRN / DPDFNet2 / WPE 实测</title><style>body{font:16px system-ui;max-width:1080px;margin:24px auto;padding:20px;background:#f4f6fa;color:#18263a}section{background:white;padding:18px;border-radius:12px;margin:15px 0}audio{width:100%}p{line-height:1.7}small{color:#526277}</style><h1>三个方案：课堂同段实测</h1><p>源录音 Recording 20260916184820.m4a（106:51.656），约 10 / 50 / 65 分钟处，各 24.939 秒。每段增强前加入相邻 5 秒前导，截取目标段送入相同 Nemotron Q8 CPU 流式 R=1。mix50 为对齐后 50% 原音＋50% 增强音。</p><p>本页为离线文件实验；WPE 采用整段统计。预处理 RTF 不包含 ASR/翻译，不能代表实时字幕延迟或无积压。没有人工参考稿，词数不代表准确率。上方为实际送模音频，下方可试听音量匹配副本（峰值保护可能限制匹配）。</p>']
    for r in report['results']:
        parts.append(f'<section><h2>{r["position"]} / {r["variant"]}</h2><audio controls preload="none" src="{r["stem"]}.wav"></audio><details><summary>音量匹配试听（带峰值保护）</summary><audio controls preload="none" src="{r["stem"]}-listen.wav"></audio></details><p>{html.escape(r["text"]) or "（无识别文字）"}</p><small>预处理 RTF {r["enhancement_rtf"]:.3f}；送模 RMS 比 {r["rms_ratio"]:.3f}；波形校正 {r["alignment_samples"]} 样本；峰值保护系数 {r["peak_scale"]:.3f}</small></section>')
    (out/'compare.html').write_text('\n'.join(parts),encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--resume',type=Path)
    args=p.parse_args()
    out=args.resume.resolve() if args.resume else BASE/'diagnostics'/('neural-wpe-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    if not out.is_relative_to(BASE/'diagnostics'):p.error('Output must be inside diagnostics')
    out.mkdir(parents=True,exist_ok=bool(args.resume))
    report={'ground_truth':None,'results':[],'enhancement':[],
            'versions':{n:importlib.metadata.version(n) for n in ['sherpa-onnx','nara-wpe','numpy','scipy']},
            'wpe':{'taps':10,'delay':3,'iterations':3,'size':512,'shift':128,'channels':1,'mode':'offline full statistics'},
            'warmup_seconds':5,'model_load_seconds':{}}
    if args.resume:report=json.loads((out/'results.json').read_text(encoding='utf-8'))
    def save():
        (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8'); render(out,report)
    models={}
    for name,file in [('gtcrn','gtcrn_simple.onnx'),('dpdfnet','dpdfnet2.onnx')]:
        path=BASE/'diagnostics/enhancement-models'/file
        config=sh.OfflineSpeechDenoiserModelConfig(num_threads=1,provider='cpu')
        if name=='gtcrn':config.gtcrn=sh.OfflineSpeechDenoiserGtcrnModelConfig(model=str(path))
        else:config.dpdfnet=sh.OfflineSpeechDenoiserDpdfNetModelConfig(model=str(path),attenuation_limit_db=0)
        conf=sh.OfflineSpeechDenoiserConfig(model=config)
        assert conf.validate(),str(conf)
        began=time.perf_counter(); models[name]=sh.OfflineSpeechDenoiser(conf)
        report['model_load_seconds'][name]=time.perf_counter()-began
        report.setdefault('model_sha256',{})[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    print(out,flush=True);save()
    for label,position in [('front','10:00'),('middle','50:00'),('late65','65:00')]:
        source=BASE/'diagnostics/noisy106-multisegment-20260916'/f'{label}-speech.wav'
        raw=read(source); background=read(source.with_name(f'{label}-background.wav'))[-80000:]
        x=np.concatenate([background,raw,np.zeros(16000)]).astype(np.float32)
        variants=[('raw',raw,0.0,0)]
        for name in ['gtcrn','dpdfnet','wpe']:
            began=time.perf_counter()
            if name=='wpe':
                y=stft(x[None,:],size=512,shift=128)
                identity=istft(y,size=512,shift=128)[0]
                assert len(identity)>=len(x) and np.max(np.abs(identity[:len(x)]-x))<1e-5
                z=wpe(y.transpose(2,0,1),taps=10,delay=3,iterations=3,statistics_mode='full')
                enhanced=istft(z.transpose(1,2,0),size=512,shift=128)[0]
            else:
                result=models[name].run(x,16000)
                assert result.sample_rate==16000
                enhanced=np.asarray(result.samples,dtype=np.float64)
            elapsed=time.perf_counter()-began
            assert np.isfinite(enhanced).all()
            lag=alignment(x,enhanced)
            start=len(background)+lag
            assert start>=0 and start+len(raw)<=len(enhanced),'Missing target samples'
            target=enhanced[start:start+len(raw)].copy()
            report['enhancement'].append({'clip':label,'method':name,'seconds':elapsed,'rtf':elapsed/(len(x)/16000),
                'alignment_samples':lag,'input_samples':len(x),'output_samples':len(enhanced),'target_samples':len(target)})
            variants.append((name,target,elapsed/(len(x)/16000),lag))
            if name!='wpe':variants.append((name+'_mix50',.5*raw+.5*target,elapsed/(len(x)/16000),lag))
        for name,audio,rtf,lag in variants:
            if any(r['clip']==label and r['variant']==name for r in report['results']):continue
            stem=f'{label}-{name}'; wav=out/(stem+'.wav'); txt=out/(stem+'.txt')
            scale=min(1.0,.98/max(1e-10,float(np.max(np.abs(audio))))) if name!='raw' else 1.0
            audio=audio*scale;write(wav,audio)
            listen=audio*energy(raw)/max(1e-10,energy(audio))
            listen*=min(1.0,.98/max(1e-10,float(np.max(np.abs(listen)))))
            write(out/(stem+'-listen.wav'),listen)
            if name!='raw':assert np.count_nonzero(np.abs(read(wav))>=32767/32768)==0
            began=time.perf_counter()
            with (out/(stem+'.log')).open('wb') as log:
                subprocess.run([str(BASE/'runtime/bin/nemo-speech.exe'),'transcribe',str(wav),'--model',
                    str(BASE/'models/nemotron-speech-streaming-en-0.6b.q8_0.gguf'),'--device','cpu','--stream',
                    '--asr.streaming.rnnt_right_context','1','--force','-o',str(txt)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
            row={'clip':label,'position':position,'variant':name,'stem':stem,'seconds':len(raw)/16000,
                 'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'enhancement_rtf':rtf,
                 'alignment_samples':lag,'peak_scale':scale,'rms_ratio':energy(audio)/energy(raw),
                 'listen_rms_ratio':energy(listen)/energy(raw),'asr_seconds_including_load':time.perf_counter()-began,
                 'text':txt.read_text(encoding='utf-8').strip()}
            report['results'].append(row);save()
            print(stem,'rtf',round(rtf,3),'lag',lag,'words',len(row['text'].split()),flush=True)


if __name__=='__main__':main()
