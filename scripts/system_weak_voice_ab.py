"""Windows system-loopback A/B: realtime frontend, then sequential ASR (not dual live ASR).

Run with diagnostics/enhancement-env/Scripts/python.exe. Private outputs stay in diagnostics.
"""
import argparse
import datetime
import hashlib
import html
import json
import queue
import sys
import threading
import time
import wave
import winsound
from pathlib import Path

import numpy as np
import pyaudiowpatch as pa
import sherpa_onnx as sh
from scipy.signal import firwin, lfilter

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'app'))


class WeakVoiceGain:
    """32 ms speech-gated gain; uncertain/non-speech and normal frames use unity."""
    def __init__(self, model):
        c = sh.VadModelConfig(silero_vad=sh.SileroVadModelConfig(
            model=str(model), threshold=.5, min_speech_duration=.064,
            min_silence_duration=.096, window_size=512), num_threads=1)
        self.vad = sh.VoiceActivityDetector(c, buffer_size_in_seconds=30)
        self.pending = np.empty(0, np.float32)
        self.gain = 1.
        self.rows = []

    def frame(self, x):
        padded = np.pad(x, (0, 512-len(x)))
        self.vad.accept_waveform(padded)
        speech = self.vad.is_speech_detected()
        while not self.vad.empty():
            self.vad.pop()
        rms = float(np.sqrt(np.mean(x*x)))
        peak = float(np.max(np.abs(x)))
        impulse = peak > .12 and peak > 5 * max(rms, 1e-9)
        weak = speech and .0032 <= rms < .05 and not impulse
        target = min(2., .063 / rms) if weak else 1.
        before = self.gain
        if weak:
            tau = 1.5 if target > before else .2
            self.gain += (target-before)*(1-np.exp(-len(x)/16000/tau))
            ramp = np.linspace(before, self.gain, len(x))
        else:
            self.gain = 1.
            ramp = np.ones(len(x))
        # Only protect added gain. Never clip or alter an unboosted normal frame.
        ramp = np.maximum(1., np.minimum(ramp, .95 / max(peak, 1e-9)))
        y = (x*ramp).astype(np.float32)
        self.rows.append(dict(speech=bool(speech), weak=bool(weak), impulse=bool(impulse),
                             rms=rms, gain=float(np.mean(ramp)), samples=len(x)))
        return y

    def process(self, x, final=False):
        self.pending = np.concatenate((self.pending, x))
        parts = []
        while len(self.pending) >= 512:
            parts.append(self.frame(self.pending[:512]))
            self.pending = self.pending[512:]
        if final and len(self.pending):
            parts.append(self.frame(self.pending)); self.pending = np.empty(0, np.float32)
        return np.concatenate(parts) if parts else np.empty(0, np.float32)


