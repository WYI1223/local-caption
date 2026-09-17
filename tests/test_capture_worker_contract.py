"""Real worker CLI/callback/queue/archive; controlled audio and ASR boundaries, no playback."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import wave
BASE=Path(__file__).resolve().parents[1]

def child():
    import numpy as np
    sys.path.insert(0,str(BASE/'app'))
    count=int(sys.argv[2]);out=Path(sys.argv[3])
    class Recognizer:
        def __init__(self):self.samples=0
        def push(self,x,rate):self.samples+=len(x)
        def results(self):return [] # Reproduce delayed result cursor without queued input.
        def finish(self):return [dict(text='Controlled sentence.',processed=self.samples/16000,final=True)]
        def close(self):pass
    class Stream:
        def __init__(self,callback):self.callback=callback
        def start_stream(self):
            for _ in range(count):
                _,status=self.callback(np.zeros(1600,np.float32).tobytes(),1600,{},0)
                if status:break
        def is_active(self):return True
        def stop_stream(self):pass
        def close(self):pass
    class Audio:
        def get_default_input_device_info(self):return dict(defaultSampleRate=16000,maxInputChannels=1,index=0,name='Controlled input')
        def open(self,**kw):return Stream(kw['stream_callback'])
        def terminate(self):pass
    sys.modules['asr_stream']=types.SimpleNamespace(StreamRecognizer=Recognizer)
    sys.modules['pyaudiowpatch']=types.SimpleNamespace(PyAudio=Audio,paFloat32=1,paContinue=0,paComplete=1)
    import loopback_worker
    sys.argv=['loopback_worker','--source','microphone','--duration',str(count/10),
              '--record-audio',str(out/'audio.wav'),'--diagnostics',str(out/'capture.jsonl')]
    raise SystemExit(loopback_worker.main())

if __name__=='__main__':
    if '--child' in sys.argv:child()
    else:
        for count in (3,121):
            with tempfile.TemporaryDirectory() as d:
                p=subprocess.Popen([sys.executable,__file__,'--child',str(count),d],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                # Keep stdin open, as the actual GUI does; closing stdin requests stop.
                try:
                    p.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    p.kill();p.communicate()
                    raise
                stdout=p.stdout.read();stderr=p.stderr.read();p.stdin.close()
                assert p.returncode==(0 if count==3 else 1),(p.returncode,stderr)
                events=[json.loads(l) for l in stdout.splitlines()]
                metrics=[r['audio_metrics'] for r in events if 'audio_metrics' in r]
                assert metrics[-1]['queue_seconds']==0,metrics[-1]
                assert metrics[-1]['overflow_count']==(0 if count==3 else 1)
                assert abs(metrics[-1]['submitted_seconds']-min(count,120)/10)<1e-6
                rows=[json.loads(l) for l in (Path(d)/'capture.jsonl').read_text().splitlines()]
                assert rows[-1]['closed'] and rows[-1]['exit_code']==p.returncode
                assert rows[-1]['timings']['asr_push']['calls']==min(count,120)
                if count==121:assert rows[-1]['queue_high_seconds']==12
                with wave.open(str(Path(d)/'audio.wav')) as w:assert w.getnframes()==count*1600
                print('PASS worker lifecycle, delayed result cursor, archive and overflow:',count)
