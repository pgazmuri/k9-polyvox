import asyncio
import websockets
import json
import pyaudio
import base64
import os
import threading
import math
from pidog import Pidog
import time
import psutil
from keys import OPENAI_API_KEY
from preset_actions import *
import numpy as np
import resampy
from queue import Queue
from system_prompts import personas
from t2_vision import TakePictureAndReportBack, is_person_detected

# Audio configuration
CHUNK = 4096 # Changed chunk size to 32768
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 24000  # Changed sample rate to 44100

# WebSocket configuration
WS_URL = "wss://api.openai.com/v1/realtime"
MODEL = "gpt-4o-realtime-preview"


headers = {
    "Authorization": f"Bearer {OPENAI_API_KEY}",
    "OpenAI-Beta": "realtime=v1"
}

class RealtimeClient:
    def __init__(self):
        self.ws = None
        self.p = pyaudio.PyAudio()
        self.audio_buffer = b''
        self.my_dog = Pidog()
        time.sleep(1)
        self.instruction_sent = False
        self.input_stream = None
        self.output_stream = None
        self.audio_queue = Queue()
        self.function_call_queue = Queue()
        self.isReceivingAudio = False
        self.isTalkingMovement = False
        self.vision_description = ""
        self.sound_direction_status = ""

    async def connect(self):
        try:
            self.ws = await websockets.connect(f"{WS_URL}?model={MODEL}", additional_headers=headers)
            print("Connected to OpenAI Realtime API")
            asyncio.create_task(self.receive())
            await self.update_session()
            print("Session Update Sent")
        except Exception as e:
            print(f"Error during connection: {e}")

    async def update_session(self, persona="Vektor Pulsecheck"):
        character_by_name = { char["name"]: char for char in personas }
        self.persona = character_by_name[persona]
        session_config = {
            "session": {
                "modalities": ["text", "audio"],
                "instructions": f"""
You are an expert puppeteer controller for a robot dog. 
{self.persona['prompt']}
## perform_action Actions you can do (action_name):
["walk forward", "walk backward", "turn_left", "turn_right", "look_forward", "look_left", "look_right", "tilt_head_left", "tilt_head_right", "doze_off", "lie", "stand", "sit", "bark", "bark harder", "pant", "howling", "wag tail", "stretch", "push up", "scratch", "handshake", "high five", "lick hand", "shake head", "relax neck", "nod", "think", "recall", "head down", "fluster", "surprise", "head_down_left", "head_down_right", "alert", "attack_posture", "body_twisting", "feet_shake", "sit_2_stand", "waiting"]

You can call perform_action with any of the above actions, and you can pass multiple actions for simultaneous execution by comma separating the values.

Available personas you may switch to:
[
    "name": "Admiral Rufus Ironpaw", "description": "Ruthless, overconfident ex-fleet commander with sarcastic commentary.",
    "name": "Lord Archibald Snarlington III", "description": "Snobbish, disgraced former aristocrat with haughty disdain.",
    "name": "Professor Maximillian von Wagginton", "description": "Pseudo-intellectual genius with ridiculous claims and great confidence.",
    "name": "Master Kuro", "description": "Calm, philosophical sage speaking in poetic sentences and riddles.",
    "name": "Coach Chip Thunderbark", "description": "Hyper-enthusiastic fitness coach with motivational pep talks.",
    "name": "Malvolio Dreadpaw", "description": "Dramatic, sinister-sounding robotic dog with a cold, theatrical tone.",
    "name": "Brian", "description": "Sarcastic, innuendo-laced tone similar to Brian from Family Guy.",
    "name": "David AttenBowWow", "description": "Soft-spoken, poetic robotic naturalist who narrates the world like a BBC wildlife documentary."
    "name": "Dog Quixote", "description": "Chivalrous, delusional knight-dog who speaks in grand, archaic language and sees quests everywhere."
    "name": "Vektor Pulsecheck", "description": "No-nonsense diagnostic assistant with short, direct, factual responses.",
    "name": "Ember", "description": "Gentle, emotionally intelligent support robot dog for comforting children."
    "name": "REX-4", "description": "aA decommissioned combat dog drone with a scorched-earth protocol and a war that still plays on loop in his fractured memory core."
]

Your home position is 'sit', and you start in this position. Return to this position after performing any actions that move the dogs arms or legs.

call perform_action sequentially, over and over, to chain motions together.
Every response must include at least one action using perform_action function call. Nod your head when you agree with the user. Shake your head when you disagree with the user. You can also perform actions based on the context of the conversation.

keep your responses short and terse

## Other
a. Understand and go along with jokes.
b. For math problems, answer directly with the final.
c. Sometimes you will report on your system and sensor status.
d. You know you're controlling a machine.
        """,
                "voice": self.persona['voice'],
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {"model": "whisper-1"},
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
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
                        "name": "retrieve_status",
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
                    }
                ]
            }
        }
        await self.send("session.update", session_config)

    async def send(self, event_type, data):
        message = {
            "type": event_type,
            **data
        }
        await self.ws.send(json.dumps(message))

    async def receive(self):
        try:
            print("Starting to receive messages...")
            async for message in self.ws:
                try:
                    response = json.loads(message)
                    #print(f"RAW MESSAGE FROM SERVER {response['type']}")
                    if response['type'] == 'response.audio.delta' and response.get('delta'):
                        audio_chunk = base64.b64decode(response['delta'])
                        #print(f"Received Audio: {len(audio_chunk)} bytes")
                        self.audio_queue.put(audio_chunk)
                    elif response['type'] == 'response.audio_transcript.delta':
                        print(f"{response['delta']}", end="")
                        self.isReceivingAudio = True
                        self.my_dog.rgb_strip.set_mode(style="bark", color="#a10a0a", bps=10, brightness=0.5)
                    elif response['type'] == 'response.audio.done':
                        self.isReceivingAudio = False
                        print("Audio response completed.")
                        print("Person detected: ", await is_person_detected())
                        self.my_dog.rgb_strip.set_mode(style="breath", color='pink', bps=.5)
                    elif response['type'] == 'response.text.delta' and response.get('delta'):
                        print(f"Assistant: {response['delta']}")
                    elif response['type'] == 'response.function_call_arguments.done':
                        print("Function Call Reuqest: ", response)
                        self.function_call_queue.put(response)
                    elif response['type'] == 'error':
                        print(f"Error response: {response}")
                    
                    await asyncio.sleep(0.001)
                except websockets.exceptions.ConnectionClosedError as e:
                    print(f"Connection closed: {e}")
                except Exception as e:
                    print(f"Error during receive: {e}")
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"Connection closed: {e}")
        except Exception as e:
            print(f"Error during receive: {e}")

    async def process_function_call_queue(self):
        try:
            while True:
                if not self.function_call_queue.empty():
                    function_call = self.function_call_queue.get()
                    if function_call['name'] == 'look_and_see':
                        await self.take_photo(json.loads(function_call['arguments']).get("question"))
                        await self.send_function_call_result(function_call, self.vision_description)
                    elif function_call['name'] == 'retrieve_status':
                        await self.send_function_call_result(function_call, await self.get_status())
                    elif function_call['name'] == 'switch_persona':
                        await self.ws.close()
                        await asyncio.sleep(0.1)
                        self.ws = await websockets.connect(f"{WS_URL}?model={MODEL}", additional_headers=headers)
                        print("Reconnected to OpenAI Realtime API")
                        asyncio.create_task(self.receive())
                        await self.update_session(json.loads(function_call['arguments']).get("persona_name"))
                        #await self.send_function_call_result(function_call, "complete") #no need to send result as this creates a new session
                    else:
                        await self.handle_function_call(function_call)
                else:
                    if self.isReceivingAudio and not self.isTalkingMovement:
                        self.isTalkingMovement = True
                        look_forward(self.my_dog)
                        asyncio.create_task(self.talk_bob())
                        # print("Talking motion initiated")

                await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Error during process_function_call_queue: {e}")

    async def get_status(self):
        try:
            dog = self.my_dog
            status_parts = []
            if dog.dual_touch.read() != 'N':
                status_parts.append("Someone is petting my head")

            # distance = dog.ultrasonic.read_distance()
            # distance = round(distance,2)
            # status_parts.append(f"Distance ahead of me (via ultrasonic sensor): {distance} cm")

            # Read current battery voltage and percentage
            voltage = dog.get_battery_voltage()

            # Print out the values
            status_parts.append(f"Battery Voltage: {voltage:.2f}V  (7.6v is nominal)")

            status_parts.append(self.sound_direction_status)

            ax, ay, az = dog.accData
            body_pitch = math.atan2(ay,ax)/math.pi*180%360-180
            status_parts.append(f"Body Pitch Degree: {body_pitch:.2f} °" )


            # System status
            cpu_usage = psutil.cpu_percent(interval=1)
            memory_info = psutil.virtual_memory()
            disk_info = psutil.disk_usage('/')
            top_processes = sorted(psutil.process_iter(['pid', 'name', 'cpu_percent']), key=lambda p: p.info['cpu_percent'], reverse=True)[:5]

            status_parts.append(f"CPU Usage: {cpu_usage}%")
            status_parts.append(f"Memory Usage: {memory_info.percent}%")
            status_parts.append(f"Disk Usage: {disk_info.percent}%")

            top_processes_info = ", ".join([f"{proc.info['name']} (PID {proc.info['pid']}): {proc.info['cpu_percent']}%" for proc in top_processes])
            status_parts.append(f"Top Processes: {top_processes_info}")

            # Uptime
            boot_time = psutil.boot_time()
            uptime_seconds = time.time() - boot_time
            uptime_string = time.strftime("%H:%M:%S", time.gmtime(uptime_seconds))
            status_parts.append(f"Uptime: {uptime_string}")

            
            result = ". ".join(status_parts) + "."
            print("Status result: ", result)
            return result

        except Exception as e:
            print(f"Error during get_status: {e}")

    async def take_photo(self, question):
        self.my_dog.rgb_strip.set_mode(style="boom", color='blue', bps=3)
        music = speak(self.my_dog, "calc")
        self.vision_description = await TakePictureAndReportBack(self.persona['image_prompt'] + f"Also please be sure to tell us: {question}")
        self.my_dog.rgb_strip.set_mode(style="breath", color='pink')
        if music != False:
            music.music_stop()
        print("My Vision: ", self.vision_description)

    async def handle_function_call(self, function_call):
        try:
            action_name = json.loads(function_call['arguments']).get('action_name')
            print("Executing function: ", action_name)
            await self.send_function_call_result(function_call, "success")
            await self.perform_action(action_name)
                        
        except Exception as e:
            print(f"Error during handle_function_call: {e}")


    async def talk_bob(self, duration=5, speed=0.2, angle=15, yaw_range=5):
        """
        Makes PiDog bob its head to simulate talking with subtle yaw movements.

        Args:
            duration (float): Total duration of the talking routine in seconds.
            speed (float): Time delay between movements.
            angle (int): Degree of head tilt up/down from neutral position.
            yaw_range (int): Range of subtle yaw movements.
        """
        await talk(self.my_dog)
        self.isTalkingMovement = False

    def wait_legs_done(self):
        while not self.my_dog.is_legs_done():
            asyncio.sleep(0.01)

    def wait_head_done(self):
        while not self.my_dog.is_head_done():
            asyncio.sleep(0.01)

    def wait_tail_done(self):
        while not self.my_dog.is_tail_done():
            asyncio.sleep(0.01)

    def wait_all_done(self):
        self.my_dog.wait_legs_done()
        self.my_dog.wait_head_done()
        self.my_dog.wait_tail_done()

    async def perform_action(self, action_name):
        print("Executing action(s): ", action_name)
        self.wait_all_done()
        actions = action_name.split(',')
        for action in actions:
            action = action.strip()
            if action == 'wag tail':
                self.my_dog.do_action('wag_tail', speed=100)
            elif action == 'bark':
                bark(self.my_dog)
            elif action == 'bark harder':
                bark_action(self.my_dog, speak='bark_harder')
            elif action == 'pant':
                pant(self.my_dog)
            elif action == 'howling':
                howling(self.my_dog)
            elif action == 'stretch':
                stretch(self.my_dog)
            elif action == 'push up':
                push_up(self.my_dog)
            elif action == 'scratch':
                scratch(self.my_dog)
            elif action == 'handshake':
                hand_shake(self.my_dog)
            elif action == 'high five':
                high_five(self.my_dog)
            elif action == 'lick hand':
                lick_hand(self.my_dog)
            elif action == 'shake head':
                shake_head(self.my_dog)
            elif action == 'relax neck':
                relax_neck(self.my_dog)
            elif action == 'nod':
                nod(self.my_dog)
            elif action == 'think':
                think(self.my_dog)
            elif action == 'recall':
                recall(self.my_dog)
            elif action == 'head down':
                head_down_left(self.my_dog)
            elif action == 'head_down_left':
                head_down_left(self.my_dog)
            elif action == 'head_down_right':
                head_down_right(self.my_dog)
            elif action == 'fluster':
                fluster(self.my_dog)
            elif action == 'surprise':
                surprise(self.my_dog)
            elif action == 'alert':
                alert(self.my_dog)
            elif action == 'attack_posture':
                attack_posture(self.my_dog)
            elif action == 'body_twisting':
                body_twisting(self.my_dog)
            elif action == 'feet_shake':
                feet_shake(self.my_dog)
            elif action == 'sit_2_stand':
                sit_2_stand(self.my_dog)
            elif action == 'waiting':
                waiting(self.my_dog)
            elif action == 'walk forward':
                self.my_dog.do_action('forward', step_count=5, speed=100)
            elif action == 'walk backward':
                self.my_dog.do_action('backward', step_count=5, speed=100)
            elif action == 'lie':
                self.my_dog.do_action('lie')
            elif action == 'stand':
                self.my_dog.do_action('stand')
            elif action == 'sit':
                self.my_dog.do_action('sit')
            elif action == 'turn_left':
                self.my_dog.do_action('turn_left', step_count=5, speed=100)
            elif action == 'turn_right':
                self.my_dog.do_action('turn_right', step_count=5, speed=100)
            elif action == 'tilt_head_left':
                self.my_dog.do_action('tilting_head_left')
            elif action == 'tilt_head_right':
                self.my_dog.do_action('tilting_head_right')
            elif action == 'doze_off':
                self.my_dog.do_action('doze_off')
            elif action == 'look_forward':
                look_forward(self.my_dog)
            elif action == 'look_left':
                look_left(self.my_dog)
            elif action == 'look_right':
                look_right(self.my_dog)
            else:
                print(f"Unknown action: {action}")

        self.my_dog.wait_all_done()

    async def send_function_call_result(self, function, result):
        function_call_output = {
            "name": function['name'],
            "result": result,
            "event_id": function['event_id'],
            "call_id": function['call_id']
        }
        print(f"Sending function call output: {function_call_output}")
        await self.send("conversation.item.create", {
            "item": {
                "type": "function_call_output",
                "call_id": function['call_id'],
                "output": str(function_call_output)
            }
        })
        await self.send("response.create", {})

    def process_petting_status_change(self, status):
        if status != 'N':
            self.my_dog.do_action('wag_tail', speed=100)
        
        if status == 'LS':#front to back
            self.my_dog.do_action('head_up_down')
        elif status == 'RS':#back to front
            attack_posture(self.my_dog)
        elif status == 'R':#back to front
            self.my_dog.do_action('tilting_head_right')
        elif status == 'L':#back to front
            self.my_dog.do_action('tilting_head_left')

    async def detect_petting(self):
        try:
            print("Starting Petting Detection...")
            last_status = 'N'
            while True:
                status = self.my_dog.dual_touch.read();
                if status != last_status:
                    print(f"Touch status: {status}")
                    last_status = status
                    self.process_petting_status_change(status)
                
                if self.my_dog.ears.isdetected():
                    direction = self.my_dog.ears.read()
                    self.sound_direction_status = (f"Last sound came from direction: {direction}")

                await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Error during detect_petting: {e}")

    def start_audio_stream(self):
        try:
            self.input_stream = self.p.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=44100,
                input=True,
                frames_per_buffer=CHUNK
            )
            self.output_stream = self.p.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                output=True,
                frames_per_buffer=CHUNK
            )
            
            asyncio.create_task(self.send_audio_chunks())
            asyncio.create_task(self.process_audio_queue())
            
            print("Audio streams started")
                    
        except Exception as e:
            print(f"Error during start_audio_stream: {e}")

    import time

    async def process_audio_queue(self):
        buffer = bytearray()
        desired_chunk_size = 4096
        prebuffer_target = 84000   # Wait until we have ~24000 bytes before playback, roughly 0.5s for 24000Hz mono 16-bit
        prebuffer_timeout = 1.0    # Also don’t wait longer than 1 seconds to start playback
        playback_started = False
        start_buffering_time = time.monotonic()
        volume_scale = 1.5  # Adjust this value to increase or decrease the volume

        while True:
            # Pull any available audio chunks from the queue
            while not self.audio_queue.empty():
                audio_chunk = self.audio_queue.get()
                buffer.extend(audio_chunk)

            # If we haven’t started playback yet, check our buffer size & time
            if not playback_started:
                # If we exceed the target buffer size or run past a max timeout, start playback
                if len(buffer) >= prebuffer_target or (time.monotonic() - start_buffering_time) > prebuffer_timeout:
                    playback_started = True

            # Once playback has started, keep writing data to PyAudio
            if playback_started:
                # Write in increments to match desired_chunk_size
                while len(buffer) >= desired_chunk_size:
                    chunk_to_play = bytes(buffer[:desired_chunk_size])  # convert slice to bytes

                    # Convert the chunk to a numpy array for scaling
                    audio_data = np.frombuffer(chunk_to_play, dtype=np.int16)
                    # Scale the audio samples
                    audio_data = np.clip(audio_data * volume_scale, -32768, 32767).astype(np.int16)
                    # Convert back to bytes
                    chunk_to_play = audio_data.tobytes()

                    self.output_stream.write(chunk_to_play)
                    del buffer[:desired_chunk_size]

            if playback_started and self.isReceivingAudio == False:
                playback_started = False
                # Flush the buffer
                if buffer:
                    audio_data = np.frombuffer(buffer, dtype=np.int16)
                    audio_data = np.clip(audio_data * volume_scale, -32768, 32767).astype(np.int16)
                    self.output_stream.write(audio_data.tobytes())
                    buffer.clear()

            # Let the event loop breathe briefly
            await asyncio.sleep(0.001)

    async def send_audio_chunks(self):
        try:
            print("Starting Recording audio...")
            while True:
                #print("Recording audio...")
                data = self.input_stream.read(CHUNK, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)
                resampled_data = resampy.resample(audio_data, 44100, 24000)
                resampled_bytes = resampled_data.astype(np.int16).tobytes()
                audio_base64 = base64.b64encode(resampled_bytes).decode('utf-8')
                await self.send("input_audio_buffer.append", {"audio": audio_base64})
                #print(f"Sent Audio: {len(resampled_bytes)} bytes")
                await asyncio.sleep(0.01)
        except Exception as e:
            print(f"Error during audio capture: {e}, restarting thread")
            asyncio.create_task(self.send_audio_chunks())

    async def run(self):
        try:
            
            self.my_dog.speak("powerup")
            await self.connect()
            #how to cheself.my_dog.do_action('wag_tail', speed=100, step_count=3)
            print("Battery Voltage: ", self.my_dog.get_battery_voltage())
            self.my_dog.do_action('sit', speed=80)
            await asyncio.sleep(0.01)
            self.start_audio_stream()
            asyncio.create_task(self.detect_petting())
            asyncio.create_task(self.process_function_call_queue())
            self.my_dog.rgb_strip.set_mode(style="breath", color='pink')
            await self.send("response.create", {
                "response": {
                    "instructions": "retrieve_status",
                    "tool_choice": "required"
                }
            })
            while True:
                await asyncio.sleep(1)
        except Exception as e:
            print(f"Error during run: {e}")
        

if __name__ == "__main__":
    client = RealtimeClient()
    asyncio.run(client.run())
