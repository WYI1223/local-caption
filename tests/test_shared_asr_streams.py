"""Real C ABI: reset decoder between raw/modified clips while keeping model weights."""
from pathlib import Path
import sys
import time
import wave
import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'app'))
from asr_stream import StreamRecognizer
from audio_enhancement import ClassroomEnhancer

with wave.open(str(BASE / 'samples/jfk.wav')) as f:
    rate = f.getframerate()
    assert f.getnchannels() == 1 and f.getsampwidth() == 2
    source = np.frombuffer(f.readframes(f.getnframes()), dtype='<i2').astype(np.float32) / 32768
# Controlled weak voice plus an artificial collision; not a real classroom accuracy benchmark.
quiet = source * .08
quiet[rate * 4:rate * 4 + 3] = .85
enhancer = ClassroomEnhancer(rate)
began = time.perf_counter()
enhanced = enhancer.process(quiet)
processing_seconds = time.perf_counter() - began
owner = StreamRecognizer()
texts = ['', '']
try:
    for i, audio in enumerate((quiet, enhanced)):
        if i:
            owner.reset_stream()
        for start in range(0, len(source), rate // 10):
            owner.push(audio[start:start + rate // 10], rate)
            for result in owner.results():
                texts[i] = result['text']
        for result in owner.finish():
            texts[i] = result['text']
    assert all('country' in t.lower() for t in texts), texts
    import json
    report = dict(raw=texts[0], enhanced=texts[1], audio_seconds=len(source) / rate,
                  dsp_seconds=processing_seconds, metrics=enhancer.metrics())
    (BASE / 'diagnostics').mkdir(exist_ok=True)
    (BASE / 'diagnostics/enhancement-fixture.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)
finally:
    owner.close()
