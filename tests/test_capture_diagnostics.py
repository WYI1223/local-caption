import json
from pathlib import Path
import queue
import sys
import tempfile
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from capture_diagnostics import AudioQueue, CaptureDiagnostics

class CaptureTest(unittest.TestCase):
    def test_overflow_is_sample_queue_not_result_cursor(self):
        q=AudioQueue(16000,maxsize=2)
        q.put_nowait([0]*1600);q.put_nowait([0]*800)
        self.assertAlmostEqual(q.snapshot()['queue_seconds'],.15)
        with self.assertRaises(queue.Full):q.put_nowait([0]*1600)
        self.assertEqual(q.snapshot()['overflow_count'],1)
        q.get();q.get()
        self.assertEqual(q.snapshot()['queue_seconds'],0)
        self.assertAlmostEqual(q.snapshot()['queue_high_seconds'],.15)
        # Empty results from the recognizer must not create a capture backlog.
        with tempfile.TemporaryDirectory() as d:
            p=CaptureDiagnostics(Path(d)/'probe.jsonl',interval=.01)
            p.queue=q;p.update(submitted_seconds=40,result_processed_seconds=0)
            self.assertEqual(p.snapshot()['queue_seconds'],0)
            p.close()

    def test_heartbeat_survives_blocked_processing_and_rotates(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'probe.jsonl'
            p=CaptureDiagnostics(path,interval=.02,max_bytes=2500)
            with p.stage('asr_push'):
                with p.stage('stdout'):
                    time.sleep(.2)
                self.assertEqual(p.snapshot()['active'][0]['stage'],'asr_push')
            p.close()
            rows=[]
            for f in Path(d).glob('*.jsonl'):
                rows.extend(json.loads(l) for l in f.read_text().splitlines())
            self.assertTrue(any(any(s['stage']=='stdout' for s in r['active']) for r in rows))
            self.assertTrue(any(r['closed'] for r in rows))
            self.assertEqual(p.snapshot()['timings']['asr_push']['calls'],1)
            self.assertLessEqual(len(list(Path(d).glob('*.jsonl'))),2)
            self.assertFalse(p.thread.is_alive())

if __name__=='__main__':unittest.main()
