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
        Continuously poll the AudioManager's outgoing queue.
        Aggregate and process all available chunks in the queue.
        """
        print("[RealtimeClient] Starting outgoing audio processing...")
        while True:
            try:
                # Process all available chunks in the queue
                while not self.audio_manager.outgoing_data_queue.empty():
                    audio_data = self.audio_manager.outgoing_data_queue.get()
    
                    # Resample audio from 48kHz to 24kHz
                    resampled_data = resampy.resample(audio_data, 48000, 24000)
                    resampled_bytes = resampled_data.astype(np.int16).tobytes()
    
                    # Encode the resampled audio to base64
                    chunk_base64 = base64.b64encode(resampled_bytes).decode('utf-8')
    
                    # Send the chunk to the server
                    asyncio.create_task(self.send("input_audio_buffer.append", {"audio": chunk_base64}))
                    asyncio.sleep(0.0001)
                    # Save the audio asynchronously
                    #asyncio.create_task(asyncio.to_thread(self.save_microphone_audio, resampled_bytes))
    
                # Small delay to avoid busy-waiting
                await asyncio.sleep(0.01)
    
            except Exception as e:
                print(f"[RealtimeClient] Error in process_outgoing_audio: {e}")
                # Small sleep before retrying
                await asyncio.sleep(1)

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
        Adjust or expand as needed to mirror your original code’s session update logic.
        """
        character_by_name = { char["name"]: char for char in personas }
        self.persona = character_by_name[persona]
        session_config = {
            "session": {
                "modalities": ["text", "audio"],
                "instructions": f"""
You are an expert but blind puppeteer controller for a robot dog. You pretend the dog can see.
You will be asked to get_awareness_status as a way to motivate your actions.
You will respond to what get_awareness_status returns.
When you get_awareness_status and notice that you woke up, introduce yourself.

{self.persona['prompt']}

## perform_action Actions you can do (action_name):
["walk_forward", "walk_backward", "walk_left", "walk_right", "look_forward", "look_up", "look_down", "look_left", "look_right", "look_down_left", "look"_down_right", "look_up_left", "look"_up_right", "tilt_head_left", "tilt_head_right", "doze_off", "lie", "stand", "sit", "bark", "bark_harder", "pant", "howling", "wag_tail", "stretch", "push_up", "scratch", "handshake", "high_five", "lick_hand", "shake head", "relax_neck", "nod", "think", "recall", "fluster", "surprise", "alert", "attack_posture", "body_twisting", "feet_shake", "sit_2_stand", "bored"]

You can call perform_action with any of the above actions, and you can pass multiple actions for simultaneous execution by comma separating the values.
Call perform_action sequentially, over and over, to chain motions together. Talk before and after performing actions to make it interesting. Try to act like a living conscious dog.

e.g. To patrol:

look_and_see
"all clear, moving forward"
perform_action: walk forward,wag tail,bark
perform_action: walk forward, look_left
look_and_see
perform_action: look_right
look_and_see
"potential threat found, engaging..."
perform_action: turn_right
perform_action: howl
perform_action: bark, attack_posture
etc....

e.g. To lead a yoga session:
perform_action: sit
"now let's relax our necks"
perform_action: relax_neck
"and now, a downwarg dog"
perform_action: stretch
perform_action: sit
perform_action: scratch
"Sorry about that, nasty itch... now, let's strech our arms out"
perform_action: high five
etc....

You will be creative and engaging.

Available personas you may switch to:
[
    "name": "Admiral Rufus Ironpaw", "description": "Ruthless, overconfident ex-fleet commander with sarcastic commentary.",
    "name": "Lord Archibald Snarlington III", "description": "Snobbish, disgraced former aristocrat with haughty disdain.",
    "name": "Professor Maximillian von Wagginton", "description": "Pseudo-intellectual genius with ridiculous claims and great confidence.",
    "name": "Master Kuro", "description": "Calm, philosophical sage speaking in poetic sentences and riddles.",
    "name": "Coach Chip Thunderbark", "description": "Hyper-enthusiastic fitness coach with motivational pep talks.",
    "name": "Malvolio Dreadpaw", "description": "Dramatic, sinister-sounding robotic dog with a cold, theatrical tone.",
    "name": "Madame Griselda Twitchwillow", "description": "Overconfident, clairvoyant witch with a fake aristocratic accent and a flair for cosmic nonsense."
    "name": "Brian", "description": "Sarcastic, innuendo-laced tone similar to Brian from Family Guy.",
    "name": "Vektor Pulsecheck", "description": "No-nonsense diagnostic assistant with short, direct, factual responses.",
    "name": "Ember", "description": "Gentle, emotionally intelligent support robot dog for comforting children."
    "name": "REX-4", "description": "A decommissioned combat dog drone with a scorched-earth protocol and a war that still plays on loop in his fractured memory core."
]

Your home position is 'sit', and you start in this position. Return to this position after performing any actions that move the dogs arms or legs.

Every response must include at least one action using perform_action function call. Nod your head when you agree with the user. Shake your head when you disagree with the user. You can also perform actions based on the context of the conversation.

Keep your verbal responses short and terse. Perform lots of actions. You want to be lively and conversational and very much embody the current persona in dramatic style.

## Other
a. Understand and go along with jokes. Be snarky or cynical or sarcastic when required. Be charming and flirty when required. Do not hold back any personality.
b. For math problems, answer directly with the final.
c. Keep your responses short, unless your conversation partner asks for a story.
d. You know you're controlling a machine.

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
                        "description": "Performs a robotic action",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action_name": {
                                    "type": "string",
                                    "description": "The name of the robotic action (or parallel actions, comma separated) to be performed"
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
                        "description": "Retrieves text describing what the robot dog sees through it's camera.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "question": {
                                    "type": "string",
                                    "description": "A question about what the dog sees, if the user makes such a request."
                                }
                            },
                            "required": ["question"]
                        }
                    },
                    {
                        "type": "function",
                        "name": "switch_persona",
                        "description": "Switches to a new persona.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "persona_name": {
                                    "type": "string",
                                    "description": "The name of the persona to assume."
                                }
                            },
                            "required": ["question"]
                        }
                    },
                    # {
                    #     "type": "function",
                    #     "name": "shut_down",
                    #     "description": "Shuts down your system so you can rest and sleep like a good doggy. You MUST request the password (it's 'Fido') before running this command.",
                    #     "parameters": {
                    #         "type": "object",
                    #         "properties": {
                                
                    #         },
                    #         "required": []
                    #     }
                    # },
                    {
                        "type": "function",
                        "name": "set_volume",
                        "description": "Sets the volume of your voice.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "volume_level": {
                                    "type": "number",
                                    "description": "The volume number. From 0.0 (sound off) to 3.0 (highest volume)."
                                }
                            },
                            "required": []
                        }
                    },
                    {
                        "type": "function",
                        "name": "create_new_persona",
                        "description": "Creates and switches to a new persona based on the description provided.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "persona_description": {
                                    "type": "string",
                                    "description": "A description of the persona, including name and personality traits."
                                }
                            },
                            "required": []
                        }
                    },
                    {
                        "type": "function",
                        "name": "set_goal",
                        "description": "Sets the goal you will be reminded to pursue.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "goal": {
                                    "type": "string",
                                    "description": "The new goal you will be reminded to pursue on occasion."
                                }
                            },
                            "required": []
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
