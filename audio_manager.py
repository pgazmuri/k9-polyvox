import asyncio
import base64
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

    - Capture mic audio in small chunks, resample from 44.1kHz to 24kHz,
      base64-encode, and enqueue for sending to the GPT model.
    - Buffer incoming audio from GPT and play it out smoothly in near-realtime.
    """

    def __init__(self, action_manager, loop, input_rate=48000, output_rate=24000, chunk_size=2048):
        self.action_manager = action_manager
        self.loop = loop  # Store the loop reference
        self.input_rate = input_rate
        self.output_rate = output_rate
        self.chunk_size = chunk_size  # Chunk size for input stream
        self.p = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        self.outgoing_data_queue = asyncio.Queue() # For sending audio to the server
        self.incoming_audio_queue = asyncio.Queue()  # For audio playback
        self.dropped_frames = 0
        self.is_shutting_down = False  # Shutdown flag
        self._playback_task = None  # To manage the playback task

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
            for i in range(0, len(audio_bytes), self.chunk_size):
                audio_chunk = audio_bytes[i:i+self.chunk_size]  # Split into chunks
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
            self.input_stream = self.p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.input_rate,
                input=True,
                # input_device_index=self.input_device_index,
                frames_per_buffer=self.chunk_size,
                stream_callback=self.audio_input_callback
            )
            print("[AudioManager] Input stream initialized successfully.")
        except Exception as e:
            print(f"[AudioManager] Error initializing input stream: {e}")
            traceback.print_exc()
            self.input_stream = None

        try:
            self.output_stream = self.p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.output_rate,
                output=True,
                # output_device_index=self.output_device_index,
                frames_per_buffer=self.chunk_size,
                stream_callback=self.audio_output_callback
            )
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


        #if pidog is talking, and the speaker isn't disabled, we need to ignore incoming audio, as it's likely to be feedback
        if self.action_manager.isTalkingMovement and not self.action_manager.PIDOG_SPEAKER_DISABLED:
            return (None, pyaudio.paContinue)
        
        try:
            resampled_data = resampy.resample(audio_data, self.input_rate, self.output_rate)
            resampled_bytes = resampled_data.astype(np.int16).tobytes()

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
