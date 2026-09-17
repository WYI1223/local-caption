"""Offline fixed noise-profile experiment. Low energy is NOT proof of no speech."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time
import wave

import numpy as np
from compare_denoise_methods import BASE, read

N, HOP = 512, 128
WINDOW = np.hanning(N)


def frames(audio):
    padded = np.pad(audio, (N, N))
    return np.lib.stride_tricks.sliding_window_view(padded, N)[::HOP]


def subtract(audio, noise, cap_db):
    spectrum = np.fft.rfft(frames(audio)*WINDOW, axis=1)
    power = np.abs(spectrum)**2
    gain = np.sqrt(np.maximum(0, 1 - noise[None, :]/np.maximum(power, 1e-20)))
    gain = np.maximum(gain, 10**(-cap_db/20))
    # Smooth across frequency and time; convex smoothing preserves the gain floor.
    gain = (np.pad(gain, ((0,0),(1,1)), mode='edge')[:, :-2] + 2*gain +
            np.pad(gain, ((0,0),(1,1)), mode='edge')[:, 2:])/4
    for i in range(1,len(gain)):
        gain[i] = 0.7*gain[i-1] + 0.3*gain[i]
    chunks = np.fft.irfft(spectrum*gain, n=N, axis=1)*WINDOW
    output = np.zeros((len(chunks)-1)*HOP+N)
    weights = np.zeros_like(output)
    for i, chunk in enumerate(chunks):
        output[i*HOP:i*HOP+N] += chunk
        weights[i*HOP:i*HOP+N] += WINDOW**2
    output /= np.maximum(weights, 1e-20)
    return output[N:N+len(audio)], float(gain.min())


def write(path, audio):
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000)
        f.writeframes((np.clip(audio,-1,32767/32768)*32768).round().astype('<i2').tobytes())


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--background',type=Path,required=True)
    p.add_argument('--input',type=Path,action='append',required=True)
    args=p.parse_args()
    for source in [args.background, *args.input]:
        if len(read(source)) == 0:
            p.error(f'No decoded audio samples: {source}')
    out=BASE/'diagnostics'/('noise-profile-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    background=read(args.background)
    # Pick two non-overlapping one-second candidates; keep all offsets for audit.
    candidates=[]
    for i in range(0,len(background)-16000+1,4000):
        sample=background[i:i+16000]
        rms=float(np.sqrt(np.mean(sample**2)))
        if rms>1e-5:
            candidates.append((rms,i))
    chosen=[]
    for rms,i in sorted(candidates):
        if all(abs(i-j)>=16000 for _,j in chosen): chosen.append((rms,i))
        if len(chosen)==2:break
    if len(chosen)<2: raise ValueError('Not enough non-silent background candidates')
    report={'background':str(args.background.resolve()),'background_sha256':hashlib.sha256(args.background.read_bytes()).hexdigest(),
            'profile_status':'unconfirmed low-energy candidates, may contain speech',
            'profiles':[], 'results':[], 'ground_truth':None}
    profiles={}
    for k,(rms,i) in enumerate(chosen):
        sample=background[i:i+16000]
        label=f'candidate{k+1}'
        write(out/(label+'.wav'),sample)
        # Only interior frames: no zero-padding bias in the fixed noise estimate.
        f=np.lib.stride_tricks.sliding_window_view(sample,N)[::HOP]*WINDOW
        profiles[label]=np.median(np.abs(np.fft.rfft(f,axis=1))**2,axis=0)
        np.save(out/(label+'-power.npy'),profiles[label])
        report['profiles'].append({'name':label,'decoded_offset_seconds':i/16000,'seconds':1,'rms_dbfs':20*np.log10(rms)})
    print(out,flush=True)
    for index,source in enumerate(args.input):
        raw=read(source)
        identity,_=subtract(raw,np.zeros(N//2+1),4)
        assert len(identity)==len(raw) and np.max(np.abs(identity-raw))<1e-10
        variants=[('raw',None,0)]+[(f'{name}-{cap}dB',profile,cap) for name,profile in profiles.items() for cap in (2,4)]
        for name,profile,cap in variants:
            began=time.perf_counter()
            enhanced,min_gain=(raw,1.0) if profile is None else subtract(raw,profile,cap)
            dsp=time.perf_counter()-began
            assert len(enhanced)==len(raw) and np.isfinite(enhanced).all()
            assert min_gain>=10**(-cap/20)-1e-12
            stem=f'{index}-{name}'
            wav=out/(stem+'.wav'); txt=out/(stem+'.txt')
            write(wav,enhanced)
            began=time.perf_counter()
            with (out/(stem+'.log')).open('wb') as log:
                subprocess.run([str(BASE/'runtime/bin/nemo-speech.exe'),'transcribe',str(wav),'--model',
                    str(BASE/'models/nemotron-speech-streaming-en-0.6b.q8_0.gguf'),'--device','cpu','--stream',
                    '--asr.streaming.rnnt_right_context','1','-o',str(txt)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
            row={'source':str(source.resolve()),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                 'variant':name,'audio':wav.name,'seconds':len(raw)/16000,'preprocess_seconds':dsp,
                 'asr_seconds_including_load':time.perf_counter()-began,'minimum_spectral_gain':min_gain,
                 'rms_ratio':float(np.sqrt(np.mean(enhanced**2)/np.mean(raw**2))),
                 'text':txt.read_text(encoding='utf-8').strip()}
            report['results'].append(row)
            (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(stem,round(dsp,3),len(row['text'].split()),flush=True)


if __name__=='__main__': main()
