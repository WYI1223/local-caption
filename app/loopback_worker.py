"""Capture default Windows output using WASAPI; stream locally into NeMo ASR."""
import json
import ctypes
from ctypes import wintypes
import msvcrt
import os
from pathlib import Path
import queue
import sys
import threading
import time
import argparse
from capture_diagnostics import AudioQueue, CaptureDiagnostics, source_fingerprint

BASE = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', choices=['system', 'microphone'], default='system')
    parser.add_argument('--diagnostics', type=Path, help='Local capture heartbeat JSONL (no audio or transcript)')
    parser.add_argument('--enhance', action='store_true')
    parser.add_argument('--gtcrn-mix', type=int, choices=[25,50])
    parser.add_argument('--record-audio', type=Path, help='Save unenhanced device audio as PCM16 WAV')
    parser.add_argument('--compare', action='store_true', help='Capture once, then decode raw/enhanced sequentially with one model')
    parser.add_argument('--duration', type=float, default=0, help='Automatic stop after captured seconds; zero is unlimited')
    args = parser.parse_args()
    if args.gtcrn_mix and (args.enhance or args.compare):
        parser.error('GTCRN mixing cannot be combined with legacy enhancement/comparison')
    if args.compare and not args.duration:
        args.duration = 30
    sys.stdout.reconfigure(encoding='utf-8')
    diagnostic_path = args.diagnostics or BASE / 'diagnostics' / f'capture-{os.getpid()}-{time.time_ns()}.jsonl'
    probe = CaptureDiagnostics(diagnostic_path, dict(source=args.source, mix=args.gtcrn_mix, build=source_fingerprint()))
    lock = threading.Lock()
    def emit(event):
        with probe.stage('stdout'):
            with lock:
                event['worker_monotonic'] = time.monotonic()
                print(json.dumps(event, ensure_ascii=True), flush=True)
    stop = threading.Event()
    ready = threading.Event()
    def listen():
        # A blocking CRT stdin read can deadlock NumPy's native-module import
        # on Windows. Poll the pipe without holding its CRT descriptor lock.
        peek = ctypes.WinDLL('kernel32', use_last_error=True).PeekNamedPipe
        peek.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                         ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        available = wintypes.DWORD()
        while peek(handle, None, 0, None, ctypes.byref(available), None) and not available.value:
            if stop.wait(0.05):
                return
        stop.set()
        if not ready.is_set():
            emit({'exit': 0, 'cancelled': True})
            probe.update(exit_code=0, cancelled_during_load=True)
            probe.close()
            os._exit(0)  # Cancels native model loading before capture starts.
    threading.Thread(target=listen, daemon=True).start()
    # Native DLL diagnostics must not fill the GUI's stderr pipe or enter subtitles.
    log_path = BASE / 'diagnostics' / f'loopback-{os.getpid()}.log'
    log_path.parent.mkdir(exist_ok=True)
    log = log_path.open('w', encoding='utf-8')
    os.dup2(log.fileno(), 2)
    recognizer = None
    capture = None
    audio = None
    archive = None
    code = 0
    try:
        import numpy as np
        import pyaudiowpatch as pa
        from asr_stream import StreamRecognizer
        audio = pa.PyAudio()
        device = audio.get_default_wasapi_loopback() if args.source == 'system' else audio.get_default_input_device_info()
        rate, channels = int(device['defaultSampleRate']), int(device['maxInputChannels'])
        if not channels:
            raise RuntimeError('默认音频设备不支持输入采集。')
        if args.compare:
            from platform_support import available_commit_gib
            available = available_commit_gib()
            if available is not None and available < 5:
                raise RuntimeError(f'A/B 对比需要额外识别工作区；当前可提交内存仅 {available:.1f} GiB（保守要求5 GiB）。请先停止其他字幕采集再试。')
        else:
            with probe.stage('model_load'):
                recognizer = StreamRecognizer()
        from audio_enhancement import ClassroomEnhancer
        enhancer = ClassroomEnhancer(rate) if args.enhance or args.compare else None
        output_rate = rate
        if args.gtcrn_mix:
            from gtcrn_mix import GTCRNMix
            enhancer = GTCRNMix(rate,args.gtcrn_mix/100)
            output_rate = enhancer.output_rate
        blocks = AudioQueue(rate, maxsize=120)  # 12 seconds, then stop explicitly; never silently drop.
        probe.queue = blocks
        probe.update(rate=rate, channels=channels)
        fault = []
        captured = 0
        peak = 0.0
        processed = 0.0
        dequeued_frames = 0
        submitted_seconds = 0.0
        callback_count = 0
        raw_processed = 0.0
        enhancement_seconds = 0.0
        comparison_audio = []
        phase = 'capture'
        started = time.monotonic()
        def callback(data, frame_count, timing, status):
            nonlocal captured, peak, callback_count
            callback_count += 1
            probe.update(callback_count=callback_count, last_callback_monotonic=time.monotonic(), callback_frames=frame_count, callback_status=status)
            if stop.is_set():
                return (None, pa.paComplete)
            if status:
                probe.update(fault='device_status')
                fault.append(f'系统音频采集发生溢出或设备错误（{status}），请停止其他高负载任务后重试。')
                stop.set()
                return (None, pa.paComplete)
            if archive:
                recorded_data = data
                if args.duration:
                    recorded_data = data[:max(0, int(args.duration * rate) - captured) * channels * 4]
                try:
                    archive.submit(recorded_data)
                except Exception as exc:
                    probe.update(fault='audio_archive_submit')
                    fault.append(str(exc))
                    stop.set()
                    return (None, pa.paComplete)
            samples = np.frombuffer(data, dtype=np.float32).reshape(-1, channels).mean(axis=1).astype(np.float32)
            if args.duration:
                samples = samples[:max(0, int(args.duration * rate) - captured)]
            peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
            try:
                blocks.put_nowait(samples)
                captured += len(samples)
                probe.update(captured_seconds=captured/rate)
            except queue.Full:
                probe.update(fault='capture_queue_full', rejected_frames=len(samples))
                fault.append('音频待识别超过 12 秒，已停止采集以避免继续积压；末尾可能不完整。')
                stop.set()
                return (None, pa.paComplete)
            if args.duration and captured >= int(args.duration * rate):
                stop.set()
                return (None, pa.paComplete)
            return (None, pa.paContinue)
        capture = audio.open(format=pa.paFloat32, channels=channels, rate=rate,
            input=True, input_device_index=device['index'], frames_per_buffer=rate // 10,
            stream_callback=callback, start=False)
        ready.set()
        if stop.is_set():
            return
        if args.record_audio:
            from audio_archive import AudioArchive
            archive = AudioArchive(args.record_audio, rate, channels)
            emit({'audio_recording': {'path': str(archive.partial_path), 'complete': False}})
        capture.start_stream()
        emit({'line': '[live] listening ' + args.source})
        emit({'capture_device': device['name']})
        emit({'enhancement': {'enabled': bool(enhancer), 'comparison': args.compare,
                             'gtcrn_mix': args.gtcrn_mix}})
        last_metrics = 0
        previous = ''
        def publish(results):
            nonlocal processed, previous
            for result in results:
                processed = max(processed, result['processed'])
                probe.update(result_processed_seconds=processed, last_result_monotonic=time.monotonic())
                text = result['text']
                if text != previous or result['final']:
                    elapsed = max(0.0, time.monotonic() - started - max(0, captured / rate - processed))
                    emit({'line': f"[live {'final' if result['final'] else 'partial'} @ {elapsed:.2f}s] {text}"})
                    previous = text
        def metrics(force=False):
            nonlocal last_metrics
            now = time.monotonic()
            if force or now - last_metrics >= 0.5:
                queue_state = blocks.snapshot()
                probe.update(dequeued_seconds=dequeued_frames/rate, submitted_seconds=submitted_seconds, result_processed_seconds=processed, phase=phase)
                emit({'audio_metrics': dict(elapsed=now - started, captured_seconds=captured / rate,
                    processed_seconds=processed, backlog_seconds=max(0, captured / rate - min(processed, raw_processed) if args.compare else captured / rate - processed),
                    queued_blocks=queue_state['queued_blocks'], queue_seconds=queue_state['queue_seconds'],
                    queue_high_seconds=queue_state['queue_high_seconds'], overflow_count=queue_state['overflow_count'],
                    submitted_seconds=submitted_seconds, result_lag_seconds=max(0, submitted_seconds-processed),
                    diagnostic_error=probe.write_error, level=peak, stopped=stop.is_set(),
                    enhancement=enhancer.metrics() if enhancer else None, enhancement_seconds=enhancement_seconds,
                    phase=phase)})
                last_metrics = now
        while not stop.is_set() or not blocks.empty():
            try:
                samples = blocks.get(timeout=0.1)
            except queue.Empty:
                if not capture.is_active() and not stop.is_set():
                    raise RuntimeError('系统声音设备已停止或断开，请重新选择默认播放设备后重试。')
                metrics()
                continue
            dequeued_frames += len(samples)
            probe.update(dequeued_seconds=dequeued_frames/rate, in_flight_seconds=len(samples)/rate)
            before = time.perf_counter()
            with probe.stage('enhancement'):
                enhanced = enhancer.process(samples) if enhancer else samples
            enhancement_seconds += time.perf_counter() - before
            if args.compare:
                comparison_audio.append((samples, enhanced))
            else:
                if len(enhanced):
                    with probe.stage('asr_push'):
                        recognizer.push(enhanced, output_rate)
                    submitted_seconds += len(enhanced)/output_rate
                    probe.update(submitted_seconds=submitted_seconds)
                with probe.stage('asr_results_and_publish'):
                    publish(recognizer.results())
            probe.update(in_flight_seconds=0)
            metrics()
        capture.stop_stream()
        if args.gtcrn_mix:
            with probe.stage('enhancement_flush'):
                tail=enhancer.finish()
            if len(tail):
                with probe.stage('asr_push'):
                    recognizer.push(tail,output_rate)
                submitted_seconds += len(tail)/output_rate
            publish(recognizer.results())
        if args.compare:
            phase = 'raw'
            metrics(True)
            # One model and one decoder state at a time; no extra translation model.
            recognizer = StreamRecognizer()
            for samples, enhanced in comparison_audio:
                recognizer.push(samples, rate)
                for result in recognizer.results():
                    raw_processed = max(raw_processed, result['processed'])
                    emit({'comparison_raw': result['text']})
                metrics()
            for result in recognizer.finish():
                raw_processed = max(raw_processed, result['processed'])
                emit({'comparison_raw': result['text']})
            recognizer.reset_stream()
            phase = 'enhanced'
            for samples, enhanced in comparison_audio:
                recognizer.push(enhanced, rate)
                publish(recognizer.results())
                metrics()
        with probe.stage('asr_finish'):
            publish(recognizer.finish())
        phase = 'finished'
        metrics(True)
        if fault:
            raise RuntimeError(fault[0])
    except Exception as exc:
        code = 1
        probe.update(fault=fault[0] if 'fault' in locals() and fault else type(exc).__name__)
        emit({'line': '[error] 音频采集：' + str(exc)})
    finally:
        stop.set()
        if capture:
            capture.close()
        if audio:
            audio.terminate()
        if archive:
            try:
                path = archive.close()
                emit({'audio_recording': {'path': str(path), 'complete': True,
                      'frames': archive.frames, 'rate': rate, 'channels': channels}})
            except Exception as exc:
                code = 1
                emit({'line': '[error] ' + str(exc)})
        if recognizer:
            recognizer.close()
        probe.update(exit_code=code)
        emit({'exit': code, 'cancelled': code == 0})
        probe.close()
    return code


if __name__ == '__main__':
    sys.exit(main())
