"""After recording ends: compare one local excerpt, one ASR model at a time (Windows)."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import wave
import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'app'))
from audio_enhancement import ClassroomEnhancer
from platform_support import available_commit_gib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', type=Path)
    parser.add_argument('--start', type=float, default=0)
    parser.add_argument('--seconds', type=float, default=30)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('This ASR comparison currently requires Windows.')
    if not args.audio.is_file() or args.start < 0 or not 0 < args.seconds <= 120:
        parser.error('Use an existing audio file, nonnegative start, and 0 < seconds <= 120.')
    available = available_commit_gib()
    if available is not None and available < 5:
        parser.error(f'Available commit memory is {available:.1f} GiB; stop other ASR captures first (conservative threshold: 5 GiB).')
    if not shutil.which('ffmpeg'):
        parser.error('ffmpeg is required to decode the recording; install it and add it to PATH.')
    output = BASE / 'diagnostics' / ('enhancement-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    output.mkdir(parents=True)
    raw_path = output / 'raw.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(args.start), '-i', str(args.audio.resolve()),
                    '-t', str(args.seconds), '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(raw_path)], check=True)
    with wave.open(str(raw_path), 'rb') as f:
        rate = f.getframerate()
        raw = np.frombuffer(f.readframes(f.getnframes()), dtype='<i2').astype(np.float32) / 32768
    if not len(raw):
        raise ValueError('Selected excerpt contains no audio frames')
    enhancer = ClassroomEnhancer(rate)
    started = time.perf_counter()
    enhanced = enhancer.process(raw)
    result = dict(audio_seconds=len(raw) / rate, start_seconds=args.start,
                  dsp_seconds=time.perf_counter() - started, enhancement=enhancer.metrics(), results=[])
    with wave.open(str(output / 'enhanced.wav'), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes((enhanced * 32767).astype('<i2').tobytes())
    # Keep native logs out of the console; diagnostic files never enter source packages.
    with (output / 'engine.log').open('w') as log:
        os.dup2(log.fileno(), 2)
        from asr_stream import StreamRecognizer
        recognizer = StreamRecognizer()
        try:
            for index, (label, samples) in enumerate((('raw', raw), ('enhanced', enhanced))):
                if index:
                    recognizer.reset_stream()
                started = time.perf_counter()
                text = ''
                for start in range(0, len(samples), rate // 10):
                    recognizer.push(samples[start:start + rate // 10], rate)
                    for row in recognizer.results():
                        text = row['text']
                for row in recognizer.finish():
                    text = row['text']
                result['results'].append(dict(variant=label, text=text, asr_seconds=time.perf_counter() - started))
                (output / 'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        finally:
            recognizer.close()
    print(output)


if __name__ == '__main__':
    main()
