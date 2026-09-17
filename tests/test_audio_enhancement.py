import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from audio_enhancement import ClassroomEnhancer


class EnhancementTest(unittest.TestCase):
    def test_quiet_voice_boost_and_sparse_impact(self):
        rate = 16000
        samples = (.01 * np.sin(2 * np.pi * 220 * np.arange(rate * 5) / rate)).astype(np.float32)
        samples[rate * 4] = .8
        original = samples.copy()
        processor = ClassroomEnhancer(rate)
        enhanced = processor.process(samples)
        self.assertEqual(len(enhanced), len(samples))
        np.testing.assert_array_equal(samples, original)
        self.assertGreater(np.std(enhanced[-rate:]), np.std(original[-rate:] - np.where(np.arange(rate) == 0, .8, 0)) * 2)
        self.assertLess(abs(enhanced[rate * 4]), .4)
        self.assertGreater(processor.limited_windows, 0)

    def test_silence_does_not_raise_gain(self):
        p = ClassroomEnhancer(16000)
        out = p.process(np.zeros(16000, dtype=np.float32))
        self.assertFalse(out.any())
        self.assertEqual(p.gain, 1)

    def test_ordinary_soft_onset_not_classified_as_impact(self):
        p = ClassroomEnhancer(16000)
        x = (.04 * np.sin(2 * np.pi * 180 * np.arange(16000) / 16000)).astype(np.float32)
        p.process(x)
        self.assertEqual(p.limited_windows, 0)

    def test_broad_short_impact_and_output_limit(self):
        p = ClassroomEnhancer(48000)
        x = np.zeros(48000, dtype=np.float32)
        x[12000:13440] = .9
        out = p.process(x)
        self.assertLess(np.max(np.abs(out)), .2)
        self.assertTrue(np.isfinite(out).all())
        with self.assertRaises(ValueError):
            p.process(np.array([np.nan], dtype=np.float32))


if __name__ == '__main__':
    unittest.main()