def save_wav(path, x, rate=16000):
    with wave.open(str(path), 'wb') as f:
        f.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        f.writeframes((np.clip(x, -1, 32767/32768)*32768).astype('<i2').tobytes())


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--play', type=Path, required=True)
    p.add_argument('--seconds', type=float, default=0, help='Limit for smoke test')
    args=p.parse_args()
    with wave.open(str(args.play)) as f:
        duration=f.getnframes()/f.getframerate()
    duration=min(duration,args.seconds) if args.seconds else duration
    out=BASE/'diagnostics'/('system-weak-ab-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir();print(out,flush=True)
    models=BASE/'diagnostics/enhancement-models'
    model=sh.OfflineSpeechDenoiserModelConfig(gtcrn=sh.OfflineSpeechDenoiserGtcrnModelConfig(
        model=str(models/'gtcrn_simple.onnx')), num_threads=1)
    denoiser=sh.OnlineSpeechDenoiser(sh.OnlineSpeechDenoiserConfig(model=model))
    gain=WeakVoiceGain(models/'silero_vad.onnx')
    audio=pa.PyAudio();device=audio.get_default_wasapi_loopback()
    rate=int(device['defaultSampleRate']);channels=int(device['maxInputChannels'])
    if rate != 48000:
        raise RuntimeError('This experimental resampler requires a 48 kHz system device')
    total=int((duration+2)*rate);captured=0;faults=[];q=queue.Queue(maxsize=120)
    report=dict(device=device,source=str(args.play),source_sha256=hashlib.sha256(args.play.read_bytes()).hexdigest(),
        playback_seconds=duration,mode='shared WASAPI capture; live frontend; sequential ASR after capture',
        parameters=dict(vad_threshold=.5,weak_rms_min=.0032,weak_rms_max=.05,target_rms=.063,
                        max_gain=2,rise_seconds=1.5,fall_seconds=.2),
        model_sha256={f:hashlib.sha256((models/f).read_bytes()).hexdigest() for f in ['gtcrn_simple.onnx','silero_vad.onnx']})
    def callback(data,frames,timing,status):
        nonlocal captured
        if status:faults.append(str(status))
        x=np.frombuffer(data,np.float32).reshape(-1,channels)[:max(0,total-captured)].copy()
        captured+=len(x)
        try:q.put_nowait(x)
        except queue.Full:faults.append('capture queue overflow');return None,pa.paAbort
        return None,pa.paComplete if captured>=total or faults else pa.paContinue
    stream=audio.open(format=pa.paFloat32,channels=channels,rate=rate,input=True,
        input_device_index=device['index'],frames_per_buffer=4800,stream_callback=callback,start=False)
    # WASAPI may stop delivering idle callbacks when playback ends. A zero-valued
    # output stream preserves the capture clock through the trailing silence.
    output_device=audio.get_host_api_info_by_type(pa.paWASAPI)['defaultOutputDevice']
    output_channels=int(audio.get_device_info_by_index(output_device)['maxOutputChannels'])
    keepalive=audio.open(format=pa.paFloat32,channels=output_channels,rate=rate,output=True,
        output_device_index=output_device,frames_per_buffer=4800,
        stream_callback=lambda data,n,t,status:(bytes(n*output_channels*4),pa.paContinue))
    b=firwin(97,7200,fs=48000);zi=np.zeros(96);raw=[];clean=[];enhanced=[];metrics=[]
    dsp=0.;processed=0;started=time.monotonic();last=0
    def play():
        time.sleep(1)
        winsound.PlaySound(str(args.play),winsound.SND_FILENAME | winsound.SND_ASYNC)
    try:
        stream.start_stream();threading.Thread(target=play,daemon=True).start()
        print('SYSTEM PLAYBACK AND CAPTURE STARTED',flush=True)
        with (out/'capture-metrics.jsonl').open('w',encoding='utf-8') as log, wave.open(str(out/'device-raw.wav'),'wb') as archive:
            archive.setparams((channels,2,rate,0,'NONE','not compressed'))
            while stream.is_active() or not q.empty():
                try:x=q.get(timeout=.2)
                except queue.Empty:continue
                began=time.perf_counter()
                archive.writeframes((np.clip(x,-1,32767/32768)*32768).astype('<i2').tobytes())
                mono=x.mean(axis=1)
                filtered,zi=lfilter(b,[1.],mono,zi=zi)
                # Callback sizes and final capture count are multiples of three.
                common=filtered[::3].astype(np.float32);raw.append(common)
                y=np.asarray(denoiser.run(common,16000).samples,dtype=np.float32)
                clean.append(y);enhanced.append(gain.process(y))
                processed+=len(x);dsp+=time.perf_counter()-began
                row=dict(elapsed=time.monotonic()-started,captured_seconds=captured/rate,
                    frontend_processed_seconds=processed/rate,queued_seconds=(captured-processed)/rate,
                    dsp_seconds=dsp)
                metrics.append(row);log.write(json.dumps(row)+'\n');log.flush()
                if row['elapsed']-last>=30:
                    print('capture',round(row['captured_seconds'],1),'queue',row['queued_seconds'],flush=True);last=row['elapsed']
        tail=np.asarray(denoiser.flush().samples,dtype=np.float32)
        clean.append(tail);enhanced.append(gain.process(tail,final=True))
    finally:
        winsound.PlaySound(None,0)
        stream.close();keepalive.close();audio.terminate()
    arrays={'raw':np.concatenate(raw),'gtcrn':np.concatenate(clean),'enhanced':np.concatenate(enhanced)}
    assert len({len(x) for x in arrays.values()})==1,[(k,len(v)) for k,v in arrays.items()]
    for name,x in arrays.items():
        assert np.isfinite(x).all()
        np.save(out/(name+'-asr-input.npy'),x)
        save_wav(out/(name+'.wav'),x)
    report.update(faults=faults,captured_seconds=captured/rate,audio_seconds=len(arrays['raw'])/16000,
        max_frontend_queue_seconds=max(r['queued_seconds'] for r in metrics),frontend_seconds=dsp,
        gain_frames=len(gain.rows),speech_frames=sum(r['speech'] for r in gain.rows),
        boosted_frames=sum(r['gain']>1.001 for r in gain.rows),max_gain=max(r['gain'] for r in gain.rows),
        saturation_samples={k:int(np.count_nonzero(abs(v)>=32767/32768)) for k,v in arrays.items()})
    (out/'gain-metrics.json').write_text(json.dumps(gain.rows),encoding='utf-8')
    def save(): (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    if faults or abs(captured/rate-duration-2)>.1:raise RuntimeError('Incomplete capture; see results.json')
    print('CAPTURE COMPLETE; sequential ASR begins',flush=True)
    from asr_stream import StreamRecognizer
    from transcript_history import TranscriptHistory
    recognizer=StreamRecognizer();report['asr']={}
    try:
        for name in ('raw','enhanced'):
            if name!='raw':recognizer.reset_stream()
            history=TranscriptHistory();events=[];began=time.monotonic()
            def consume(results):
                for r in results:
                    history.observe(r['text'],r['final']);events.append(r)
                    log.write(json.dumps(r,ensure_ascii=False)+'\n');log.flush()
            x=arrays[name]
            with (out/(name+'-events.jsonl')).open('w',encoding='utf-8') as log:
                for start in range(0,len(x),1600):
                    consume(recognizer.results())
                    recognizer.push(x[start:start+1600],16000)
                    if start%480000==0:
                        print(name,'ASR',round(start/16000),flush=True)
                consume(recognizer.finish())
            (out/(name+'.txt')).write_text(history.text,encoding='utf-8')
            report['asr'][name]=dict(seconds=time.monotonic()-began,words=len(history.text.split()),
                final_events=sum(r['final'] for r in events),text=history.text)
            save()
    finally:recognizer.close()
    parts=['<!doctype html><meta charset="utf-8"><title>系统声音十分钟 A/B</title><style>body{font:16px system-ui;max-width:1100px;margin:30px auto}audio{width:100%}p{line-height:1.8}section{padding:20px;background:#f3f5f8;margin:16px 0}</style><h1>系统声音：原版 / GTCRN＋弱语音增益</h1><p>同一次 WASAPI 采集；增强实时处理，识别为采集结束后依次执行，不是双路实时字幕测试。无人工真值，词数不代表准确率。</p>']
    for name in ('raw','enhanced'):
        parts.append(f'<section><h2>{name} — {report["asr"][name]["words"]} words</h2><audio controls src="{name}.wav"></audio><p>{html.escape(report["asr"][name]["text"])}</p></section>')
    parts.append('<h2>仅 GTCRN（用于听辨增益差异）</h2><audio controls src="gtcrn.wav"></audio>')
    (out/'compare.html').write_text('\n'.join(parts),encoding='utf-8')
    print('DONE',out,flush=True)


if __name__=='__main__':main()
