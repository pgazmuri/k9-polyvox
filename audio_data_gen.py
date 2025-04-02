import numpy as np
import pyaudio
import wave
import os
import time

# Constants
RATE = 48000
CHANNELS = 1
FORMAT = pyaudio.paInt16
FRAMES_PER_BUFFER = 512
DURATION = 1.0  # per sound
SAMPLES = int(RATE * DURATION)

# Output dir
os.makedirs("recordings", exist_ok=True)

# Timebase for one clip
t = np.linspace(0, DURATION, SAMPLES, endpoint=False)

# Sound functions
def tone(): return 0.5 * np.sin(2 * np.pi * 440 * t)
def chirp(): return np.sin(2 * np.pi * t * (200 + (8000 - 200) * t / DURATION))
def impulse():
    s = np.zeros_like(t)
    for _ in range(5): s[np.random.randint(0, len(t))] = 1.0
    return s
def white_noise(): return 0.3 * np.random.randn(len(t))
def pink_noise():
    wn = np.random.randn(len(t))
    return 0.3 * np.convolve(wn, np.ones(8)/8, mode='same')
def am():
    c = np.sin(2 * np.pi * 1000 * t)
    m = 0.5 * (1.0 + np.sin(2 * np.pi * 5 * t))
    return c * m
def fm():
    mf = 100; mi = 10; cf = 500
    return np.sin(2 * np.pi * cf * t + mi * np.sin(2 * np.pi * mf * t))
def burst():
    s = np.sin(2 * np.pi * 1000 * t)
    env = (np.sin(2 * np.pi * 5 * t) > 0).astype(float)
    return s * env
def glitch():
    w = np.zeros_like(t)
    for _ in range(50):
        start = np.random.randint(0, len(t)-10)
        w[start:start+10] = np.random.uniform(-1, 1, 10)
    return w
def composite():
    tone = np.sin(2 * np.pi * 880 * t)
    noise = 0.3 * np.random.randn(len(t))
    am = 0.5 * (1.0 + np.sin(2 * np.pi * 3 * t))
    return am * (tone + noise)

sound_funcs = [
    tone, chirp, impulse, white_noise, pink_noise,
    am, fm, burst, glitch, composite
]

# Generate all sounds and stack into one buffer
print("🔊 Generating composite audio...")
full_signal = np.concatenate([f() for f in sound_funcs])
full_signal = (full_signal * 0.316 * 32767).astype(np.int16)

# full_signal = (full_signal * 32767).astype(np.int16)
playback_buffer = full_signal.tobytes()

# Globals
recorded_frames = []
playback_cursor = 0
done = False

# Callback
def callback(in_data, frame_count, time_info, status):
    global playback_cursor, done

    start = playback_cursor
    end = start + frame_count * 2  # 2 bytes per sample
    chunk = playback_buffer[start:end]

    if len(chunk) < frame_count * 2:
        chunk += b'\x00' * (frame_count * 2 - len(chunk))
        done = True

    playback_cursor += frame_count * 2
    recorded_frames.append(in_data)

    return (chunk, pyaudio.paContinue)

# PyAudio init
p = pyaudio.PyAudio()
input_device_index = 2   # USB mic
output_device_index = 1  # DAC

stream = p.open(format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                output=True,
                input_device_index=input_device_index,
                output_device_index=output_device_index,
                frames_per_buffer=FRAMES_PER_BUFFER,
                stream_callback=callback)


print("▶️ Playing all 10 sounds...")
stream.start_stream()
while stream.is_active() and not done:
    time.sleep(0.1)
stream.stop_stream()
stream.close()
p.terminate()

print("💾 Saving output and input...")

with wave.open("recordings/output.wav", 'wb') as wf:
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(p.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(playback_buffer)

with wave.open("recordings/input.wav", 'wb') as wf:
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(p.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(b''.join(recorded_frames))

print("✅ Done: recordings/output.wav + input.wav")
