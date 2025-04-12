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

    def __init__(self, 
                 action_manager=None):
        self.input_rate = 48000
        self.output_rate = 24000
        self.chunk_size = 1024
        self.mic_chunk_size = 8192
        self.format = pyaudio.paInt16
        self.channels = 1
        self.action_manager = action_manager

        self.p = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None

        # Using standard Queue for incoming_data_queue because it's accessed from a callback in a different thread
        self.incoming_data_queue = Queue()
        # Using asyncio.Queue for outgoing_data_queue for more efficient async handling
        self.outgoing_data_queue = asyncio.Queue(maxsize=100)
        
        self.loop = asyncio.get_event_loop()  # Get the loop reference for thread-safe operations
        self.dropped_frames = 0
        self.latest_volume = 0
        self.volume_history = []  # Store recent volumes for running average
        self.volume_history_duration = 0.1  # Duration in seconds for running average

    def queue_audio(self, audio_bytes: bytes):
        """Add incoming audio to the queue for playback."""
        for i in range(0, len(audio_bytes), self.chunk_size):
           audio_chunk = audio_bytes[i:i+self.chunk_size]  # Split into chunks
           self.incoming_data_queue.put(audio_chunk)
        #print("Enqueued audio")
        
        
    def start_streams(self):
        """Initialize both input and output streams with error handling."""
        try:
            # Initialize the input stream
            self.input_stream = self.p.open(
                format=self.format,
                channels=self.channels,
                rate=self.input_rate,
                input=True,
                frames_per_buffer=self.mic_chunk_size,
                stream_callback=self.audio_input_callback  # Set the callback function
            )
            print("[AudioManager] Input stream initialized successfully.")
        except Exception as e:
            print(f"[AudioManager] Error initializing input stream: {e}")
            traceback.print_exc()
            self.input_stream = None  # Ensure the input stream is set to None if initialization fails
    
        try:
            # Initialize the output stream
            self.output_stream = self.p.open(
                format=self.format,
                channels=self.channels,
                rate=self.output_rate,
                output=True,
                frames_per_buffer=self.chunk_size,
                # output_device_index=0,  # Set to the desired output device index
                stream_callback=self.audio_output_callback  # Set the callback function
            )
            print("[AudioManager] Output stream initialized successfully.")
        except Exception as e:
            print(f"[AudioManager] Error initializing output stream: {e}")
            traceback.print_exc()
            self.output_stream = None  # Ensure the output stream is set to None if initialization fails
    
        # Check if both streams were initialized successfully
        if self.input_stream is None or self.output_stream is None:
            print("[AudioManager] One or both streams failed to initialize. Please check the configuration.")

    def audio_input_callback(self, in_data, frame_count, time_info, status):
        audio_data = np.frombuffer(in_data, dtype=np.int16)

        # Update volume based on amplitude of audio data
        self.latest_volume = np.sqrt(np.mean(audio_data**2))

        # Update running average of volumes
        self.volume_history.append((self.latest_volume, len(audio_data) / self.input_rate))
        total_duration = sum(duration for _, duration in self.volume_history)
        while total_duration > self.volume_history_duration:
            self.volume_history.pop(0)
            total_duration = sum(duration for _, duration in self.volume_history)
        if(total_duration > 0):
            self.latest_volume = sum(volume * duration for volume, duration in self.volume_history) / total_duration
        # print(f"[AudioManager] Running average volume: {self.latest_volume}")

        try:
            if not self.action_manager.isTalkingMovement:
                # Resample from input_rate (48kHz) to output_rate (24kHz) right here
                resampled_data = resampy.resample(audio_data, self.input_rate, self.output_rate)
                resampled_bytes = resampled_data.astype(np.int16).tobytes()
                
                # Use call_soon_threadsafe to safely put resampled data onto the asyncio queue from this thread
                self.loop.call_soon_threadsafe(
                    lambda data=resampled_bytes: asyncio.create_task(self._safe_queue_put(data))
                )
        except Exception as e:
            # Log the exception details
            print(f"[AudioManager] Error adding audio to outgoing_data_queue: {e}")
            traceback.print_exc()
            # Count or log dropped frames
            self.dropped_frames += 1
            if self.dropped_frames % 100 == 0:
                print(f"[AudioManager] Dropped {self.dropped_frames} chunks so far")

        return (None, pyaudio.paContinue)
    
    async def _safe_queue_put(self, data):
        """Safely put data on the outgoing queue, handling queue full situations."""
        try:
            # Try to put without blocking; if queue is full, drop the frame
            await asyncio.wait_for(self.outgoing_data_queue.put(data), timeout=0.01)
        except asyncio.TimeoutError:
            # Queue is full, drop the frame
            self.dropped_frames += 1
            if self.dropped_frames % 100 == 0:
                print(f"[AudioManager] Dropped {self.dropped_frames} frames due to queue full")
        except Exception as e:
            print(f"[AudioManager] Error in _safe_queue_put: {e}")

    def save_speaker_audio(self, resampled_bytes):
        # # Buffer audio and save the most recent 10 seconds to a file
        filecount=0
        try:
            # Initialize a buffer if it doesn't exist
            if not hasattr(self, "_audio_buffer"):
                self._audio_buffer = bytearray()

            # Append the current resampled audio to the buffer
            self._audio_buffer.extend(resampled_bytes)

            # Calculate the number of bytes corresponding to 10 seconds of audio
            bytes_per_second = 24000 * 1 * 2  # 2 bytes per sample for paInt16
            max_buffer_size = bytes_per_second * 30

            # Trim the buffer to keep only the most recent 10 seconds
            if len(self._audio_buffer) > max_buffer_size:
                self._audio_buffer = self._audio_buffer[-max_buffer_size:]

            # Save the buffered audio to a file every 10 seconds
            if not hasattr(self, "_last_save_time"):
                self._last_save_time = time.monotonic()

            if time.monotonic() - self._last_save_time >= 30:
                with wave.open(f"speaker_{filecount}.wav", "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(24000)
                    wf.writeframes(self._audio_buffer)
                self._last_save_time = time.monotonic()
                filecount = filecount + 1
        except Exception as save_error:
            print(f"[AudioManager] Error saving audio: {save_error}")

    def audio_output_callback(self, in_data, frame_count, time_info, status):
        """
        Callback function for audio output. Buffers audio data until enough is available
        to fill the requested frame size, then flushes the buffer.
        Also handles LED visualization directly to ensure it's synchronized with the played audio.
        """
        try:
            # print("audio_output_callback")
            expected_size = frame_count * self.channels * 2  # 2 bytes per sample for paInt16
    
            # Initialize a buffer if it doesn't exist
            if not hasattr(self, "_audio_buffer"):
                self._audio_buffer = bytearray()
    
            # Check if we're about to start talking
            if not self.incoming_data_queue.empty() and not self.action_manager.isTalkingMovement:
                # Signal that we're starting to talk
                self.action_manager.isTalkingMovement = True
                # Use loop.call_soon_threadsafe if we need to start an async task from a different thread
                self.loop.call_soon_threadsafe(asyncio.create_task, self.action_manager.start_talking())
                
    
            # Fill the buffer with data from the queue
            while len(self._audio_buffer) < expected_size and not self.incoming_data_queue.empty():
                audio_chunk = self.incoming_data_queue.get()
                self._audio_buffer.extend(audio_chunk)
                # print(f"Buffered audio chunk. Buffer size: {len(self._audio_buffer)}")
    
            # If the buffer has enough data, extract the required amount
            if len(self._audio_buffer) >= expected_size:
                audio_chunk = self._audio_buffer[:expected_size]
                self._audio_buffer = self._audio_buffer[expected_size:]  # Remove the used data
            else:
                # If not enough data, pad with silence
                audio_chunk = self._audio_buffer
                audio_chunk += b'\x00' * (expected_size - len(audio_chunk))
                self._audio_buffer = bytearray()  # Clear the buffer after flushing
                
                # If we've run out of audio and were talking, signal that we're done talking
                if self.action_manager.isTalkingMovement:
                    self.action_manager.isTalkingMovement = False
                    # Use loop.call_soon_threadsafe to call async functions from this thread
                    self.loop.call_soon_threadsafe(asyncio.create_task, self.action_manager.stop_talking())
                    
    
            # Scale the audio data
            audio_data_np = np.frombuffer(audio_chunk, dtype=np.int16)
            scaled_data_np = np.clip(audio_data_np * self.action_manager.state.volume, -32768, 32767).astype(np.int16)
            
            # --- Visualization Logic --- 
            if self.action_manager.isTalkingMovement:
                # Convert to float to prevent overflow during calculations
                audio_float = scaled_data_np.astype(np.float32)
                # Compute RMS amplitude
                rms = np.sqrt(np.mean(audio_float**2))
                # Normalize amplitude (adjust scaling factor as needed)
                norm_amp = min(rms / 10000.0, 1.0)
                r = int(255 * norm_amp)
                g = int(255 * (1 - norm_amp))
                b = 0
                brightness = 0.2 + 0.8 * norm_amp
                # Set the light bar color
                # Use a try-except here as this is a critical audio path
                try:
                    self.action_manager.set_lightbar_direct(r, g, b, brightness)
                except Exception as viz_error:
                    # Just log the error but don't interrupt audio output
                    print(f"[AudioManager] Error in visualization: {viz_error}")
            # --- End Visualization ---
            
            return (scaled_data_np.tobytes(), pyaudio.paContinue)
    
        except Exception as e:
            print(f"[AudioManager] Error in audio_output_callback: {e}")
            traceback.print_exc()
            # Return silence on error
            return (b'\x00' * frame_count * self.channels * 2, pyaudio.paContinue)
            

    def close(self):
        """
        Clean up resources: stop streams and terminate PyAudio instance.
        This should be called during application shutdown.
        """
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