import numpy as np
import pyaudio
import time
from scipy.signal import correlate, chirp
import wave

# Config
RATE = 48000
CHUNK = 1024
CHANNELS = 1
FORMAT = pyaudio.paInt16
SIGNAL_DURATION = 0.1     # seconds
FREQ_START = 500          # Hz
FREQ_END = 4000           # Hz
TEST_COUNT = 10
RECORD_DURATION = 1.0     # seconds

# Generate a chirp sweep signal
t = np.linspace(0, SIGNAL_DURATION, int(RATE * SIGNAL_DURATION), endpoint=False)
chirp_wave = chirp(t, f0=FREQ_START, f1=FREQ_END, t1=SIGNAL_DURATION, method='linear')
window = np.hanning(len(chirp_wave))
signal = (chirp_wave * window).astype(np.float32)
signal_pcm = (signal * 32767).astype(np.int16).tobytes()

# Optional: save chirp for reference
with wave.open("chirp_tone.wav", "wb") as wf:
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(2)
    wf.setframerate(RATE)
    wf.writeframes(signal_pcm)

# Setup PyAudio
p = pyaudio.PyAudio()
stream_out = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True, frames_per_buffer=CHUNK)
stream_in = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)

delays = []
confidences = []

print("[INFO] Starting chirp echo delay tests...\n")

for test in range(TEST_COUNT):
    print(f"[INFO] Test {test + 1}/{TEST_COUNT}")

    # Start stream, pre-buffer one frame
    frames = []
    stream_in.start_stream()
    data = stream_in.read(CHUNK, exception_on_overflow=False)
    frames.append(data)

    # Play chirp after one frame
    stream_out.write(signal_pcm)

    # Record remaining duration
    start_time = time.time()
    while time.time() - start_time < RECORD_DURATION:
        data = stream_in.read(CHUNK, exception_on_overflow=False)
        frames.append(data)

    # Process recording
    recorded = np.frombuffer(b''.join(frames), dtype=np.int16).astype(np.float32)

    # Cross-correlation (positive lags only)
    corr = correlate(recorded, signal, mode='full')
    mid = len(signal) - 1
    corr_positive = corr[mid:]
    lag = np.argmax(corr_positive)

    # Subtract one frame worth of lag (because we delayed chirp by 1 CHUNK)
    adjusted_lag = lag - CHUNK
    delay_sec = adjusted_lag / RATE
    confidence = np.max(corr_positive) / np.sum(np.abs(signal))

    delays.append(delay_sec)
    confidences.append(confidence)

    print(f"  → Delay: {delay_sec:.3f} sec | Confidence: {confidence:.2f}\n")

# Cleanup
stream_out.stop_stream()
stream_in.stop_stream()
stream_out.close()
stream_in.close()
p.terminate()

# Results
print(f"[RESULT] Average Delay: {np.mean(delays):.3f} seconds")
print(f"[RESULT] Average Confidence: {np.mean(confidences):.2f}")
