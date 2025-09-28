import asyncio
import base64
import os
import numpy as np
import resampy
import pyaudio
from queue import Queue
import time
import traceback
import wave

from realtime_client import RealtimeClient

class AudioManager:
    """
    Manages microphone input -> server, and server audio -> speaker output.

    - Capture mic audio in small chunks, resample to the negotiated model rate (16 kHz or 24 kHz),
      base64-encode, and enqueue for sending to the GPT model.
    - Buffer incoming audio from GPT and play it out smoothly in near-realtime.
    """

    def __init__(self, action_manager, loop, input_rate=48000, output_rate=24000, chunk_size=2048):
        self.action_manager = action_manager
        self.loop = loop  # Store the loop reference

        model_rate_override = os.environ.get("MODEL_SAMPLE_RATE")
        preferred_model_rate = int(model_rate_override or output_rate)
        desired_input_rate = int(os.environ.get("AUDIO_INPUT_RATE", input_rate))
        # Desired speaker rate defaults to preferred model rate but may be overridden
        desired_speaker_rate = int(os.environ.get("AUDIO_OUTPUT_RATE", preferred_model_rate))

        env_chunk = os.environ.get("AUDIO_CHUNK_SIZE")
        base_chunk_frames = int(env_chunk) if env_chunk else (1024 if chunk_size == 2048 else chunk_size)
        base_chunk_frames = max(256, base_chunk_frames)

        self.p = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None

        self.input_device_info = self._get_default_device(is_input=True)
        self.output_device_info = self._get_default_device(is_input=False)
        self.input_device_index = self.input_device_info.get("index") if self.input_device_info else None
        self.output_device_index = self.output_device_info.get("index") if self.output_device_info else None

        self.input_rate = self._select_supported_rate(
            device_info=self.input_device_info,
            desired_rate=desired_input_rate,
            fallback_rates=[desired_input_rate, preferred_model_rate, 48000, 44100, 32000, 24000, 16000, 11025, 8000],
            is_input=True
        )
        self.speaker_rate = self._select_supported_rate(
            device_info=self.output_device_info,
            desired_rate=desired_speaker_rate,
            fallback_rates=[desired_speaker_rate, preferred_model_rate, 48000, 44100, 32000, 24000, 16000, 11025, 8000],
            is_input=False
        )

        # Finalize model (server) rate: default to 24 kHz when devices can sustain it, else 16 kHz
        if model_rate_override:
            override_rate = int(model_rate_override)
            self.model_rate = 24000 if override_rate >= 24000 else 16000
            if override_rate not in (16000, 24000):
                print(f"[AudioManager] MODEL_SAMPLE_RATE override {override_rate} Hz normalized to {self.model_rate} Hz (supported: 16000 or 24000)")
        else:
            available_rates = [rate for rate in (self.input_rate, self.speaker_rate) if rate]
            min_rate = min(available_rates) if available_rates else 0
            self.model_rate = 24000 if min_rate >= 24000 else 16000

        # Derive chunk sizes tuned for each domain (model ↔ devices)
        self.model_chunk_frames = base_chunk_frames
        self.input_chunk_size = max(128, int(round(base_chunk_frames * (self.input_rate / self.model_rate))))
        self.output_chunk_size = max(128, int(round(base_chunk_frames * (self.speaker_rate / self.model_rate))))

        print(f"[AudioManager] Model sample rate: {self.model_rate} Hz")
        print(f"[AudioManager] Microphone sample rate: {self.input_rate} Hz")
        print(f"[AudioManager] Speaker sample rate: {self.speaker_rate} Hz")
        print(f"[AudioManager] Chunk frames (model/mic/speaker): {self.model_chunk_frames}/{self.input_chunk_size}/{self.output_chunk_size}")

        self.outgoing_data_queue = asyncio.Queue()  # For sending audio to the server
        self.incoming_audio_queue = asyncio.Queue()  # For audio playback
        self.dropped_frames = 0
        self.is_shutting_down = False  # Shutdown flag
        self._playback_task = None  # To manage the playback task
        self.last_user_audio_chunk_time = 0.0  # latency instrumentation
        self.latest_volume = 0.0
        self.enable_barge_in = os.environ.get("ENABLE_BARGE_IN", "0") == "1"

        # Find device indices (replace with your actual logic if needed)
        # self.input_device_index = self._find_device_index("pulse")  # Example
        # self.output_device_index = self._find_device_index("pulse")  # Example

        # print(f"[AudioManager] Input Device Index: {self.input_device_index}")
        # print(f"[AudioManager] Output Device Index: {self.output_device_index}")

    
    def clear_audio_buffer(self):
        """Clears the outgoing audio data queue."""
        print("[AudioManager] Clearing outgoing audio buffer...")
        
        # self.output_stream.close()  # Close the output stream
        # self.output_stream = self.p.open(
        #         format=pyaudio.paInt16,
        #         channels=1,
        #         rate=self.output_rate,
        #         output=True,
        #         # output_device_index=self.output_device_index,
        #         frames_per_buffer=self.chunk_size,
        #         stream_callback=self.audio_output_callback
        #     )
        self.incoming_audio_queue = asyncio.Queue()
        self._audio_buffer = bytearray()


    def _get_default_device(self, is_input: bool):
        direction = "input" if is_input else "output"
        try:
            if is_input:
                return self.p.get_default_input_device_info()
            return self.p.get_default_output_device_info()
        except Exception as e:
            print(f"[AudioManager] Warning: unable to fetch default {direction} device: {e}")
            return None

    def _select_supported_rate(self, device_info, desired_rate, fallback_rates, is_input: bool):
        candidates = []
        if desired_rate:
            candidates.append(desired_rate)
        if device_info:
            default_rate = device_info.get("defaultSampleRate")
            if default_rate:
                candidates.append(default_rate)
        candidates.extend(fallback_rates or [])

        normalized = []
        seen = set()
        for rate in candidates:
            try:
                rate_int = int(round(float(rate)))
            except (TypeError, ValueError):
                continue
            if rate_int <= 0 or rate_int in seen:
                continue
            seen.add(rate_int)
            normalized.append(rate_int)

        if not normalized:
            normalized = [16000]

        for rate in normalized:
            try:
                kwargs = {"rate": rate}
                if is_input:
                    kwargs.update({
                        "input_channels": 1,
                        "input_format": pyaudio.paInt16,
                    })
                    if device_info:
                        kwargs["input_device"] = device_info["index"]
                else:
                    kwargs.update({
                        "output_channels": 1,
                        "output_format": pyaudio.paInt16,
                    })
                    if device_info:
                        kwargs["output_device"] = device_info["index"]

                self.p.is_format_supported(**kwargs)
                return rate
            except Exception:
                continue

        fallback_rate = normalized[0]
        role = "input" if is_input else "output"
        print(f"[AudioManager] Warning: falling back to {fallback_rate} Hz for {role}; no preferred rate supported")
        return fallback_rate

    def _resample(self, samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
        if target_rate <= 0 or source_rate <= 0:
            return samples
        if source_rate == target_rate or samples.size == 0:
            return samples
        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)
        return resampy.resample(samples, source_rate, target_rate, axis=0, filter='kaiser_fast')


    def _find_device_index(self, device_name):
        """Find the device index for the given device name."""
        for i in range(self.p.get_device_count()):
            device_info = self.p.get_device_info_by_index(i)
            if device_name.lower() in device_info.get("name", "").lower():
                return i
        return None

    def person_speaking(self):
        """
        Check if the person is speaking by checking the latest volume.
        This is a placeholder for more complex logic.
        """
        return self.latest_volume > 30

    def queue_audio(self, audio_bytes: bytes):
        """Add incoming audio to the queue for playback."""
        try:
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
            if audio_np.size == 0:
                return

            if self.speaker_rate != self.model_rate:
                resampled = self._resample(audio_np, self.model_rate, self.speaker_rate)
                audio_np = np.clip(resampled, -32768, 32767).astype(np.int16)

            chunk_source = audio_np.tobytes()

            chunk_bytes = self.output_chunk_size * 2
            if chunk_bytes <= 0:
                chunk_bytes = len(chunk_source)

            for i in range(0, len(chunk_source), chunk_bytes):
                audio_chunk = chunk_source[i:i+chunk_bytes]
                if audio_chunk:
                    self.incoming_audio_queue.put_nowait(audio_chunk)
        except asyncio.QueueFull:
            print("[AudioManager] Incoming audio queue is full. Dropping audio chunk.")
        except Exception as e:
            print(f"[AudioManager] Error in queue_audio: {e}")
            traceback.print_exc()

    def stop_streams(self):
        """Stop both input and output streams."""
        if self.input_stream:
            self.input_stream.stop_stream()
            self.input_stream.close()
            self.input_stream = None
        if self.output_stream:
            self.output_stream.stop_stream()
            self.output_stream.close()
            self.output_stream = None
        print("[AudioManager] Streams stopped.")
        self.dropped_frames = 0
        self.latest_volume = 0
        self.action_manager.isTalkingMovement = False
        self.incoming_audio_queue = asyncio.Queue(maxsize=100)
        self.outgoing_data_queue = asyncio.Queue(maxsize=100)
        print("[AudioManager] Queues cleared.")

    def start_streams(self):
        """Initialize both input and output streams with error handling."""
        try:
            input_kwargs = dict(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.input_rate,
                input=True,
                frames_per_buffer=self.input_chunk_size,
                stream_callback=self.audio_input_callback
            )
            if self.input_device_index is not None:
                input_kwargs["input_device_index"] = self.input_device_index
            self.input_stream = self.p.open(**input_kwargs)
            print("[AudioManager] Input stream initialized successfully.")
        except Exception as e:
            print(f"[AudioManager] Error initializing input stream: {e}")
            traceback.print_exc()
            self.input_stream = None

        try:
            output_kwargs = dict(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.speaker_rate,
                output=True,
                frames_per_buffer=self.output_chunk_size,
                stream_callback=self.audio_output_callback
            )
            if self.output_device_index is not None:
                output_kwargs["output_device_index"] = self.output_device_index
            self.output_stream = self.p.open(**output_kwargs)
            print("[AudioManager] Output stream initialized successfully.")
        except Exception as e:
            print(f"[AudioManager] Error initializing output stream: {e}")
            traceback.print_exc()
            self.output_stream = None

        if self.input_stream is None or self.output_stream is None:
            print("[AudioManager] One or both streams failed to initialize. Please check the configuration.")

    def audio_input_callback(self, in_data, frame_count, time_info, status):
        audio_data = np.frombuffer(in_data, dtype=np.int16)
        self.latest_volume = np.sqrt(np.mean(audio_data**2))
        # If robot speaking, drop mic unless barge-in enabled
        if (self.action_manager.isTalkingMovement and not self.action_manager.PIDOG_SPEAKER_DISABLED \
            and not self.enable_barge_in):
            return (None, pyaudio.paContinue)
        
        try:
            if self.input_rate == self.model_rate:
                resampled_data = audio_data
            else:
                method = os.environ.get("RESAMPLE_METHOD", "resampy")
                if method == "linear":
                    # Simple linear interpolation (fast, lower quality)
                    duration = len(audio_data) / self.input_rate
                    target_len = int(duration * self.model_rate)
                    x_old = np.arange(len(audio_data))
                    x_new = np.linspace(0, len(audio_data)-1, target_len)
                    resampled_data = np.interp(x_new, x_old, audio_data).astype(np.int16)
                else:
                    resampled = self._resample(audio_data, self.input_rate, self.model_rate)
                    resampled_data = np.clip(resampled, -32768, 32767).astype(np.int16)
            resampled_bytes = resampled_data.astype(np.int16).tobytes()
            self.last_user_audio_chunk_time = time.time()
            if self.loop.is_running():
                asyncio.run_coroutine_threadsafe(self._safe_queue_put(resampled_bytes), self.loop)
        except Exception as e:
            print(f"[AudioManager] Error adding audio to outgoing_data_queue: {e}")
            traceback.print_exc()
            self.dropped_frames += 1
            if self.dropped_frames % 100 == 0:
                print(f"[AudioManager] Dropped {self.dropped_frames} chunks so far")

        return (None, pyaudio.paContinue)

    async def _safe_queue_put(self, data):
        if not self.loop.is_running():
            return

        try:
            await asyncio.wait_for(self.outgoing_data_queue.put(data), timeout=0.01)
        except asyncio.TimeoutError:
            self.dropped_frames += 1
            if self.dropped_frames % 100 == 0:
                print(f"[AudioManager] Dropped {self.dropped_frames} frames due to queue full")
        except Exception as e:
            if self.loop.is_running():
                print(f"[AudioManager] Error in _safe_queue_put: {e}")

    def audio_output_callback(self, in_data, frame_count, time_info, status):
        try:
            expected_size = frame_count * 2

            if not hasattr(self, "_audio_buffer"):
                self._audio_buffer = bytearray()

            if not self.incoming_audio_queue.empty() and not self.action_manager.isTalkingMovement:
                self.action_manager.isTalkingMovement = True
                self.loop.call_soon_threadsafe(asyncio.create_task, self.action_manager.start_talking())

            while len(self._audio_buffer) < expected_size and not self.incoming_audio_queue.empty():
                audio_chunk = self.incoming_audio_queue.get_nowait()
                self._audio_buffer.extend(audio_chunk)

            if len(self._audio_buffer) >= expected_size:
                audio_chunk = self._audio_buffer[:expected_size]
                self._audio_buffer = self._audio_buffer[expected_size:]
            else:
                audio_chunk = self._audio_buffer
                audio_chunk += b'\x00' * (expected_size - len(audio_chunk))
                self._audio_buffer = bytearray()

                if self.action_manager.isTalkingMovement:
                    self.action_manager.isTalkingMovement = False
                    self.loop.call_soon_threadsafe(asyncio.create_task, self.action_manager.stop_talking())

            audio_data_np = np.frombuffer(audio_chunk, dtype=np.int16)
            scaled_data_np = np.clip(audio_data_np * self.action_manager.state.volume, -32768, 32767).astype(np.int16)

            if self.action_manager.isTalkingMovement:
                audio_float = scaled_data_np.astype(np.float32)
                rms = np.sqrt(np.mean(audio_float**2))
                norm_amp = min(rms / 10000.0, 1.0)
                r = int(255 * norm_amp)
                g = int(255 * (1 - norm_amp))
                b = 0
                brightness = 0.2 + 0.8 * norm_amp
                try:
                    self.action_manager.set_lightbar_direct(r, g, b, brightness)
                except Exception as viz_error:
                    print(f"[AudioManager] Error in visualization: {viz_error}")

            return (scaled_data_np.tobytes(), pyaudio.paContinue)

        except Exception as e:
            print(f"[AudioManager] Error in audio_output_callback: {e}")
            traceback.print_exc()
            return (b'\x00' * frame_count * 2, pyaudio.paContinue)

    def close(self):
        print("[AudioManager] Closing streams...")
        if self.input_stream:
            try:
                self.input_stream.stop_stream()
                self.input_stream.close()
            except Exception as e:
                print(f"[AudioManager] Error closing input stream: {e}")

        if self.output_stream:
            try:
                self.output_stream.stop_stream()
                self.output_stream.close()
            except Exception as e:
                print(f"[AudioManager] Error closing output stream: {e}")

        if self.p:
            try:
                self.p.terminate()
            except Exception as e:
                print(f"[AudioManager] Error terminating PyAudio: {e}")

        print("[AudioManager] Streams closed.")
