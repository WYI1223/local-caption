"""Bounded, local-only capture telemetry independent of stdout and Tk."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import queue
import threading
import time


class AudioQueue(queue.Queue):
    """Measure actual queued samples; result emission is not processing progress."""
    def __init__(self, rate, maxsize=120):
        super().__init__(maxsize)
        self.rate = rate
        self.frames = 0
        self.high_frames = 0
        self.overflows = 0

    def _put(self, item):
        super()._put((time.monotonic(), item))
        self.frames += len(item)
        self.high_frames = max(self.high_frames, self.frames)

    def _get(self):
        _, item = super()._get()
        self.frames -= len(item)
        return item

    def put_nowait(self, item):
        try:
            super().put_nowait(item)
        except queue.Full:
            with self.mutex:
                self.overflows += 1
            raise

    def snapshot(self):
        with self.mutex:
            return dict(queued_blocks=self._qsize(), queue_seconds=self.frames / self.rate,
                        queue_high_seconds=self.high_frames / self.rate,
                        oldest_queue_age_seconds=time.monotonic() - self.queue[0][0] if self.queue else 0,
                        overflow_count=self.overflows)


class CaptureDiagnostics:
    def __init__(self, path, metadata=None, interval=1., max_bytes=20 * 1024 * 1024):
        self.path = Path(path)
        self.interval, self.max_bytes = interval, max_bytes
        self.lock = threading.Lock()
        self.stages, self.totals, self.values = {}, {}, {}
        self.queue = None
        self.started = time.monotonic()
        self.closed = threading.Event()
        self.write_error = None
        self.metadata = dict(schema=1, pid=os.getpid(), **(metadata or {}))
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def update(self, **values):
        with self.lock:
            self.values.update(values)

    @contextmanager
    def stage(self, name):
        key = threading.get_ident()
        started = time.monotonic()
        with self.lock:
            old = self.stages.get(key)
            self.stages[key] = (name, started)
        try:
            yield
        finally:
            duration = time.monotonic() - started
            with self.lock:
                stat = self.totals.setdefault(name, dict(calls=0, seconds=0., max_seconds=0.))
                stat['calls'] += 1
                stat['seconds'] += duration
                stat['max_seconds'] = max(stat['max_seconds'], duration)
                if old is None:
                    self.stages.pop(key, None)
                else:
                    self.stages[key] = old

    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            result = dict(self.metadata, wall_time=time.time(), monotonic=now,
                          elapsed=now-self.started, process_cpu_seconds=time.process_time(),
                          active=[dict(stage=n, seconds=now-t) for n,t in self.stages.values()],
                          timings={k:dict(v) for k,v in self.totals.items()}, **self.values)
        if self.queue is not None:
            result.update(self.queue.snapshot())
        return result

    def _run(self):
        # One writer; even a stalled native call or stdout pipe leaves a heartbeat.
        try:
            import psutil
            process = psutil.Process()
            psutil.cpu_percent()
        except ImportError:
            process = None
        while True:
            row = self.snapshot()
            row['resources_available'] = process is not None
            if process is not None:
                try:
                    mem = process.memory_info()
                    row['resources'] = dict(system_cpu_percent=psutil.cpu_percent(),
                        available_ram_bytes=psutil.virtual_memory().available,
                        process_cpu_percent=process.cpu_percent(), rss_bytes=mem.rss,
                        private_bytes=getattr(mem, 'private', None),
                        page_faults=getattr(mem, 'num_page_faults', None))
                except psutil.Error:
                    row['resource_error'] = True
            row['closed'] = self.closed.is_set()
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                    self.path.replace(self.path.with_suffix('.previous.jsonl'))
                with self.path.open('a', encoding='utf-8') as f:
                    f.write(json.dumps(row, ensure_ascii=True) + '\n')
            except OSError as exc:
                # Diagnostics failure must not stop audio; expose it to the caller.
                self.write_error = type(exc).__name__
            if row['closed']:
                return
            self.closed.wait(self.interval)

    def close(self):
        self.closed.set()
        self.thread.join(timeout=2)


def source_fingerprint():
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for name in ('loopback_worker.py', 'asr_stream.py', 'gtcrn_mix.py', 'capture_diagnostics.py', 'audio_devices.py'):
        digest.update((root/name).read_bytes())
    return digest.hexdigest()[:16]
