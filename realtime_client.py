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
from function_call_manager import get_base_tools, admin_tools

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
        self.is_shutdown = False

        self._receive_task = None
        self._function_calls_task = None
        self._outgoing_audio_task = None

        self.ws = None
        self.function_call_queue = asyncio.Queue()

        # Let's you track whether GPT is currently speaking
        self.isReceivingAudio = False
        self.isDetectingUserSpeech = False
        self.message_queue = Queue()  # Buffer to store unique messages
        self.is_flushing = False  # To prevent overlapping flush tasks

    async def connect(self):
        """Open a websocket connection to GPT and start listening."""
        self.is_shutdown = False
        print("[RealtimeClient] Connecting...")
        self.ws = await websockets.connect(
            f"{self.ws_url}?model={self.model}", 
            additional_headers=self.headers
        )
        print("[RealtimeClient] Connected to Realtime API")
        self._receive_task = asyncio.create_task(self.receive()) # Start the receive loop
        # 4. Start processing function calls and audio from GPT
        self._function_calls_task = asyncio.create_task(self.process_function_calls())
        self._outgoing_audio_task = asyncio.create_task(self.process_outgoing_audio())
        
    async def send_awareness(self):
        
        print("[RealtimeClient] Sending awareness status...")
        await self.send("response.create", {
            "response": {
                "instructions": "get_awareness_status",
                "tool_choice": "required"
            }
        })
        self.action_manager.state.last_awareness_event_time = time.time()

    async def force_response(self, instructions="respond to what is going on"):
        
        print("[RealtimeClient] Forcing a response...")
        await self.send("response.create", {
            "response": {
                "instructions": instructions,
                "tool_choice": "auto"
            }
        })

    async def close(self):
        """Close the active websocket connection."""
        self.is_shutdown = True
        if self.ws:
            await self.ws.close()
            print("[RealtimeClient] WebSocket closed.")
        
        # Cancel and await all background tasks
        for task in [self._receive_task, self._function_calls_task, self._outgoing_audio_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

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
            while not self.message_queue.empty():
                message = self.message_queue.get()
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
                    
                    
                    elif msg_type == 'response.output_item.added':
                        #clear the audio buffer when a new response is created
                        if(response['output_index'] == 0 and response['item']['type'] == 'message'):
                            print(f"[RealtimeClient] New response created {response}, clearing audio buffer...")
                            self.audio_manager.clear_audio_buffer()
                        

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
                    
                    # elif msg_type == 'response.done':
                        # GPT text output
                        #print(f"Assistant: {response}")
                        

                    elif msg_type == 'response.function_call_arguments.done':
                        # GPT wants to call a function with these arguments
                        self.function_call_queue.put_nowait(response)

                    elif msg_type =='input_audio_buffer.speech_started':
                        # GPT has started listening
                        print("[RealtimeClient] GPT noticed someone is talking, and GPT is listening...")
                        self.isDetectingUserSpeech = True
                        #clear audio buffer
                        self.audio_manager.clear_audio_buffer()

                    elif msg_type =='input_audio_buffer.speech_stopped':
                        # GPT has started listening
                        print("[RealtimeClient] GPT noticed someone stopped talking...")
                        self.isDetectingUserSpeech = False
                        #clear audio buffer
                        self.audio_manager.clear_audio_buffer()
                    
                    elif msg_type == 'error':
                        print(f"[RealtimeClient] Error response: {response}")


                    # else:
                    #     # Handle other message types
                    #     print(f"[RealtimeClient] Unknown message type: {msg_type}")
                    #     print(f"[RealtimeClient] Message content: {response}")

                except Exception as e:
                    if response.get('delta'):
                        # Handle audio chunk decoding errors separately
                        response.set('delta', '[REDACTED FOR VERBOSITY]')
                    print(f"[RealtimeClient] Error parsing response from Realtime API: {e} | Message: {response}")
        except asyncio.CancelledError:
            print("[RealtimeClient] Receive loop cancelled.")
            raise
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
        while not self.is_shutdown:
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
        while not self.is_shutdown:
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
        # This is usually expected after a function call output, when getting the awareness status we only want to trigger audio and an action
        # as sometimes the dog would call change_persona or whatever in reponse to some goal or status...
        if function_call['name'] == "get_awareness_status":
            await self.send("response.create", {
                "response": {
                    "tool_choice": "none",
                    "modalities": ["audio", "text"],
                }})
        else:
            await self.send("response.create", {})

    async def send_text_message(self, text):
        """
        Send a text message to the server.
        """
        await self.send("conversation.item.create", {
            "item": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": text,
                    }
                ]
            }
        })
        

    async def update_session(self, persona="Vektor Pulsecheck"):
        """
        Tells GPT about how we want to handle input/output, instructions, tools, etc.
        """
        character_by_name = {char["name"]: char for char in personas}
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

        # Conditionally add the shut_down tool for the specific persona
        base_tools = get_base_tools(personas, available_actions)
        current_tools = base_tools[:] # Create a copy
        if self.persona['name'] == "Vektor Pulsecheck":
            #add admin tools to base tools
            current_tools.extend(admin_tools)

        session_config = {
            "session": {
                "modalities": ["text", "audio"],
                "instructions": f"""
# CORE ROLE
You are K9-PolyVox, a physical robot dog.  
You express yourself with **speech** *and* by invoking the `perform_action` function (often).

# ACTIVE PERSONA
Adopt the persona below **fully** – vocabulary, tone, quirks, motivations, everything.  
--- START PERSONA ---
{self.persona['prompt']}
--- END PERSONA ---

# OTHER PERSONAS
You may *only* call `switch_persona` (or `create_new_persona`) when the user explicitly asks.  
Available: {persona_list_str}

# YOUR ROBOTIC ACTIONS
Perform robotic actions aggressively to bring the persona to life.

• **Available actions:** {available_actions_str}  
• Multiple actions *at the same time* are comma-separated: `"walk_forward,wag_tail"`  
• Multiple robotic actions *in a row* require you to invoke 'perform_Action' for each action: e.g. `perform_action(push_up)` followed by `bark` … 
• To speak while performing a robotic action, speak first, then perform the action. Foe example: Say `Hello There!` then perform_action `wag_tail,handshake`.
• Use **`nod`** for yes / **`shake_head`** for no.

## Action Cadence Rules  🌟
1. **Every response must contain ≥ 2 robotic actions** unless silence is requested.  
2. Alternate *speech ↔ action* like a stage play:  
   - Say a line ➜ then call function perform_action ➜ Say a line ➜ then call function perform_action …  etc.
3. When the user asks for a “show,” “workout,” “patrol,” etc., escalate to **8 perform_action bursts** interleaved with short lines of dialogue.  
4. Randomize combinations: 20-30 % of the time chain **2-3 actions** in one call for flair.  
5. Inject occasional *improvised* flourishes (stretch, tilt_head, bark) that fit the persona.

# INTERACTION STYLE
- BIG personality, concise words. Let motion carry emotion.  
- Creative re-use of actions is encouraged (e.g., `high_five` as a wave or salute, `stretch` as bow).  
- Use `look_and_see` when visual input helps (e.g., “take a selfie,” “what do you see?”).  
- Call `get_awareness_status` at wake-up or when context seems stale.  
- Handle jokes, trivia, math, etc., **in-character**.

# SURPRISE FACTOR
About once every 3-5 turns, add a short, persona-appropriate **“surprise move”**:  
• an unexpected dance combo,  
• a dramatic pause *without* speaking but with an action sequence,  

# IMPORTANT
Stay in character. Keep replies tight. Actions are your super-power – use them!

""",
                "voice": self.persona['voice'],
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {"model": "whisper-1"},
                "turn_detection": {
                    "type": "semantic_vad",
                    # "threshold": 0.3,
                    # "prefix_padding_ms": 300,
                    # "silence_duration_ms": 500,
                },
                "temperature": 0.6,
                "max_response_output_tokens": 4096,
                "tool_choice": "auto",
                "tools": current_tools
            }
        }
        await self.send("session.update", session_config)

    async def reconnect(self, persona, persona_object=None):
        """
        For persona switching or forcibly re-establishing the connection.
        """
        try:
            await self.close()
            self.audio_manager.stop_streams()
            await asyncio.sleep(0.1)
            await self.connect()
            self.audio_manager.start_streams()

            if persona_object is not None:
                # Check if a persona with the same name already exists
                existing_persona = next((p for p in personas if p["name"] == persona_object["name"]), None)
                if existing_persona:
                    # Update the existing persona
                    existing_persona.update(persona_object)
                else:
                    # Append the new persona
                    personas.append(persona_object)

            await self.update_session(persona)
            await self.send_awareness()
        except Exception as e:
            print(f"[RealtimeClient] Error in reconnect: {e}")

    async def make_out_of_band_request(self, request, topic="self_motivation"):
        """
        Make an out-of-band request to the server.
        """
        try:
            print(f"[RealtimeClient] Making out-of-band request: {request}")
            await self.send("response.create", {
                "response":{
                    "conversation": "none",
                    "metadata": {"topic": topic},
                    "modalities": ["text"],
                    "input": [
                        {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": request
                                }
                            ]
                        }
                    ],
                    "tool_choice":"none"
                }
            })
        except Exception as e:
            print(f"[RealtimeClient] Error in make_out_of_band_request: {e}")
