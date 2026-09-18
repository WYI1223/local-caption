"""Keep Windows microphone capture on the WASAPI default endpoint when available."""
def select_device(audio, pa, source):
    if source == 'system':
        return audio.get_default_wasapi_loopback(), 'wasapi-loopback'
    try:
        host = audio.get_host_api_info_by_type(pa.paWASAPI)
        index = int(host['defaultInputDevice'])
        if index < 0:
            raise ValueError('No WASAPI input endpoint')
        device = audio.get_device_info_by_index(index)
        if not device['maxInputChannels'] or device.get('isLoopbackDevice', False):
            raise ValueError('Invalid WASAPI input endpoint')
        return device, 'wasapi-microphone'
    except (OSError, ValueError):
        # Older devices/backends may not expose WASAPI; record the fallback.
        return audio.get_default_input_device_info(), 'default-input-fallback'
