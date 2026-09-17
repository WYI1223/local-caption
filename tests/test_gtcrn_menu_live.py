"""Opt-in Windows E2E: actual Tk menus -> worker -> WASAPI/JFK -> saved transcript.

Run with translation/.venv/Scripts/python.exe; plays a short sample three times.
Translation is disabled through its menu to isolate audio routing.
"""
import json
from pathlib import Path
import sys
import time
import winsound

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'app'))
import floating_asr as ui

OUT=BASE/'diagnostics/gtcrn-menu-e2e'
OUT.mkdir(exist_ok=True)
ui.SAVES=OUT
ui.PREFERENCES=OUT/'preferences.json'
checks=[]


def driver(app):
    app.root.withdraw()
    def invoke(label):
        for i in range(app.settings.index('end')+1):
            if app.settings.type(i)!='separator' and app.settings.entrycget(i,'label')==label:
                app.settings.invoke(i);return
        raise AssertionError(label)
    if app.chinese.get():invoke('中文翻译')
    invoke('输入：系统声音')
    if not app.save_audio.get():invoke('保存原始音频（下次开始生效）')

    def begin(index):
        if index==3:
            assert len(checks)==3
            (OUT/'result.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
            print('PASS',json.dumps(checks,ensure_ascii=True),flush=True)
            app.shutdown();return
        app.filter_menu.invoke(app.filter_indices[index])
        key=('raw','gtcrn25','gtcrn50')[index]
        assert json.loads(ui.PREFERENCES.read_text())['audio_filter']==key
        app.start_button.invoke()
        deadline=time.monotonic()+75
        played=False;stop_at=0;stopped=False
        def poll():
            nonlocal played,stop_at,stopped
            assert time.monotonic()<deadline, 'UI workflow timeout'
            assert not app.errors,app.errors
            if app.capture_device and not played:
                assert app.active_filter==key
                winsound.PlaySound(str(BASE/'samples/jfk.wav'),winsound.SND_FILENAME|winsound.SND_ASYNC)
                played=True;stop_at=time.monotonic()+14
                # Selecting the next mode during capture must not reconfigure this stream.
                app.filter_menu.invoke(app.filter_indices[(index+1)%3])
                assert app.active_filter==key
            if played and not stopped and time.monotonic()>=stop_at:
                app.stop_button.invoke();stopped=True
            if stopped and app.proc is None:
                winsound.PlaySound(None,0)
                assert 'country' in app.text.lower(),app.text
                saved=app.session_file.read_text(encoding='utf-8')
                assert app.text in saved and ui.FILTERS[key] in saved
                assert app.audio_recording.get('complete'),app.audio_recording
                m=app.audio_metrics
                if key!='raw':
                    assert m['enhancement']['mode']==key,m
                    assert m['enhancement']['buffered_samples']==0,m
                else:assert m['enhancement'] is None,m
                assert m['backlog_seconds']<.3,m
                checks.append(dict(mode=key,text=app.text,metrics=m,session=str(app.session_file)))
                app.root.after(100,lambda:begin(index+1));return
            app.root.after(100,poll)
        app.root.after(100,poll)
    begin(0)


if __name__=='__main__':ui.main(driver)
