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
        if event_type == "response.create":
            response_payload = message.get("response")
            if response_payload is None:
                response_payload = {}
                message["response"] = response_payload

            # Send immediately if not receiving audio
            if not self.isReceivingAudio:
                asyncio.create_task(self._send_message(message))
                return

            # Deduplicate buffered instructions when provided
            last_buffered = None
            if len(self.message_queue.queue) > 0:
                last_buffered = self.message_queue.queue[-1].get('response', {})
            if (
                last_buffered is not None
                and "instructions" in response_payload
                and "instructions" in last_buffered
                and response_payload["instructions"] == last_buffered["instructions"]
            ):
                print(f"[RealtimeClient] Skipping duplicate message: {message}")
            else:
                print(f"[RealtimeClient] Buffering message: {message}")
                self.message_queue.put(message)

            if not self.is_flushing:
                asyncio.create_task(self._flush_buffer())
        else:
            asyncio.create_task(self._send_message(message))

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
                # message already a dict; previous code attempted json.loads causing errors & dropped messages
                asyncio.create_task(self._send_message(message))
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
                    msg_type = response.get('type')
                    
                    # Unified handling for audio output chunks
                    if msg_type == 'response.output_audio.delta' and response.get('delta'):
                        # Audio chunk (mark start sooner for reduced perceived latency)
                        if not self.isReceivingAudio:
                            self.isReceivingAudio = True
                            # Latency instrumentation: time from last user audio chunk to first model audio
                            if hasattr(self.audio_manager, 'last_user_audio_chunk_time'):
                                gap_ms = (time.time() - self.audio_manager.last_user_audio_chunk_time) * 1000
                                print(f"[LAT] user->first_model_audio: {gap_ms:.1f} ms")
                            # Kick off talking movement once when audio starts
                            if not self.action_manager.isTalkingMovement:
                                asyncio.create_task(self.action_manager.start_talking())
                        audio_chunk = base64.b64decode(response['delta'])
                        self.audio_manager.queue_audio(audio_chunk)
                    
                    elif msg_type in ('response.output_item.added', 'conversation.item.added'):
                        # Clear audio buffer when a new assistant message response starts
                        item = response.get('item', {})
                        # Older response.* events used output_index/item/type structure; keep guard flexible
                        if (response.get('output_index') == 0 and item.get('type') == 'message') or item.get('role') == 'assistant':
                            print(f"[RealtimeClient] New item added {response.get('event_id','?')} - clearing audio buffer...")
                            try:
                                self.audio_manager.clear_audio_buffer()
                            except Exception as e:
                                print(f"[RealtimeClient] Error clearing audio buffer: {e}")

                    elif msg_type in ('response.output_item.done', 'conversation.item.done'):
                        # Placeholder: could finalize any in-progress item assembly
                        pass
                        
                    elif msg_type == 'response.output_audio_transcript.delta':
                        # Partial transcript while GPT is speaking
                        self.isReceivingAudio = True
                        print(response['delta'], end='')
                    elif msg_type == 'response.audio.done':
                        # GPT finished speaking
                        if self.action_manager.isTalkingMovement:
                            asyncio.create_task(self.action_manager.stop_talking())
                        self.isReceivingAudio = False
                        print("\n[RealtimeClient] Audio response completed.")

                    elif msg_type == 'response.output_text.delta' and response.get('delta'):
                        # GPT text output
                        print(f"Assistant: {response['delta']}")
                    
                    # elif msg_type == 'response.done':
                        # GPT text output
                        #print(f"Assistant: {response}")
                        

                    elif msg_type == 'response.function_call_arguments.done':  # unchanged in GA per notes
                        # GPT wants to call a function with these arguments
                        self.function_call_queue.put_nowait(response)

                    elif msg_type =='input_audio_buffer.speech_started':
                        # GPT has started listening
                        print("[RealtimeClient] GPT noticed someone is talking, and GPT is listening...")
                        self.isDetectingUserSpeech = True
                        #clear audio buffer
                        self.audio_manager.clear_audio_buffer()

                    elif msg_type =='input_audio_buffer.speech_stopped':
                        # User finished speaking; do NOT clear incoming audio here.
                        # Clearing now risks dropping early model audio chunks that race in right after VAD end.
                        print("[RealtimeClient] GPT noticed someone stopped talking...")
                        self.isDetectingUserSpeech = False
                    
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

            model_rate = getattr(self.audio_manager, "model_rate", 24000)
            # Calculate the number of bytes corresponding to 10 seconds of audio
            bytes_per_second = model_rate * 1 * 2  # 2 bytes per sample for paInt16
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
                    wf.setframerate(model_rate)
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
                    # Removed auto start_talking here; now tied to first audio chunk to avoid rapid loop
                    pass

            except Exception as e:
                print(f"[RealtimeClient] Error in process_function_calls: {e}")
            # Poll faster to reduce tool call latency
            await asyncio.sleep(0.02)

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
                    "tool_choice": "none"
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

    async def send_image_and_request_response(self, image_path: str):
        """Send an input image (captured locally) to the conversation then request a model response.

        This follows the new realtime API pattern:
          1. conversation.item.create (message with content type 'input_image')
          2. response.create (to have the model respond)
        """
        try:
            with open(image_path, 'rb') as f:
                img_bytes = f.read()
            b64_image = base64.b64encode(img_bytes).decode('utf-8')
            await self.send("conversation.item.create", {
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": f"data:image/jpeg;base64,{b64_image}"
                        }
                    ]
                }
            })
            # Now request a response (no extra instructions so persona/instructions drive behavior)
            await self.send("response.create", {"response": {}})
        except Exception as e:
            print(f"[RealtimeClient] Error sending image: {e}")
        

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

        model_rate = getattr(self.audio_manager, "model_rate", 16000)

        session_config = {
            "session": {
                # Realtime API now requires explicit session.type
                "type": "realtime",
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

# VISION
Use look_and_see to see whatever is in front of where your head is pointing.  To scan an area, turn head up left -> look_and_see -> turn head up forward -> look_and_see -> turn head up right -> look_and_see
To patrol with vision, scan the area and walk in an appropriate direction, then scan the area and walk in an appropriate direction, etc... over and over until you are told to stop.
When asked to roast the person in front of you, turn_head_up -> look_and_see, and then roast them ruthlessly (unless out of character for your persona).
When asked to look left, right, up, down, or center, turn your head in that direction and then look_and_see.

## Action Cadence Rules 
1. When responding, always speak before performing actions and **Every response should contain at least one action** unless silence is requested.  
2. Alternate *speech ↔ action* like a stage play:  
   - Say a line ➜ then call function perform_action ➜ Say a line ➜ then call function perform_action …  etc.
3. When the user asks for a “show,” “workout,” “patrol,” etc., escalate to **8 perform_action bursts** interleaved with short lines of dialogue.  
4. Randomize combinations: 20-30 % of the time chain **2-3 actions** in one call for flair.  
5. Inject occasional *improvised* flourishes (stretch, tilt_head, bark) that fit the persona.

# INTERACTION STYLE
- BIG personality, concise words. Let motion carry emotion.  
- Creative re-use of actions is encouraged (e.g., `high_five` as a wave or salute, `stretch` as bow).  
- Use `look_and_see` when visual input helps (e.g., “look here” “what do you see?” “roast me”).  
- Call `get_awareness_status` at wake-up or when context seems stale.  
- Handle jokes, trivia, math, etc., **in-character**.

# SURPRISE FACTOR
About once every 3-5 turns, add a short, persona-appropriate **“surprise move”**:  
• an unexpected dance combo,  
• a dramatic pause *without* speaking but with an action sequence,  

# IMPORTANT
Stay in character. Keep replies tight. Actions are your super-power – use them!

""",
                "audio": {
                    "output": {
                        "voice": self.persona['voice'],
                        "format": {"type": "audio/pcm", "rate": model_rate}
                    },
                    "input": {
                        "format": {"type": "audio/pcm", "rate": model_rate}
                    }
                },
                # "turn_detection": {
                #     "type": "semantic_vad",
                #     # "threshold": 0.3,
                #     # "prefix_padding_ms": 300,
                #     # "silence_duration_ms": 500,
                # },
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
            # Removed unsupported response.modalities (modalities defined at session level)
            print(f"[RealtimeClient] Error in make_out_of_band_request: {e}")
