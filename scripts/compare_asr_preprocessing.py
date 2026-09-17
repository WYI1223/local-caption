"""Local controlled ASR comparison; private audio/results remain in diagnostics."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import wave
import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'app'))
from audio_enhancement import ClassroomEnhancer


def read_wav(path):
    with wave.open(str(path)) as f:
        return np.frombuffer(f.readframes(f.getnframes()), '<i2').astype(np.float32) / 32768


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--clear', type=Path, required=True)
    p.add_argument('--noisy', type=Path, required=True)
    p.add_argument('--clear-start', type=float, default=600)
    p.add_argument('--noisy-start', type=float, default=1800)
    p.add_argument('--seconds', type=float, default=25)
    p.add_argument('--clips', choices=['both', 'clear', 'noisy'], default='both')
    args = p.parse_args()
    if not 0 < args.seconds <= 120:
        p.error('Use 0 < seconds <= 120')
    output = BASE / 'diagnostics' / ('asr-preprocessing-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    output.mkdir(parents=True)
    report = {'requested_seconds': args.seconds, 'ground_truth': None, 'results': [], 'clips': {}}
    engine = BASE / 'runtime/bin/nemo-speech.exe'
    for label, source, start in [('clear', args.clear, args.clear_start), ('noisy', args.noisy, args.noisy_start)]:
        if args.clips != 'both' and args.clips != label:
            continue
        raw_path = output / f'{label}-raw.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(start), '-i', str(source), '-t', str(args.seconds),
                        '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(raw_path)], check=True)
        raw = read_wav(raw_path)
        enhancer = ClassroomEnhancer(16000)
        began = time.perf_counter()
        levelled = np.concatenate([enhancer.process(raw[i:i+1600]) for i in range(0, len(raw), 1600)])
        dsp_seconds = time.perf_counter() - began
        level_path = output / f'{label}-level.wav'
        with wave.open(str(level_path), 'wb') as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000)
            f.writeframes((np.clip(levelled, -1, 32767/32768)*32768).astype('<i2').tobytes())
        denoise_path = output / f'{label}-denoise.wav'
        filter_spec = 'highpass=f=80,afftdn=nr=6:nf=-40:tn=1'
        began = time.perf_counter()
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(raw_path), '-af', filter_spec,
                        '-c:a', 'pcm_s16le', str(denoise_path)], check=True)
        denoise_seconds = time.perf_counter() - began
        denoised = read_wav(denoise_path)
        assert len(denoised) == len(raw), 'Preprocessing changed duration'
        report['clips'][label] = {'source': str(source), 'start': start, 'samples': len(raw), 'decoded_seconds': len(raw)/16000,
            'input_rms_dbfs': float(20*np.log10(max(1e-9,np.sqrt(np.mean(raw*raw))))),
            'peak': float(np.max(np.abs(raw))), 'level_dsp_seconds': dsp_seconds,
            'level_metrics': enhancer.metrics(), 'denoise_process_seconds': denoise_seconds,
            'denoise_filter': filter_spec}
        variants = [('raw_stream_r1', raw_path, ['--stream','--asr.streaming.rnnt_right_context','1']),
                    ('raw_stream_r13', raw_path, ['--stream','--asr.streaming.rnnt_right_context','13']),
                    ('raw_offline', raw_path, []),
                    ('level_stream_r1', level_path, ['--stream','--asr.streaming.rnnt_right_context','1']),
                    ('denoise_stream_r1', denoise_path, ['--stream','--asr.streaming.rnnt_right_context','1'])]
        for variant, audio, extra in variants:
            stem = label + '-' + variant
            text_path = output / (stem + '.txt')
            began = time.perf_counter()
            with (output / (stem + '.log')).open('wb') as log:
                run = subprocess.run([str(engine), 'transcribe', str(audio), '--model',
                    str(BASE/'models/nemotron-speech-streaming-en-0.6b.q8_0.gguf'), '--device','cpu',
                    '-o',str(text_path), *extra], stdout=log, stderr=subprocess.STDOUT, timeout=180)
            row = {'clip':label,'variant':variant,'wall_seconds':time.perf_counter()-began,'exit_code':run.returncode,
                   'text':text_path.read_text(encoding='utf-8').strip() if text_path.exists() else ''}
            report['results'].append(row)
            (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:v for k,v in row.items() if k!='text'}),flush=True)
            if run.returncode:
                raise RuntimeError('ASR failed; see ' + str(output/(stem+'.log')))
    print(output,flush=True)


if __name__ == '__main__':
    main()
