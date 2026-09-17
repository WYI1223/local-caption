"""Experimental file-based denoising comparison, not a live capture benchmark."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
import wave

import numpy as np

BASE = Path(__file__).resolve().parents[1]
FILTERS = {
    'raw': None,
    'nonlocal': 'anlmdn=s=0.001:p=0.002:r=0.006',
    'wavelet': 'afwtdn=sigma=0.003:percent=40:samples=512:levels=6',
    'declick': 'adeclick=t=4:w=30',
}


def read(path):
    with wave.open(str(path)) as f:
        if (f.getnchannels(), f.getsampwidth(), f.getframerate()) != (1, 2, 16000):
            raise ValueError('Inputs must be mono PCM16 16 kHz WAV')
        return np.frombuffer(f.readframes(f.getnframes()), '<i2').astype(np.float64) / 32768


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, action='append', required=True)
    parser.add_argument('--rnn-model', type=Path, help='Optional local FFmpeg arnndn model; not downloaded automatically')
    parser.add_argument('--methods', nargs='+', help='Select named methods instead of all')
    args = parser.parse_args()
    args.input = [path.resolve() for path in args.input]
    if args.rnn_model:
        args.rnn_model = args.rnn_model.resolve()
    out = BASE / 'diagnostics' / ('denoise-methods-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True, exist_ok=False)
    filters = dict(FILTERS)
    if args.rnn_model:
        shutil.copyfile(args.rnn_model, out / 'model.rnnn')
        model = (out / 'model.rnnn').relative_to(BASE).as_posix()
        filters['rnn_half'] = f'aresample=48000,arnndn=m={model}:mix=0.5,aresample=16000'
        filters['rnn_full'] = f'aresample=48000,arnndn=m={model}:mix=1,aresample=16000'
    if args.methods:
        if any(name not in filters for name in args.methods):
            parser.error('Unknown method or missing --rnn-model')
        filters = {name:filters[name] for name in args.methods}
    report = {'ground_truth': None, 'stream_context': 1, 'results': [],
              'timing_scope': 'file processing incl process startup; ASR includes model loading; not live latency'}
    if args.rnn_model:
        report['rnn_model_sha256'] = hashlib.sha256(args.rnn_model.read_bytes()).hexdigest()
    print(out, flush=True)
    for index, source in enumerate(args.input):
        raw = read(source)
        if not len(raw):
            raise ValueError('Empty audio')
        for name, spec in filters.items():
            if name.startswith('rnn_'):
                # arnndn rounds the tail to a complete frame; remove padding only.
                spec += f',atrim=end_sample={len(raw)}'
            stem = f'{index}-{source.stem}-{name}'
            audio = out / (stem + '.wav')
            began = time.perf_counter()
            if spec:
                subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-af', spec,
                                '-c:a', 'pcm_s16le', str(audio)], cwd=BASE, check=True, timeout=120)
            else:
                shutil.copyfile(source, audio)
            dsp_time = time.perf_counter() - began
            processed = read(audio)
            if len(processed) != len(raw) or not np.isfinite(processed).all():
                raise ValueError('Invalid filtered audio or changed sample count')
            text = out / (stem + '.txt')
            began = time.perf_counter()
            with (out / (stem + '.log')).open('wb') as log:
                run = subprocess.run([str(BASE / 'runtime/bin/nemo-speech.exe'), 'transcribe',
                    str(audio), '--model', str(BASE / 'models/nemotron-speech-streaming-en-0.6b.q8_0.gguf'),
                    '--device', 'cpu', '--stream', '--asr.streaming.rnnt_right_context', '1',
                    '-o', str(text)], stdout=log, stderr=subprocess.STDOUT, timeout=180)
            row = {'source': str(source.resolve()), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                   'variant': name, 'filter': spec, 'seconds': len(raw)/16000,
                   'preprocess_seconds': dsp_time, 'preprocess_rtf': dsp_time/(len(raw)/16000),
                   'asr_wall_seconds': time.perf_counter()-began, 'exit_code': run.returncode,
                   'rms_ratio': float(np.sqrt(np.mean(processed**2)/max(1e-20, np.mean(raw**2)))),
                   'peak_ratio': float(np.max(np.abs(processed))/max(1e-10,np.max(np.abs(raw)))),
                   'difference_rms': float(np.sqrt(np.mean((processed-raw)**2))),
                   'difference_note': 'Unaligned waveform difference, not a noise removal or quality score',
                   'text': text.read_text(encoding='utf-8').strip() if text.exists() else ''}
            report['results'].append(row)
            (out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({k:row[k] for k in ('variant','seconds','preprocess_rtf','asr_wall_seconds','exit_code')}), flush=True)
            if run.returncode:
                raise RuntimeError(f'ASR failed: {stem}')


if __name__ == '__main__':
    main()
