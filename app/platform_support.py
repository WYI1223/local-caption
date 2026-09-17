"""Small OS boundary for subprocesses and the desktop shell."""
import os
from pathlib import Path
import signal
import subprocess
import sys

WINDOWS = os.name == 'nt'
BASE = Path(__file__).resolve().parents[1]
PYTHON = BASE / ('translation/.venv/Scripts/python.exe' if WINDOWS else 'translation/.venv/bin/python')


def available_commit_gib():
    """Windows available system commit, not free physical RAM."""
    if not WINDOWS:
        return None
    import ctypes
    class Memory(ctypes.Structure):
        _fields_ = [('length', ctypes.c_uint32), ('load', ctypes.c_uint32)] + [
            (key, ctypes.c_uint64) for key in ('total_phys', 'available_phys', 'total_pagefile',
                'available_pagefile', 'total_virtual', 'available_virtual', 'available_extended')]
    value = Memory()
    value.length = ctypes.sizeof(value)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
        raise ctypes.WinError()
    return value.available_pagefile / 2**30


def process_options(console=False):
    if not WINDOWS:
        return {'start_new_session': True}
    result = {'creationflags': subprocess.CREATE_NEW_CONSOLE if console else subprocess.CREATE_NO_WINDOW}
    if console:
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        result['startupinfo'] = startup
    return result


def kill_tree(pid):
    try:
        if WINDOWS:
            subprocess.run(['taskkill.exe', '/PID', str(pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10, **process_options())
        else:
            os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, subprocess.SubprocessError):
        pass


def open_folder(path):
    if WINDOWS:
        os.startfile(path)
    else:
        subprocess.Popen(['open', str(path)])
