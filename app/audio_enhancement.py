"""Conservative causal level control and sparse impulse limiting for mono float32."""
import math
import numpy as np


class ClassroomEnhancer:
    def __init__(self, sample_rate):
        if not 8000 <= sample_rate <= 96000:
            raise ValueError('Sample rate must be between 8 and 96 kHz')
        self.rate = sample_rate
        self.gain = 1.0
        self.reference = .01
        self.limited_windows = 0
        self.processed_samples = 0
        self.input_energy = self.output_energy = 0.0
        self.hot_windows = 0

    def process(self, samples):
        x = np.asarray(samples, dtype=np.float32)
        if x.ndim != 1 or not np.isfinite(x).all():
            raise ValueError('Audio must be finite mono float32 samples')
        out = np.empty_like(x)
        for start in range(0, len(x), max(1, self.rate // 100)):
            frame = x[start:start + self.rate // 100]
            duration = len(frame) / self.rate
            rms = float(np.sqrt(np.mean(frame * frame)))
            peak = float(np.max(np.abs(frame)))
            # Only very sparse, large peaks qualify; ordinary syllable onsets do not.
            sparse = peak > max(.12, self.reference * 12) and peak > max(1e-6, rms) * 5
            abrupt = peak > .55 and rms > max(.1, self.reference * 10)
            self.hot_windows = self.hot_windows + 1 if abrupt else 0
            impulse = sparse or (abrupt and self.hot_windows <= 8)
            clean = frame
            if impulse:
                ceiling = max(.04, min(.25, self.reference * 6))
                clean = np.clip(frame, -ceiling, ceiling)
                self.limited_windows += 1
            level = float(np.sqrt(np.mean(clean * clean)))
            # A level gate is not a speech detector. Below -50 dBFS, do not boost.
            desired = min(4.0, .063 / max(level, 1e-6)) if level >= .0032 else 1.0
            # Do not let a knock drive the gain controller, including its recovery.
            if impulse:
                desired = self.gain
            tau = 1.5 if desired > self.gain else .2
            new_gain = self.gain + (desired - self.gain) * (1 - math.exp(-duration / tau))
            ramp = np.linspace(self.gain, new_gain, len(frame), dtype=np.float32)
            out[start:start + len(frame)] = np.clip(clean * ramp, -.85, .85)
            self.gain = new_gain
            if not impulse:
                self.reference += (rms - self.reference) * (1 - math.exp(-duration / .5))
        self.processed_samples += len(x)
        self.input_energy += float(np.dot(x, x))
        self.output_energy += float(np.dot(out, out))
        return out

    def metrics(self):
        n = max(1, self.processed_samples)
        return dict(gain_db=20 * math.log10(max(self.gain, 1e-9)), limited_windows=self.limited_windows,
                    input_rms=math.sqrt(self.input_energy / n), output_rms=math.sqrt(self.output_energy / n))
