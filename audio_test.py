import pyaudio
import numpy as np
import resampy
import wave
import time

# Parameters
FORMAT = pyaudio.paInt16
CHANNELS = 1
INPUT_RATE = 48000
OUTPUT_RATE = 24000
CHUNK = 8192
RECORD_SECONDS = 10
OUTPUT_FILENAME = "resampled_output.wav"

# Setup PyAudio
p = pyaudio.PyAudio()

print(f"[INFO] Opening stream at {INPUT_RATE} Hz...")
stream = p.open(format=FORMAT,
                channels=CHANNELS,
                rate=INPUT_RATE,
                input=True,
                frames_per_buffer=CHUNK)

frames = []
print(f"[INFO] Recording for {RECORD_SECONDS} seconds...")

start_time = time.time()
while time.time() - start_time < RECORD_SECONDS:
    data = stream.read(CHUNK, exception_on_overflow=False)
    frames.append(data)
    time.sleep(0.001)

print("[INFO] Done recording.")

stream.stop_stream()
stream.close()
p.terminate()

# Convert to numpy array
audio_data = np.frombuffer(b"".join(frames), dtype=np.int16)

# Resample to 24kHz
print(f"[INFO] Resampling from {INPUT_RATE} Hz to {OUTPUT_RATE} Hz...")
resampled = resampy.resample(audio_data.astype(np.float32), INPUT_RATE, OUTPUT_RATE)
resampled_int16 = resampled.astype(np.int16)

# Write to .wav
print(f"[INFO] Saving to {OUTPUT_FILENAME}")
with wave.open(OUTPUT_FILENAME, 'wb') as wf:
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(p.get_sample_size(FORMAT))
    wf.setframerate(OUTPUT_RATE)
    wf.writeframes(resampled_int16.tobytes())

print("[INFO] Done.")
