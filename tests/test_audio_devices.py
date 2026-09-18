import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from audio_devices import select_device

class DeviceTest(unittest.TestCase):
    def test_uses_wasapi_endpoint_not_legacy_default(self):
        class Audio:
            def get_host_api_info_by_type(self,kind):return {'defaultInputDevice':19}
            def get_device_info_by_index(self,index):
                assert index==19
                return {'maxInputChannels':4,'defaultSampleRate':48000}
            def get_default_input_device_info(self):raise AssertionError('MME must not be selected')
        device,route=select_device(Audio(),SimpleNamespace(paWASAPI=13),'microphone')
        self.assertEqual(device['defaultSampleRate'],48000)
        self.assertEqual(route,'wasapi-microphone')
    def test_fallback_and_system_route(self):
        class Audio:
            def get_host_api_info_by_type(self,kind):raise OSError('Unavailable')
            def get_default_input_device_info(self):return {'index':1}
            def get_default_wasapi_loopback(self):return {'index':5}
        pa=SimpleNamespace(paWASAPI=13)
        self.assertEqual(select_device(Audio(),pa,'microphone'),({'index':1},'default-input-fallback'))
        self.assertEqual(select_device(Audio(),pa,'system'),({'index':5},'wasapi-loopback'))
if __name__=='__main__':unittest.main()
