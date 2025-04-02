import numpy as np
import pyaudio
import wave
import os
import time
from scipy.signal import resample
from scipy.io import wavfile
from scipy.io.wavfile import write as wav_write
import pyttsx3
import openai
from keys import OPENAI_API_KEY

# === CONFIG ===
ORIGINAL_RATE = 48000
TARGET_RATE = 24000
CHANNELS = 1
FORMAT = pyaudio.paInt16
FRAMES_PER_BUFFER = 512
DURATION = 20.0  # seconds
SAMPLES_ORIG = int(ORIGINAL_RATE * DURATION)

client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Devices (change as needed)
input_device_index = 2   # Your USB mic
output_device_index = 1  # Your speakers/DAC

os.makedirs("recordings", exist_ok=True)
wanted_tts_path = "recordings/wanted_tmp.wav"
unwanted_tts_path = "recordings/unwanted_source.wav"

def tts_to_wav(text, path, voice="coral", add_click=False):
    # Generate TTS audio
    with client.audio.speech.with_streaming_response.create(
        model="gpt-4o-mini-tts",
        voice=voice,
        input=text,
        response_format="wav",
        instructions="Speak in a cheerful and positive tone.",
    ) as response:
        response.stream_to_file(path)
        print(f"💾 TTS saved to {path}")

    if add_click:
        # Add click sound with silence
        sample_rate = TARGET_RATE
        silence_duration = int(0.05 * sample_rate)  # 50ms silence
        click_duration = int(0.01 * sample_rate)    # 10ms click
        amplitude = 0.5                             # Click amplitude (scaled to 16-bit range)

        # Generate silence and click
        silence = np.zeros(silence_duration, dtype=np.float32)
        click = (amplitude * np.ones(click_duration, dtype=np.float32)).astype(np.float32)

        # Combine silence, click, and silence
        click_with_silence = np.concatenate([silence, click, silence])

        # Read the generated TTS audio
        sr, tts_audio = wavfile.read(path)
        if tts_audio.ndim > 1:  # If stereo, take only one channel
            tts_audio = tts_audio[:, 0]
        # tts_audio = tts_audio.astype(np.float32) / 32767.0  # Normalize to [-1, 1]

        
        click_with_silence = (click_with_silence * 32767).astype(np.int16)  # Convert back to 16-bit PCM

        # Combine click sound with TTS audio
        combined_audio = np.concatenate([click_with_silence, tts_audio])

        # Save the new audio with the click prepended
        wav_write(path, sample_rate, combined_audio)
        print(f"🔊 Added click sound to {path}")

# print("🗣 Generating TTS...")

# # Unwanted background audio
# tts_to_wav(
#     "This is the unwanted background audio. It represents noise or interference that should be removed from the mix. "
#     "Imagine this as a busy street with cars honking, people talking, and general chaos. Testing, one, two, three."
#     "I'm saying additional words now so you can have better data to ensure a good model is learned. There is planty of text here to create the training data you need so I will stop talking now.",
#     unwanted_tts_path
# )

# # Wanted foreground speech
# tts_to_wav(
#     "Hi! Wanted foreground speech here. It contains the important message that should remain clear and audible. "
#     "For example, this could be a person giving instructions or narrating a story. "
#     "Please ensure that this voice is preserved and stands out from the background noise. Thank you for your attention. I will now stop talking.",
#     wanted_tts_path,
#     "ash",
#     True
# )
# === LOAD + LOOP AUDIO ===
def load_looped_signal(path, duration_sec, sample_rate):
    sr, data = wavfile.read(path)
    if data.ndim > 1:
        data = data[:, 0]
    data = data.astype(np.float32) / 32767.0
    if sr != sample_rate:
        data = resample(data, int(len(data) * sample_rate / sr))
    reps = int(np.ceil(sample_rate * duration_sec / len(data)))
    return np.tile(data, reps)[:int(sample_rate * duration_sec)]

wanted_signal = load_looped_signal(wanted_tts_path, DURATION, ORIGINAL_RATE)
unwanted_signal = load_looped_signal(unwanted_tts_path, DURATION, ORIGINAL_RATE)

# Scale and convert
unwanted_signal *= 1
wanted_signal *= 1

unwanted_pcm = (unwanted_signal * 32767).astype(np.int16)
wanted_pcm = (wanted_signal * 32767).astype(np.int16)

min_len = min(len(unwanted_pcm), len(wanted_pcm))
combined_pcm = ((unwanted_pcm[:min_len].astype(np.int32) + wanted_pcm[:min_len].astype(np.int32)) // 2).astype(np.int16)

# Convert to bytes
unwanted_bytes = unwanted_pcm.tobytes()
wanted_bytes = wanted_pcm.tobytes()
combined_bytes = combined_pcm.tobytes()

# === RECORDING FUNCTION ===
def record_playback(audio_bytes, duration, filename, p, input_device_index, output_device_index, volume_scale=1.0):
    recorded = []
    cursor = 0
    done = False

    def callback(in_data, frame_count, time_info, status):
        nonlocal cursor, done
        start = cursor
        end = start + frame_count * 2
        chunk = audio_bytes[start:end]
        if len(chunk) < frame_count * 2:
            chunk += b'\x00' * (frame_count * 2 - len(chunk))
            done = True
        cursor += frame_count * 2
        recorded.append(in_data)
        #scale chunk by volume_scale
        scaled_chunk = np.frombuffer(chunk, dtype=np.int16) * volume_scale
        scaled_chunk = scaled_chunk.astype(np.int16)
        # Convert to bytes
        chunk_bytes = scaled_chunk.tobytes()
        return (chunk_bytes, pyaudio.paContinue)

    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=ORIGINAL_RATE,
                    input=True,
                    output=True,
                    input_device_index=input_device_index,
                    output_device_index=output_device_index,
                    frames_per_buffer=FRAMES_PER_BUFFER,
                    stream_callback=callback)

    print(f"▶️ Playing and recording: {filename}")
    stream.start_stream()
    while stream.is_active() and not done:
        time.sleep(0.1)
    stream.stop_stream()
    stream.close()

    raw = np.frombuffer(b''.join(recorded), dtype=np.int16).astype(np.float32)
    resampled = resample(raw, int(len(raw) * TARGET_RATE / ORIGINAL_RATE)).astype(np.int16)

    with wave.open(f"recordings/{filename}", 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(TARGET_RATE)
        wf.writeframes(resampled.tobytes())



# === PY AUDIO ===
p = pyaudio.PyAudio()

# Save unwanted source (clean reference)
# resampled_unwanted = resample(unwanted_pcm.astype(np.float32), int(len(unwanted_pcm) * TARGET_RATE / ORIGINAL_RATE)).astype(np.int16)
# wavfile.write("recordings/unwanted_source.wav", TARGET_RATE, resampled_unwanted)
# print("💾 Saved unwanted_source.wav (raw)")

# Record playback
record_playback(wanted_bytes, DURATION, "aec2_test_mic_audio.wav", p, input_device_index, output_device_index, volume_scale=1)
#record_playback(combined_bytes, DURATION, "recorded_mic_audio.wav", p, input_device_index, output_device_index)

p.terminate()
print("✅ Done! All WAVs saved to recordings/ at 24kHz.")
