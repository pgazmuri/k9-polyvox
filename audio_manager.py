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

        # Incoming audio to play locally
        self.incoming_data_queue = Queue()
        self.outgoing_data_queue = Queue(maxsize=100)
        self.visualizer_data_queue = Queue()

        self.dropped_frames = 0
        self.latest_volume = 0
        self.volume_history = []  # Store recent volumes for running average
        self.volume_history_duration = 0.1  # Duration in seconds for running average

    def queue_audio(self, audio_bytes: bytes):
        """Add incoming audio to the queue for playback."""
        #split the audio into chunks and add to the visualizer queue
        #chunk_size = 1024
        for i in range(0, len(audio_bytes), self.chunk_size):
           audio_chunk = audio_bytes[i:i+self.chunk_size]  # Split into chunks
           self.visualizer_data_queue.put(audio_chunk)
           self.incoming_data_queue.put(audio_chunk)
           asyncio.sleep(0)
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
            if(not self.action_manager.isTalkingMovement):
                #Zero out the audio data, but keep it the same length, this prevents audio from feeding back to mic while dog is talking
                #audio_data = np.zeros_like(audio_data)
                self.outgoing_data_queue.put_nowait(audio_data)
        except Exception as e:
            # Log the exception details
            print(f"[AudioManager] Error adding audio to outgoing_data_queue: {e}")
            traceback.print_exc()
            # Count or log dropped frames
            self.dropped_frames += 1
            if self.dropped_frames % 100 == 0:
                print(f"[AudioManager] Dropped {self.dropped_frames} chunks so far")
        # audio_base64 = base64.b64encode(resampled_bytes).decode('utf-8')
        # await self.client.send("input_audio_buffer.append", {"audio": audio_base64})
        return (None, pyaudio.paContinue)

    # async def capture_microphone(self):
    #     """
    #     Continuously read mic audio, resample, encode, and push to
    #     outgoing_data_queue for the real-time client to send.
    #     """
    #     print("[AudioManager] Starting microphone capture, initializing stream...")

    #     """Initialize both input stream for output."""
    #     self.input_stream = self.p.open(
    #         format=self.format,
    #         channels=self.channels,
    #         rate=self.input_rate,
    #         input=True,
    #         frames_per_buffer=self.chunk_size
    #     )

    #     while True:
    #         try:
    #             # Read all available data from the input stream
    #             while self.input_stream.get_read_available() > 0:
    #                 data = self.input_stream.read(self.mic_chunk_size, exception_on_overflow=False)
    #                 audio_data = np.frombuffer(data, dtype=np.int16)
        
    #                 # Resample 44.1kHz -> 24kHz
    #                 resampled_data = resampy.resample(audio_data, self.input_rate, self.output_rate)
    #                 resampled_bytes = resampled_data.astype(np.int16).tobytes()
        
    #                 # Add the resampled audio to the outgoing queue
    #                 self.outgoing_data_queue.put(resampled_bytes)
        
    #                 print(f"[AudioManager] Processed audio chunk, length: {len(resampled_bytes)}")
        
    #             # Tiny sleep to let the loop breathe
    #             await asyncio.sleep(0.01)
    #         except Exception as e:
    #             print(f"[AudioManager] Error capturing audio: {e}")
    #             await asyncio.sleep(1)  # Attempt a quick delay before continuing

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
        """
        try:
            # print("audio_output_callback")
            expected_size = frame_count * self.channels * 2  # 2 bytes per sample for paInt16
    
            # Initialize a buffer if it doesn't exist
            if not hasattr(self, "_audio_buffer"):
                self._audio_buffer = bytearray()
    
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
    
            # Scale the audio data
            audio_data = np.frombuffer(audio_chunk, dtype=np.int16)
            scaled_data = np.clip(audio_data * self.action_manager.state.volume, -32768, 32767).astype(np.int16)
            
            # resampled_data = resampy.resample(scaled_data, self.input_rate, self.output_rate)
            # self.save_speaker_audio(resampled_data.tobytes())
            
            # Return the scaled audio data to the stream
            return (scaled_data.tobytes(), pyaudio.paContinue)
    
        except Exception as e:
            print(f"[AudioManager] Error in audio_output_callback: {e}")
            traceback.print_exc()
            # Return silence on error
            return (b'\x00' * frame_count * self.channels * 2, pyaudio.paContinue)
            
    async def visualize_audio(self):
        """
        Continuously read raw audio from visualizer_data_queue,
        compute amplitude, and set LED bar accordingly.
        """
        print("[AudioManager] Starting audio visualization...")
        last_empty_time = None  # Track when the queue was last empty
        total_talk_time = None
        talking_started = None
    
        while True:
            try:
                loop_start_time = time.monotonic()  # Record the start time of the loop iteration

                # Wait for audio data to be played back
                if self.visualizer_data_queue.empty():
                    if last_empty_time is None:
                        last_empty_time = time.monotonic()  # Record the time when it became empty
                    elif self.action_manager.isTalkingMovement and time.monotonic() - last_empty_time >= .2:  # Check if it's been empty for .2 second
                        self.action_manager.isTalkingMovement = False
                        await self.action_manager.stop_talking()
                        if(total_talk_time != None):
                            print("total speech length: ", total_talk_time)
                            print("time taken to visualize: ", time.monotonic() - talking_started)
                            talking_started = None
                            total_talk_time = None
                    await asyncio.sleep(0)
                else:
                    # print("[AudioManager] Visualizing audio chunk...")
                    if not self.action_manager.isTalkingMovement:
                        self.action_manager.isTalkingMovement = True #prevent this from running twice...
                        # asyncio.create_task(self.action_manager.start_talking())
                        total_talk_time = 0
                        talking_started = time.monotonic()

                    last_empty_time = None  # Reset if the queue is not empty
    
                    # Process audio data at playback speed
                    chunk = self.visualizer_data_queue.get()
                    if(not self.visualizer_data_queue.empty()):
                        self.visualizer_data_queue.get()
                    audio_data = np.frombuffer(chunk, dtype=np.int16)
                    # Convert audio_data to float to prevent overflow
                    audio_data = audio_data.astype(np.float32)
                    
                    # Compute simple RMS amplitude
                    rms = np.sqrt(np.mean(audio_data**2))
                    if np.isnan(audio_data).any() or np.isinf(audio_data).any():
                        print("[AudioManager] Warning: audio_data contains NaN or Inf values.")
   
                    # Compute simple RMS amplitude
                    rms = np.sqrt(np.mean(audio_data**2))

                    norm_amp = min(rms / 32767.0, 1.0) * 8  # Normalize to max possible RMS for int16
                    # print("Normalized amplitude: ", norm_amp)
                    # Map amplitude to color or brightness
                    r = int(255 * norm_amp)
                    g = int(255 * (1 - norm_amp))
                    b = 0
    
                    hex_color = '#{:02x}{:02x}{:02x}'.format(r, g, b)
                    brightness = 0.2 + 0.8 * norm_amp  # Adjusted brightness scaling

                    self.action_manager.set_lightbar_direct(r, g, b, brightness)
                    
                    
                    total_talk_time += len(chunk) / self.output_rate
                    should_wake_time = talking_started + total_talk_time
                    sleep_time = should_wake_time - time.monotonic()
                    # print("Visualization Sleeping for: ", sleep_time)
                    await asyncio.sleep(sleep_time)
                chunk = 0
                audio_data = []
                # await asyncio.sleep(0)
            except Exception as e:
                print(f"[AudioManager] Error in visualize_audio: {e}")
                traceback.print_exc()
                await asyncio.sleep(0.1)