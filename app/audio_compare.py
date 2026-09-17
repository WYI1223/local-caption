"""Capture once, decode raw/enhanced sequentially with one model; no translation."""
import argparse
import datetime
import json
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
import tkinter as tk
from tkinter.scrolledtext import ScrolledText
from platform_support import BASE, PYTHON, process_options, kill_tree


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', choices=['microphone', 'system'], default='microphone')
    args = parser.parse_args()
    root = tk.Tk()
    root.title('Local Caption · 原始 / 课堂增强对比')
    root.geometry('800x440')
    root.minsize(500, 280)
    inbox = queue.Queue()
    state = dict(process=None, closing=False, raw='', enhanced='', metrics={}, errors=[], stopping_at=None)
    status = tk.StringVar(value='先采集30秒，再用一份模型依次识别原始/增强音频。两栏对比英文，不额外加载翻译。')
    toolbar = tk.Frame(root)
    toolbar.pack(fill='x')
    panes = tk.Frame(root)
    panes.pack(fill='both', expand=True)
    views = {}
    for name, title in [('raw', '原始音频'), ('enhanced', '课堂增强（实验）')]:
        frame = tk.Frame(panes)
        frame.pack(side='left', fill='both', expand=True)
        tk.Label(frame, text=title).pack()
        views[name] = ScrolledText(frame, wrap='word', width=40, font=('Arial', 12))
        views[name].pack(fill='both', expand=True)
        views[name].configure(state='disabled')
    tk.Label(root, textvariable=status, wraplength=760, justify='left').pack(side='bottom', fill='x', before=panes)

    def save():
        output = state.get('output')
        if output:
            output.parent.mkdir(exist_ok=True)
            output.write_text(json.dumps({k: state[k] for k in ('raw', 'enhanced', 'metrics', 'errors')},
                ensure_ascii=False, indent=2), encoding='utf-8')

    def stop():
        process = state['process']
        if process and process.poll() is None and state['stopping_at'] is None:
            state['stopping_at'] = time.monotonic()
            try:
                process.stdin.write('stop\n')
                process.stdin.flush()
            except (OSError, ValueError):
                pass
            status.set('正在停止并整理两路字幕…')

    def start():
        if state['process']:
            return
        state.update(raw='', enhanced='', metrics={}, errors=[], stopping_at=None)
        state['output'] = BASE / 'transcripts' / ('compare-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
        try:
            p = subprocess.Popen([str(PYTHON), str(BASE / 'app/loopback_worker.py'), '--source', args.source,
                '--compare', '--duration', '30'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding='utf-8', **process_options())
        except OSError as exc:
            status.set(str(exc))
            return
        state['process'] = p
        start_button.configure(state='disabled')
        status.set('检查可用内存并开始30秒采集…')
        def read():
            for line in p.stdout:
                try:
                    inbox.put(json.loads(line))
                except ValueError:
                    continue
            inbox.put({'finished': p.wait()})
        threading.Thread(target=read, daemon=True).start()

    def close():
        state['closing'] = True
        if state['process']:
            stop()
        else:
            root.destroy()

    start_button = tk.Button(toolbar, text='开始30秒对比', command=start)
    start_button.pack(side='left')
    tk.Button(toolbar, text='停止', command=stop).pack(side='left')
    tk.Button(toolbar, text='关闭', command=close).pack(side='right')

    def poll():
        dirty = False
        while not inbox.empty():
            event = inbox.get_nowait()
            if 'comparison_raw' in event:
                state['raw'] = event['comparison_raw']
                dirty = True
            match = re.match(r'\[live (?:partial|final)[^\]]*\]\s*(.*)', event.get('line', ''))
            if match:
                state['enhanced'] = match.group(1)
                dirty = True
            if event.get('line', '').startswith('[error]'):
                state['errors'].append(event['line'])
            if 'audio_metrics' in event:
                m = state['metrics'] = event['audio_metrics']
                phase = {'capture': '采集中', 'raw': '识别原始音频', 'enhanced': '识别增强音频', 'finished': '完成'}.get(m.get('phase'), '')
                status.set(f"{phase} · 音频 {m['captured_seconds']:.1f}/30秒 · "
                           f"增益 {m['enhancement']['gain_db']:+.1f}dB · 峰值抑制窗口 {m['enhancement']['limited_windows']}")
            if 'finished' in event:
                if event['finished'] and not state['errors']:
                    state['errors'].append('识别进程未正常结束：' + str(event['finished']))
                state['process'] = None
                save()
                start_button.configure(state='normal')
                status.set(('对比未完成：' + state['errors'][-1]) if state['errors'] else
                           '已停止并保存至 transcripts/' + state['output'].name + '。比较漏词与误词，文字更多不一定更准确。')
        if dirty:
            for name, view in views.items():
                view.configure(state='normal')
                view.delete('1.0', 'end')
                view.insert('end', state[name][-5000:])
                view.configure(state='disabled')
                view.yview_moveto(1)
        if state['stopping_at'] and state['process'] and time.monotonic() - state['stopping_at'] > 20:
            kill_tree(state['process'].pid)
        if state['closing'] and not state['process']:
            root.destroy()
        else:
            root.after(150, poll)
    root.protocol('WM_DELETE_WINDOW', close)
    poll()
    root.mainloop()


if __name__ == '__main__':
    main()
