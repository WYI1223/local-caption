"""Experimental stateful GTCRN mixing frontend; no automatic gain control."""
from pathlib import Path
import numpy as np


class GTCRNMix:
    output_rate = 16000

    def __init__(self, rate, amount):
        import sherpa_onnx as sh
        from scipy.signal import firwin
        if rate not in (16000, 48000):
            raise ValueError('GTCRN 试用目前支持 16/48 kHz 设备，请将系统声音格式设为 48 kHz。')
        if amount not in (.25, .5):
            raise ValueError('GTCRN mix must be 25% or 50%')
        self.rate, self.amount = rate, amount
        path=Path(__file__).resolve().parents[1]/'models/enhancement/gtcrn_simple.onnx'
        config=sh.OfflineSpeechDenoiserModelConfig(num_threads=1,
            gtcrn=sh.OfflineSpeechDenoiserGtcrnModelConfig(model=str(path)))
        self.model=sh.OnlineSpeechDenoiser(sh.OnlineSpeechDenoiserConfig(model=config))
        self.b=firwin(97,7200,fs=48000) if rate==48000 else None
        self.zi=np.zeros(96);self.input_count=0
        self.pending=np.empty(0,np.float32)
        self.output_count=0;self.finished=False

    def _mix(self, clean):
        clean=np.asarray(clean,np.float32)
        if len(clean)>len(self.pending):
            raise RuntimeError('GTCRN 输出超过原音缓冲，停止以避免错位。')
        out=((1-self.amount)*self.pending[:len(clean)]+self.amount*clean).astype(np.float32)
        self.pending=self.pending[len(clean):];self.output_count+=len(out)
        return out

    def process(self, x):
        from scipy.signal import lfilter
        if self.finished:raise RuntimeError('Frontend already finished')
        x=np.asarray(x,np.float32)
        if x.ndim!=1 or not np.isfinite(x).all():raise ValueError('Invalid mono audio')
        if not len(x):return x
        if self.b is not None:
            filtered,self.zi=lfilter(self.b,[1.],x,zi=self.zi)
            common=filtered[(-self.input_count)%3::3].astype(np.float32)
        else:common=x
        self.input_count+=len(x)
        self.pending=np.concatenate((self.pending,common))
        return self._mix(self.model.run(common,16000).samples) if len(common) else common

    def finish(self):
        if self.finished:return np.empty(0,np.float32)
        self.finished=True
        tail=self._mix(self.model.flush().samples)
        if len(self.pending):raise RuntimeError('GTCRN 收尾后仍有未处理原音，末尾可能不完整。')
        return tail

    def metrics(self):
        return dict(mode=f'gtcrn{int(self.amount*100)}',mix_percent=int(self.amount*100),
                    gain_db=0.,limited_windows=0,output_seconds=self.output_count/16000,
                    buffered_samples=len(self.pending))
