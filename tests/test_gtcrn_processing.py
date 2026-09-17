"""Real pinned ONNX frontend, synthetic PCM only; no playback or ASR quality claim."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from gtcrn_mix import GTCRNMix

class GTCRNTest(unittest.TestCase):
    def test_chunk_boundaries_and_flush(self):
        x=(.02*np.sin(np.arange(48001)*.041)).astype(np.float32)
        for ratio in (.25,.5):
            whole=GTCRNMix(48000,ratio)
            expected=np.concatenate([whole.process(x),whole.finish()])
            chunks=GTCRNMix(48000,ratio)
            actual=np.concatenate([chunks.process(x[i:i+777]) for i in range(0,len(x),777)]+[chunks.finish()])
            self.assertEqual(len(actual),16001)
            np.testing.assert_allclose(actual,expected,atol=1e-5,rtol=1e-5)
            self.assertEqual(chunks.metrics()['buffered_samples'],0)
            self.assertEqual(len(chunks.finish()),0)
    def test_empty_and_bad_rate(self):
        for ratio in (.25,.5):
            self.assertEqual(len(GTCRNMix(16000,ratio).finish()),0)
        with self.assertRaises(ValueError):GTCRNMix(44100,.25)

if __name__=='__main__':unittest.main()
