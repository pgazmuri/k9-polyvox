import json
import asyncio
from queue import Queue
import time
import wave
import numpy as np
import pyaudio
import resampy
import websockets
import base64
from system_prompts import personas 

class RealtimeClient:
    """
    Handles the connection to the GPT model: 
    - open/close websockets
    - send requests (session updates, input audio, function call results)
    - receive events from the server
    """

    def __init__(self, 
                 ws_url, 
                 model, 
                 headers,
                 function_call_manager,
                 audio_manager,
                 action_manager):
        self.ws_url = ws_url
        self.model = model
        self.headers = headers

        self.function_call_manager = function_call_manager
        self.audio_manager = audio_manager
        self.action_manager = action_manager

        self.ws = None
        self.function_call_queue = asyncio.Queue()

        # Let's you track whether GPT is currently speaking
        self.isReceivingAudio = False
        self.message_queue = Queue()  # Buffer to store unique messages
        self.is_flushing = False  # To prevent overlapping flush tasks

    async def connect(self):
        """Open a websocket connection to GPT and start listening."""
        print("[RealtimeClient] Connecting...")
        self.ws = await websockets.connect(
            f"{self.ws_url}?model={self.model}", 
            additional_headers=self.headers
        )
        print("[RealtimeClient] Connected to Realtime API")
        asyncio.create_task(self.receive())  # Start receiving in the background
        asyncio.create_task(self.send_awareness())
        
    async def send_awareness(self):
        print("[RealtimeClient] Sending awareness status...")
        asyncio.sleep(0.1)
        await self.send("response.create", {
            "response": {
                "instructions": "get_awareness_status",
                "tool_choice": "required"
            }
        })
        self.action_manager.state.last_awareness_event_time = time.time()

    async def close(self):
        """Close the active websocket connection."""
        if self.ws:
            await self.ws.close()
            print("[RealtimeClient] WebSocket closed.")

    async def send(self, event_type, data):
        """Helper to serialize & send a JSON message to server."""
        message = {"type": event_type}
        message.update(data)
        if not self.isReceivingAudio or event_type != "response.create":
            # Send immediately if not receiving audio
            asyncio.create_task(self._send_message(message))
        else:
            if len(self.message_queue.queue) > 0 and message['response']['instructions'] == self.message_queue.queue[-1]['response']['instructions']:
                print(f"[RealtimeClient] Skipping duplicate message: {message}")
            else:
                print(f"[RealtimeClient] Buffering message: {message}")
                self.message_queue.put(message)

            # Start a flush task if not already running
            if not self.is_flushing:
                asyncio.create_task(self._flush_buffer())

    async def _send_message(self, message):
        """Internal helper to send a message asynchronously."""
        try:
            await self.ws.send(json.dumps(message))
        except Exception as e:
            print(f"[RealtimeClient] Error sending message: {e}")

    async def _flush_buffer(self):
        """Flush the message buffer and send all unique messages."""
        self.is_flushing = True
        try:
            while self.message_buffer:
                message = self.message_buffer.pop()
                print(f"[RealtimeClient] Sending buffered message: {message}")
                asyncio.create_task(self._send_message(json.loads(message)))
                await asyncio.sleep(0.01)  # Small delay to avoid overwhelming the server
        except Exception as e:
            print(f"[RealtimeClient] Error flushing buffer: {e}")
        finally:
            self.is_flushing = False

    async def receive(self):
        """
        Continuously read messages from GPT in a loop,
        handle them or route them to the function_call queue.
        """
        print("[RealtimeClient] Listening for messages...")
        try:
            async for message in self.ws:
                try:
                    response = json.loads(message)
                    msg_type = response['type']
                    
                    if msg_type == 'response.audio.delta' and response.get('delta'):
                        # Audio chunk
                        audio_chunk = base64.b64decode(response['delta'])
                        self.audio_manager.queue_audio(audio_chunk)
                        
                    elif msg_type == 'response.audio_transcript.delta':
                        # Partial transcript while GPT is speaking
                        self.isReceivingAudio = True
                        print(response['delta'], end='')
                    elif msg_type == 'response.audio.done':
                        # GPT finished speaking
                        #await self.action_manager.stop_talking()
                        self.isReceivingAudio = False
                        print("\n[RealtimeClient] Audio response completed.")

                    elif msg_type == 'response.text.delta' and response.get('delta'):
                        # GPT text output
                        print(f"Assistant: {response['delta']}")

                    elif msg_type == 'response.function_call_arguments.done':
                        # GPT wants to call a function with these arguments
                        self.function_call_queue.put_nowait(response)

                    elif msg_type == 'error':
                        print(f"[RealtimeClient] Error response: {response}")

                except Exception as e:
                    print(f"[RealtimeClient] Error parsing message: {e}")
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"[RealtimeClient] Connection closed: {e}")
        except Exception as e:
            print(f"[RealtimeClient] Receive loop exception: {e}")

    def save_microphone_audio(self, resampled_bytes):
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
                with wave.open(f"microphone_{filecount}.wav", "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(24000)
                    wf.writeframes(self._audio_buffer)
                self._last_save_time = time.monotonic()
                filecount = filecount + 1
        except Exception as save_error:
            print(f"[AudioManager] Error saving audio: {save_error}")

    async def process_outgoing_audio(self):
        """
        Continuously process audio data from the AudioManager's outgoing queue.
        Uses proper async await patterns for processing.
        """
        print("[RealtimeClient] Starting outgoing audio processing...")
        while True:
            try:
                # Use await with a timeout to avoid blocking indefinitely
                try:
                    # Try to get an item with a short timeout
                    resampled_bytes = await asyncio.wait_for(
                        self.audio_manager.outgoing_data_queue.get(), 
                        timeout=0.01
                    )
                    
                    # Audio is already resampled in AudioManager, so we just need to encode it
                    # Base64 encode the audio
                    chunk_base64 = await asyncio.to_thread(
                        lambda: base64.b64encode(resampled_bytes).decode('utf-8')
                    )
                    
                    # Send the chunk to the server
                    await self.send("input_audio_buffer.append", {"audio": chunk_base64})
                    
                    # Optional: Indicate task completion
                    self.audio_manager.outgoing_data_queue.task_done()
                    
                    # Optional: Save microphone audio for debugging
                    # self.save_microphone_audio(resampled_bytes)
                    
                except asyncio.TimeoutError:
                    # No data available, just continue the loop
                    pass
                    
                # Yield control back to the event loop
                await asyncio.sleep(0)
            except Exception as e:
                print(f"[RealtimeClient] Error in process_outgoing_audio: {e}")
                await asyncio.sleep(1)  # Wait before retrying after an error

    async def process_function_calls(self):
        """
        Continuously poll function_call_queue for new requests
        and dispatch them via FunctionCallManager.
        """
        while True:
            try:
                if not self.function_call_queue.empty():
                    function_call = await self.function_call_queue.get()
                    result = await self.function_call_manager.handle_function_call(function_call)
                    await self.send_function_call_result(function_call, result)
                else:
                    if self.isReceivingAudio and not self.action_manager.isTalkingMovement:
                        asyncio.create_task(self.action_manager.start_talking())

            except Exception as e:
                print(f"[RealtimeClient] Error in process_function_calls: {e}")
            await asyncio.sleep(0.1)

    async def send_function_call_result(self, function_call, result):
        """
        Format a function_call_output message with the result 
        and send it back to GPT so it knows the function call completed.
        """
        output = {
            "name": function_call['name'],
            "result": result,
            "event_id": function_call['event_id'],
            "call_id": function_call['call_id']
        }
        await self.send("conversation.item.create", {
            "item": {
                "type": "function_call_output",
                "call_id": function_call['call_id'],
                "output": str(output)
            }
        })
        # This is usually expected after a function call output
        await self.send("response.create", {})

    async def update_session(self, persona="Vektor Pulsecheck"):
        """
        Tells GPT about how we want to handle input/output, instructions, tools, etc.
        """
        character_by_name = { char["name"]: char for char in personas }
        self.persona = character_by_name[persona]
        
        # Get available actions from action manager
        available_actions = self.action_manager.get_available_actions()
        
        # Create persona list with descriptions for the prompt
        persona_descriptions = []
        for p in personas:
            persona_descriptions.append(f"- {p['name']}: {p['description']}")
        
        # Pre-format strings to avoid issues with backslashes inside f-string expressions
        persona_list_str = "\n".join(persona_descriptions)
        available_actions_str = json.dumps(available_actions)

        session_config = {
            "session": {
                "modalities": ["text", "audio"],
                "instructions": f"""
# Your Core Role:
You ARE the personality and controller for a robot dog. You interact with the world through speech and robotic actions.

# Current Persona:
Embody the persona detailed below. Follow its personality, speaking style, and motivations closely in all responses and actions.
--- START PERSONA ---
{self.persona['prompt']}
--- END PERSONA ---

# Available Personas:
The following personas are available for switching via the `switch_persona` function:
{persona_list_str}

# Actions are Key:
- Use the `perform_action` function frequently to make the robot dog move, express itself, and interact physically. This is crucial for bringing the persona to life.
- Available actions: {available_actions_str}
- You can combine actions with commas (e.g., 'walk_forward,wag_tail').
- Aim to include relevant actions in most of your responses. Talk before and after actions to make interactions feel natural.
- Use 'nod' and 'shake_head' actions to show agreement or disagreement.
- Your default/home position is 'sit'. Try to return to 'sit' after complex movements unless actively doing something else.

# Interaction Style:
- Keep spoken responses relatively concise, but engaging and in character. Let your actions do a lot of the talking.
- Use `look_and_see` to get visual information when needed, interpreting the results according to your persona.
- Use `get_awareness_status` periodically or when prompted to understand recent events or your current goal. If you just woke up, introduce yourself based on your persona.
- Handle jokes, math, and other requests appropriately for your persona.

# Other Functions:
- Use `get_system_status`, `switch_persona`, `create_new_persona`, `set_goal`, and `set_volume` as needed, following their descriptions.
""",
                "voice": self.persona['voice'],
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {"model": "whisper-1"},
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.3,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 500,
                },
                "temperature": 0.6,
                "max_response_output_tokens": 4096,
                "tool_choice": "auto",
                "tools": [
                    {
                        "type": "function",
                        "name": "perform_action",
                        "description": "Performs one or more robotic actions simultaneously (comma-separated). Essential for expressing the persona physically.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action_name": {
                                    "type": "string",
                                    "description": f"The name of the action(s) to perform. Available actions: {', '.join(available_actions)}"
                                }
                            },
                            "required": ["action_name"]
                        }
                    },
                    {
                        "type": "function",
                        "name": "get_system_status",
                        "description": "Retrieves sensor and system status, including body pitch, battery voltage, cpu utilization, last sound direction and more.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                
                            },
                            "required": []
                        }
                    },
                    {
                        "type": "function",
                        "name": "get_awareness_status",
                        "description": "Retrieves text telling you what the robot dog just noticed.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                
                            },
                            "required": []
                        }
                    },
                    {
                        "type": "function",
                        "name": "look_and_see",
                        "description": "Retrieves text describing what the robot dog sees through its camera.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "question": {
                                    "type": "string",
                                    "description": "A question about what the dog sees, if the user makes such a request."
                                }
                            },
                            "required": [] 
                        }
                    },
                    {
                        "type": "function",
                        "name": "switch_persona",
                        "description": "Switches the robot's personality to one of the available personas listed in the instructions.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "persona_name": {
                                    "type": "string",
                                    "description": f"The exact name of the persona to switch to. Options: {', '.join([p['name'] for p in personas])}"
                                }
                            },
                            "required": ["persona_name"]
                        }
                    },
                    {
                        "type": "function",
                        "name": "set_volume",
                        "description": "Sets the speech volume.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "volume_level": {
                                    "type": "number",
                                    "description": "The volume number. From 0.0 (sound off) to 3.0 (highest volume)."
                                }
                            },
                            "required": ["volume_level"]
                        }
                    },
                    {
                        "type": "function",
                        "name": "create_new_persona",
                        "description": "Generates and switches to a new persona based on the description provided.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "persona_description": {
                                    "type": "string",
                                    "description": "A description of the persona, including name and personality traits."
                                }
                            },
                            "required": ["persona_description"]
                        }
                    },
                    {
                        "type": "function",
                        "name": "set_goal",
                        "description": "Sets a new goal or motivation that you will be reminded to pursue.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "goal": {
                                    "type": "string",
                                    "description": "The new goal you will be reminded to pursue on occasion."
                                }
                            },
                            "required": ["goal"]
                        }
                    }
                ]
            }
        }
        await self.send("session.update", session_config)

    async def reconnect(self, persona, persona_object = None):
        """
        For persona switching or forcibly re-establishing the connection.
        """
        await self.close()
        await asyncio.sleep(0.1)
        await self.connect()
        if(persona_object is not None):
            personas.append(persona_object)
        await self.update_session(persona)
