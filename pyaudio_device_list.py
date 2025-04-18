import pyaudio

p = pyaudio.PyAudio()

print("== OUTPUT Devices ==")
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    if info.get('maxOutputChannels') > 0:
        print(f"[{i}] {info['name']} — rate: {int(info['defaultSampleRate'])} Hz, channels: {int(info['maxOutputChannels'])}")

print("\n== INPUT Devices ==")
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    if info.get('maxInputChannels') > 0:
        print(f"[{i}] {info['name']} — rate: {int(info['defaultSampleRate'])} Hz, channels: {int(info['maxInputChannels'])}")

p.terminate()
