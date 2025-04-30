import math
import time
import psutil
import asyncio
import random
import os
from state_manager import RobotDogState

# External dependencies
from pidog import Pidog
from robot_hat import Ultrasonic

# Conditionally import actions based on environment variable
if os.environ.get("USE_MOCK_ACTIONS") == "1":
    print("[ActionManager] Using MOCK preset actions.")
    from mock_preset_actions import *
else:
    print("[ActionManager] Using REAL preset actions.")
    from preset_actions import *

from t2_vision import TakePictureAndReportBack, is_person_detected, close_camera
from persona_generator import generate_persona

from display_manager import display_message, display_status

class ActionManager:
    """
    Manages all PiDog-specific actions and sensor interactions.
    """

    def __init__(self):
        display_message("Status", "Booting PiDog...")
        #if env DISABLE_PIDOG_SPEAKER is set, use the patch
        if os.environ.get("DISABLE_PIDOG_SPEAKER") == "1":
            print("DISABLE_PIDOG_SPEAKER is set, using patch for speaker.")
            from unittest.mock import patch
            from unittest.mock import MagicMock
            # Mock the enable_speaker function to do nothing
            noop = MagicMock()
            with patch("robot_hat.music.enable_speaker", new=noop):
                self.my_dog = Pidog()
        else:
            self.my_dog = Pidog()
        print("PiDog Initiated...")
        
        display_message("Status", "PiDog Loaded...")
        time.sleep(1)  # small delay for hardware init
        self.reset_state_for_new_persona()

    def close(self):
        close_camera()
        self.perform_action('lie')
        self.my_dog.close()
        try:
            self.my_dog.sensory_process.stop()
            sleep(.5)  # Wait for the process to stop
        except Exception as e:
            print(f"[ActionManager] Error stopping sensory process: {e}")

    async def speak_async(self, filename):
        """
        Asynchronously plays a sound file.
        """
        if filename:
            self.isPlayingSound = True
            # Offload the blocking speak_block call to a thread
            await asyncio.to_thread(self.my_dog.speak_block, filename)
            print(f"[ActionManager] Finished playing sound: {filename}")
            self.isPlayingSound = False

    
    def speak(self, name, volume=100):
        """
        speak, play audio

        :param name: the file name int the folder(SOUND_DIR)
        :type name: str
        :param volume: volume, 0-100
        :type volume: int
        """
        print(f"looking for {SOUND_DIR+name+'.mp3'}")
        status, _ = utils.run_command('sudo killall pulseaudio') # Solve the problem that there is no sound when running in the vnc environment

        if os.path.isfile(name):
            self.my_dog.music.music_play(name, volume)
        elif os.path.isfile(LOCAL_SOUND_DIR+name):
            self.my_dog.music.music_play(LOCAL_SOUND_DIR+name, volume)
        elif os.path.isfile(LOCAL_SOUND_DIR+name+'.mp3'):
            self.my_dog.music.music_play(LOCAL_SOUND_DIR+name+'.mp3', volume)
        elif os.path.isfile(LOCAL_SOUND_DIR+name+'.wav'):
            self.my_dog.music.music_play(LOCAL_SOUND_DIR+name+'.wav', volume)
        elif os.path.isfile(SOUND_DIR+name+'.mp3'):
            self.my_dog.music.music_play(SOUND_DIR+name+'.mp3', volume)
        elif os.path.isfile(SOUND_DIR+name+'.wav'):
            self.my_dog.music.music_play(SOUND_DIR+name+'.wav', volume)
        else:
            return False
        return self.my_dog.music

    async def initialize_posture(self):
        """Sets an initial posture after power up."""
        print("[ActionManager] Initializing posture...")
        powerup_lightbar_task = asyncio.create_task(self.power_up_sequence())
        self.isPlayingSound = True
        music = self.speak("powerup")
        await self.perform_action('sit,look_forward')
        await powerup_lightbar_task  # Wait for the power-up sequence to finish
        music.music_stop()
        self.isPlayingSound = False
        self.lightbar_breath()
    
    def reset_state_for_new_persona(self):
        self.sound_direction_status = ""
        self.vision_description = ""
        self.isTalkingMovement = False
        self.isPlayingSound = False
        self.isTakingAction = False
        self.state = RobotDogState()
        self.last_change_time = 0  # Track the last time a change was noticed
        self.last_reminder_time = time.time()  # Track the last time we reminded of the default goal

    def detect_sound_direction(self):
        """Reads the dog's ear sensors to find out from which direction the sound came."""
        if self.my_dog.ears.isdetected():
            direction = self.my_dog.ears.read()

            # Classify the direction based on the angle
            if 337.5 <= direction <= 360 or 0 <= direction < 22.5:
                classified_direction = "front"
            elif 22.5 <= direction < 67.5:
                classified_direction = "front right"
            elif 67.5 <= direction < 112.5:
                classified_direction = "right"
            elif 112.5 <= direction < 157.5:
                classified_direction = "back right"
            elif 157.5 <= direction < 202.5:
                classified_direction = "back"
            elif 202.5 <= direction < 247.5:
                classified_direction = "back left"
            elif 247.5 <= direction < 292.5:
                classified_direction = "left"
            elif 292.5 <= direction < 337.5:
                classified_direction = "front left"
            else:
                classified_direction = "unknown"

            # print(f"[ActionManager] Last sound came from direction: {classified_direction} (angle: {direction}°)")
            # self.state.last_sound_direction = classified_direction
            return classified_direction

    def detect_petting_change(self):
        current_status = self.my_dog.dual_touch.read()
        # print(f"[DEBUG] Current petting status: {current_status}")
        
        self.process_petting_status_change(current_status)
        detected = current_status != 'N'
        # print(f"[DEBUG] Petting detected: {detected}")
        
        retVal = False
        if detected:
            if not self.state.petting_detected_at:
                # print("[DEBUG] First petting detected.")
                retVal = True
            elif self.state.petting_detected_at and time.time() - self.state.petting_detected_at > 10:
                # print("[DEBUG] Petting detected after 10 seconds.")
                retVal = True
            self.state.petting_detected_at = time.time()
            # print(f"[DEBUG] Updated petting_detected_at: {self.state.petting_detected_at}")
        else:
            if self.state.petting_detected_at and time.time() - self.state.petting_detected_at < 10:
                # print("[DEBUG] No petting detected for over 10 seconds.")
                retVal = True
        
        # print(f"[DEBUG] Returning value: {retVal}")
        return retVal

    def detect_sound_direction_change(self):
        """
        Detects if the last sound direction has changed.
        Returns True if the direction has changed, otherwise False.
        """
        if self.my_dog.ears.isdetected():
            current_direction = self.detect_sound_direction()
            # print(f"[DEBUG] Current sound direction: {current_direction}")
            # print(f"[DEBUG] Last sound direction: {self.state.last_sound_direction}")
            if self.state.last_sound_direction != current_direction:
                self.state.last_sound_direction = current_direction
                #print(f"[DEBUG] Sound direction change detected: {current_direction}")
                return True
        return False

    async def detect_face_change(self):
        """Detects if a face is in front of the dog."""
        detected = await is_person_detected()
        # print(f"[DEBUG] Face detected: {detected}")
        retVal = False  # Ensure consistent variable naming
    
        if detected:
            if not self.state.face_detected_at:
                # print("[DEBUG] First face detected.")
                retVal = True
            elif self.state.face_detected_at and time.time() - self.state.face_detected_at > 10:
                # print("[DEBUG] Face detected after 10 seconds.")
                retVal = True
            self.state.face_detected_at = time.time()
            # print(f"[DEBUG] Updated face_detected_at: {self.state.face_detected_at}")
        else:
            if self.state.face_detected_at and time.time() - self.state.face_detected_at < 10:
                # print("[DEBUG] No face detected for over 10 seconds.")
                retVal = True
    
        if retVal:
            print(f"[DEBUG] Face change detected: {detected}, last face seen at: {self.state.face_detected_at}")
    
        # print(f"[DEBUG] Returning value: {retVal}")
        return retVal
    

    def detect_orientation_change(self):
        """Detects if the dog has been moved."""
        #check state.last_orientation_description comared to get_orientation_description
        desc = self.get_orientation_description()
        if self.state.last_orientation_description == None:
            self.state.last_orientation_description = desc
            return False
        if desc != self.state.last_orientation_description:
            self.state.last_orientation_description = desc
            print(f"[DEBUG] Orientation change detected: {desc}")
            return True
        return False
        

    def get_orientation_description(self):
        """
        Provides a string describing the dog's orientation based on pitch and roll.
        """
        # Body pitch, roll, and yaw from IMU
        ax, ay, az = self.my_dog.accData  # Accelerometer data
        
        # Calculate pitch and roll from accelerometer
        body_pitch = math.atan2(ay, math.sqrt(ax**2 + az**2)) * 180 / math.pi
        body_roll = math.atan2(-ax, az) * 180 / math.pi

        # Determine orientation based on pitch and roll
        if body_roll <= -80:
            return "You are upside down!"
        elif -40 <= body_pitch <= 15:
            if 65 <= body_roll <= 105:
                return "You are upright."
            elif 155 <= abs(body_roll) <= 190:
                return "You are on your left side!" if body_roll > 0 else "You are on your right side!"
        elif body_pitch >= 75:
            return "You are hanging by your tail!"
        elif body_pitch <= -75:
            return "You are hanging by your nose!"

        return "The dog's orientation is unclear."


    def process_petting_status_change(self, status):
        """
        Called when a new 'touch' status is detected.
        This method chooses which action to perform based on the new status.
        """
        if status != 'N':
            wag_tail(self.my_dog)
        
        if status == 'LS':   # front to back
            head_up_down(self.my_dog)
        elif status == 'RS': # back to front
            attack_posture(self.my_dog)
        elif status == 'R':
            tilt_head_right(self.my_dog)
        elif status == 'L':
            tilt_head_left(self.my_dog)

    def get_status(self):
        """
        Gathers info about battery, pitch, CPU usage, memory usage,
        disk usage, top processes, uptime, and the last sound direction.
        Returns them as a formatted string.
        """
        status_parts = []

        # Goal
        status_parts.append(f"Current Goal: {self.state.goal}")

        # Petting Status
        if self.my_dog.dual_touch.read() != 'N':
            status_parts.append("Someone is petting my head RIGHT NOW!")
        elif self.state.petting_detected_at and time.time() - self.state.petting_detected_at < 10:
            status_parts.append("Someone petted my head recently!")

        # Face Detection Status (from state)
        person_detected_recently = self.state.face_detected_at and (time.time() - self.state.face_detected_at < 10)
        if person_detected_recently:
             # We can refine this further if needed, e.g., differentiate between "right now" vs "recently"
             # For now, just indicate recent detection based on state.
            status_parts.append("A person was detected recently!")
        else:
            status_parts.append("No person detected recently.")


        # Report on posture and head position from state
        status_parts.append(f"Posture: {self.state.posture}")
        status_parts.append(f"Head Position: {self.state.head_position}")

        # Battery voltage
        voltage = self.my_dog.get_battery_voltage()
        status_parts.append(f"Battery Voltage: {voltage:.2f}V (7.6 is nominal)")

        # Body pitch, roll, and yaw from IMU
        ax, ay, az = self.my_dog.accData  # Accelerometer data
        gx, gy, gz = self.my_dog.gyroData  # Gyroscope data

        # Calculate pitch and roll from accelerometer
        body_pitch = math.atan2(ay, math.sqrt(ax**2 + az**2)) * 180 / math.pi
        body_roll = math.atan2(-ax, az) * 180 / math.pi

        # Yaw requires integration of gyroscope data over time
        dt = 0.01  # Example time delta in seconds (adjust based on your loop timing)
        if not hasattr(self, 'yaw_angle'):
            self.yaw_angle = 0.0  # Initialize yaw angle if not already set
        self.yaw_angle += gz * dt  # Integrate gyroscope Z-axis data for yaw
        body_yaw = self.yaw_angle

        # Append IMU status to status_parts
        status_parts.append(f"Body Pitch: {body_pitch:.2f}°")
        status_parts.append(f"Body Roll: {body_roll:.2f}°")
        status_parts.append(f"Body Yaw: {body_yaw:.2f}°")

        # Report orientation from state
        orientation_desc = self.state.last_orientation_description if self.state.last_orientation_description else self.get_orientation_description() # Fallback if state is None
        status_parts.append(f"Your orientation: {orientation_desc}")

        # Gyroscope angular velocity
        status_parts.append(f"Gyro Angular Velocity: gx={gx:.2f}, gy={gy:.2f}, gz={gz:.2f}")

        # Distance Sensor
        try:
            distance = self.my_dog.distance
            distance = round(distance, 2)
            status_parts.append(f"Space in front of you: {distance} cm (ultrasonic distance)")
        except AttributeError:
            status_parts.append("Ultrasonic sensor is not functional or not initialized.")
        except Exception as e:
            status_parts.append(f"Error reading ultrasonic sensor: {str(e)}")

        # Sound direction from state
        status_parts.append(f"Last Sound Direction: {self.state.last_sound_direction if self.state.last_sound_direction else 'None detected yet'}")

        # System status
        cpu_usage = psutil.cpu_percent(interval=1)
        memory_info = psutil.virtual_memory()
        disk_info = psutil.disk_usage('/')
        top_processes = sorted(
            psutil.process_iter(['pid', 'name', 'cpu_percent']),
            key=lambda p: p.info['cpu_percent'],
            reverse=True
        )[:5]

        status_parts.append(f"CPU Usage: {cpu_usage}%")
        status_parts.append(f"Memory Usage: {memory_info.percent}%")
        status_parts.append(f"Disk Usage: {disk_info.percent}%")

        top_procs_info = ", ".join(
            [f"{proc.info['name']} (PID {proc.info['pid']}): {proc.info['cpu_percent']}%"
             for proc in top_processes]
        )
        status_parts.append(f"Top Processes: {top_procs_info}")

        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        uptime_string = time.strftime("%H:%M:%S", time.gmtime(uptime_seconds))
        status_parts.append(f"Uptime: {uptime_string}")

        return ". ".join(status_parts) + "."

    def get_simple_status(self):
        """
        Gathers basic info about the robot's state, including posture, head position,
        last sound direction, and time since last face or pet detection.
        Returns them as a formatted string.
        """
        status_parts = []

        # Goal
        status_parts.append(f"Current Goal: {self.state.goal}")

        # Petting Status
        if self.my_dog.dual_touch.read() != 'N':
            status_parts.append("Someone is petting my head RIGHT NOW!")
        elif self.state.petting_detected_at:
            time_since_petting = time.time() - self.state.petting_detected_at
            status_parts.append(f"Last petting was {time_since_petting:.1f} seconds ago.")
        else:
            status_parts.append("No petting detected yet.")

        # Face Detection Status
        if self.state.face_detected_at:
            time_since_face = time.time() - self.state.face_detected_at
            status_parts.append(f"Last face detected {time_since_face:.1f} seconds ago.")
        else:
            status_parts.append("No face detected yet.")

        # Posture and Head Position
        status_parts.append(f"Posture: {self.state.posture}")
        status_parts.append(f"Head Position: {self.state.head_position}")

        # Last Sound Direction
        last_sound = self.state.last_sound_direction if self.state.last_sound_direction else "None detected yet"
        status_parts.append(f"Last Sound Direction: {last_sound}")

        return "\n".join(status_parts)

    async def take_photo(self, persona, question="", silent=False):
        """
        Asks PiDog to flash a certain LED style, then triggers the camera routine
        and calls `TakePictureAndReportBack` with the prompt. Then reverts LED style.
        """
        self.isTakingAction = True
        try:
            # optionally play a "camera shutter" or "beep" sound
            if not silent: 
                self.lightbar_boom()
                self.isPlayingSound = True
                music = self.speak("calc")
            self.vision_description = await TakePictureAndReportBack(
                persona['image_prompt'] + f" {question}"
            )
        #add error handling
        except Exception as e:
            print(f"[ActionManager] Error taking photo: {e}")
            self.vision_description = "Error taking photo."
        finally:
            if not silent: 
                self.lightbar_breath()
                music.music_stop()
                self.isPlayingSound = False
                self.isTakingAction = False
        
        print("[ActionManager] Vision result: ", self.vision_description)
        return self.vision_description

    async def perform_action(self, action_name):
        """
        Executes one or more PiDog actions by name. 
        If multiple actions are comma-separated, executes them sequentially.
        """
        print(f"[ActionManager] Performing action(s): {action_name}")
        self.isTakingAction = True
        actions = [a.strip() for a in action_name.split(',')]

        for action in actions:
            if action == 'wag_tail':
                wag_tail(self.my_dog, step_count=5, speed=100)
            elif action == 'bark':
                bark(self.my_dog)
            elif action == 'bark_harder':
                bark_action(self.my_dog, speak='single_bark_2')
                self.state.posture = "standing"
                await self.reset_head()
            elif action == 'pant':
                pant(self.my_dog)
            elif action == 'howling':
                howling(self.my_dog)
                self.state.posture = "sitting"
                await self.reset_head()
            elif action == 'stretch':
                stretch(self.my_dog)
                self.state.posture = "sitting"
                await self.reset_head()
            elif action == 'push_up':
                push_up(self.my_dog)
                self.state.posture = "standing"
                await self.reset_head()
            elif action == 'scratch':
                if self.state.posture == "standing":
                    sit_down(self.my_dog)
                scratch(self.my_dog)
                self.state.posture = "sitting"
                await self.reset_head()
            elif action == 'handshake':
                if self.state.posture == "standing":
                    sit_down(self.my_dog)
                hand_shake(self.my_dog)
                self.state.posture = "sitting"
                await self.reset_head()
            elif action == 'high_five':
                if self.state.posture == "standing":
                    sit_down(self.my_dog)
                high_five(self.my_dog)
                self.state.posture = "sitting"
                await self.reset_head()
            elif action == 'lick_hand':
                if self.state.posture == "standing":
                    sit_down(self.my_dog)
                lick_hand(self.my_dog)
                self.state.posture = "sitting"
                await self.reset_head()
            elif action == 'shake_head':
                shake_head(self.my_dog)
            elif action == 'relax_neck':
                relax_neck(self.my_dog)
            elif action == 'nod':
                nod(self.my_dog)
            elif action == 'think':
                think(self.my_dog)
            elif action == 'recall':
                recall(self.my_dog)
            elif action == 'look_down':
                look_down(self.my_dog, pitch_comp=-30 if self.state.posture == "sitting" else 0)
                self.state.head_position = "down"
            elif action == 'look_up':
                look_up(self.my_dog, pitch_comp=-30 if self.state.posture == "sitting" else 0)
                self.state.head_position = "up"
            elif action == 'look_down_left':
                head_down_left(self.my_dog, pitch_comp=-30 if self.state.posture == "sitting" else 0)
                self.state.head_position = "down left"
            elif action == 'look_down_right':
                head_down_right(self.my_dog, pitch_comp=-30 if self.state.posture == "sitting" else 0)
                self.state.head_position = "down right"
            elif action == 'look_up_left':
                head_up_left(self.my_dog, pitch_comp=-30 if self.state.posture == "sitting" else 0)
                self.state.head_position = "up left"
            elif action == 'look_up_right':
                head_up_right(self.my_dog, pitch_comp=-30 if self.state.posture == "sitting" else 0)
                self.state.head_position = "up right"
            elif action == 'look_forward':
                look_forward(self.my_dog, pitch_comp=-30 if self.state.posture == "sitting" else 0)
                self.state.head_position = "forward"
            elif action == 'look_left':
                look_left(self.my_dog, pitch_comp=-30 if self.state.posture == "sitting" else 0)
                self.state.head_position = "left"
            elif action == 'look_right':
                look_right(self.my_dog, pitch_comp=-30 if self.state.posture == "sitting" else 0)
                self.state.head_position = "right"
            elif action == 'fluster':
                fluster(self.my_dog)
            elif action == 'surprise':
                surprise(self.my_dog)
                self.state.posture = "sitting"
                await self.reset_head()
            elif action == 'alert':
                alert(self.my_dog)
                self.state.posture = "sitting"
                await self.reset_head()
            elif action == 'attack_posture':
                attack_posture(self.my_dog)
                self.state.posture = "standing"
                await self.reset_head()
            elif action == 'body_twisting':
                body_twisting(self.my_dog)
            elif action == 'feet_shake':
                feet_shake(self.my_dog)
            elif action == 'sit_2_stand':
                sit_2_stand(self.my_dog)
                self.state.posture = "sitting"
                await self.reset_head()
            elif action == 'bored':
                waiting(self.my_dog)
            elif action == 'walk_forward':
                if self.state.posture == "sitting":
                    sit_2_stand(self.my_dog)
                walk_forward(self.my_dog, step_count=5, speed=100)
                self.state.posture = "standing"
                await self.reset_head()
            elif action == 'walk_backward':
                if self.state.posture == "sitting":
                    sit_2_stand(self.my_dog)
                walk_backward(self.my_dog, step_count=5, speed=100)
                self.state.posture = "standing"
                await self.reset_head()
            elif action == 'lie':
                lie_down(self.my_dog)
                self.state.posture = "standing"
                await self.reset_head()
            elif action == 'stand':
                if self.state.posture == "sitting":
                    sit_2_stand(self.my_dog)
                else:
                    stand_up(self.my_dog)
                self.state.posture = "standing"
                await self.reset_head()
            elif action == 'sit':
                sit_down(self.my_dog)
                self.state.posture = "sitting"
                await self.reset_head()
            elif action == 'walk_left':
                if self.state.posture == "sitting":
                    sit_2_stand(self.my_dog)
                turn_left(self.my_dog, step_count=5, speed=100)
                self.state.posture = "standing"
                await self.reset_head()
            elif action == 'walk_right':
                if self.state.posture == "sitting":
                    sit_2_stand(self.my_dog)
                turn_right(self.my_dog, step_count=5, speed=100)
                self.state.posture = "standing"
                await self.reset_head()
            elif action == 'tilt_head_left':
                tilt_head_left(self.my_dog)
            elif action == 'tilt_head_right':
                tilt_head_right(self.my_dog)
            elif action == 'doze_off':
                doze_off(self.my_dog, speed=100)
                self.state.posture = "standing"
                await self.reset_head()
            else:
                print(f"[ActionManager] Unknown action: {action}")
            
        self.my_dog.wait_all_done()
        self.isTakingAction = False
        print("[ActionManager] Done performing actions.")

    def lightbar_breath(self):
        self.my_dog.rgb_strip.set_mode(style="breath", color='pink', bps=0.5)

    #async function for power_up_sequence that calls lightbar_power_up with progressively increasing brightness and Red->Orange->Yellow->White smooth color progression
    async def power_up_sequence(self):
        total_steps = 40  # 4 seconds with 0.1 sleep
        red = (255, 0, 0)
        orange = (255, 165, 0)
        yellow = (255, 255, 0)
        white = (255, 255, 255)

        # Define transition points (adjust steps per transition if needed)
        red_to_orange_steps = 13
        orange_to_yellow_steps = 13
        yellow_to_white_steps = total_steps - red_to_orange_steps - orange_to_yellow_steps # 14 steps

        for i in range(1, total_steps + 1):
            brightness = i / total_steps
            r, g, b = 0, 0, 0

            if i <= red_to_orange_steps:
                # Transition Red to Orange
                progress = i / red_to_orange_steps
                r = int(red[0] + (orange[0] - red[0]) * progress)
                g = int(red[1] + (orange[1] - red[1]) * progress)
                b = int(red[2] + (orange[2] - red[2]) * progress)
            elif i <= red_to_orange_steps + orange_to_yellow_steps:
                # Transition Orange to Yellow
                progress = (i - red_to_orange_steps) / orange_to_yellow_steps
                r = int(orange[0] + (yellow[0] - orange[0]) * progress)
                g = int(orange[1] + (yellow[1] - orange[1]) * progress)
                b = int(orange[2] + (yellow[2] - orange[2]) * progress)
            else:
                # Transition Yellow to White
                progress = (i - red_to_orange_steps - orange_to_yellow_steps) / yellow_to_white_steps
                r = int(yellow[0] + (white[0] - yellow[0]) * progress)
                g = int(yellow[1] + (white[1] - yellow[1]) * progress)
                b = int(yellow[2] + (white[2] - yellow[2]) * progress)

            # Ensure colors are within valid range
            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))

            self.set_lightbar_direct(r, g, b, brightness=brightness)
            await asyncio.sleep(0.1) # 40 steps * 0.1s = 4 seconds

        # Optional: Set a final state after the sequence
        self.my_dog.rgb_strip.set_mode(style="breath", color='pink', bps=0.5) # Changed bps from 15 to 0.5 for a calmer breath

    def lightbar_boom(self, color='blue'):
        self.my_dog.rgb_strip.set_mode(style="boom", color=color, bps=3)

    def lightbar_bark(self):
        self.my_dog.rgb_strip.set_mode(style="bark", color="#a10a0a", bps=10, brightness=0.5)

    def set_lightbar_mode(self, style: str, color: str = "#ffffff", bps: float = 1.0, brightness: float = 1.0):
        """
        Generic call to set lightbar style, color, blink/beat frequency, brightness, etc.
        style can be something like "breath", "boom", "blink", "bark", etc.
        """
        print(f"[ActionManager] Setting lightbar mode: style={style}, color={color}, bps={bps}, brightness={brightness}")
        self.my_dog.rgb_strip.set_mode(style=style, color=color, bps=bps, brightness=brightness)

    def set_lightbar_direct(self, r: int, g: int, b: int, brightness: float = 1.0):
        """
        Directly sets the lightbar color and brightness without any special effects.
        """
        r_scaled = min(int(r * brightness), 255)
        g_scaled = min(int(g * brightness), 255)
        b_scaled = min(int(b * brightness), 255)
        # color = "#{:02x}{:02x}{:02x}".format(r_scaled, g_scaled, b_scaled)
        # print(f"[ActionManager] Setting lightbar color: {color}, brightness={brightness}")
        self.my_dog.rgb_strip.style = None
        lights = [[r_scaled, g_scaled, b_scaled]]*self.my_dog.rgb_strip.light_num

        self.my_dog.rgb_strip.display(self.adjust_lights_based_on_brightness(lights, r_scaled, g_scaled, b_scaled, brightness))


    def adjust_lights_based_on_brightness(self, lights, r, g, b, brightness):
        """
        Adjusts the lights array based on the brightness value.
        - When brightness is 0, only the middle LED (index 5) is lit.
        - When brightness is 1, all LEDs are lit.
        - Brightness scales linearly for LEDs in between.

        Args:
            lights (list): Array of RGB values for the LED strip.
            r (int): Red component of the color (0-255).
            g (int): Green component of the color (0-255).
            b (int): Blue component of the color (0-255).
            brightness (float): Brightness value (0.0 to 1.0).

        Returns:
            list: Adjusted lights array.
        """
        num_lights = len(lights)
        middle_index = num_lights // 2  # Index of the middle LED

        # Apply logarithmic scaling to brightness
        if brightness > 0:
            brightness = math.log1p(brightness * 9) / math.log1p(20)  # Scale brightness logarithmically


        # Scale brightness for each LED
        for i in range(num_lights):
            if brightness == 0:
                # Only the middle LED is lit
                lights[i] = [0, 0, 0] if i != middle_index else [r, g, b]
            elif brightness == 1:
                # All LEDs are fully lit
                lights[i] = [r, g, b]
            else:
                # Scale brightness for LEDs based on distance from the middle
                distance_from_middle = abs(i - middle_index)
                max_distance = max(middle_index, num_lights - middle_index - 1)
                scaled_brightness = max(0, brightness - (distance_from_middle / max_distance) * (1 - brightness))
                lights[i] = [
                    int(r * scaled_brightness),
                    int(g * scaled_brightness),
                    int(b * scaled_brightness),
                ]

        return lights
    
    async def start_talking(self):
        print("[ActionManager] Starting to talk...")
        # try:
        #     start_angles = self.my_dog.head_current_angles
        # except AttributeError as e:
        #     print(f"[ERROR] Unable to retrieve head angles: {e}")
        #     start_angles = None
        self.isTalkingMovement = True
        #self.lightbar_bark()
        #look_forward(self.my_dog)
        while self.isTalkingMovement:
            await talk(self.my_dog)
            await asyncio.sleep(0.1)
        #look_forward(self.my_dog)
        #self.lightbar_breath()
        #return to start angles
        # if(start_angles is not None):
        #     self.my_dog.head_move(start_angles, speed=100)
        # else:
        #     # If we can't get the angles, just set it to a default position
        #     start_angles = [0, 0, 0]
        #     # Assuming the dog has a head_move method that takes angles
        # self.my_dog.head_move(start_angles, speed=100)

    async def stop_talking(self):
        print("[ActionManager] Stop Talking...")
        self.isTalkingMovement = False
        self.lightbar_breath()
        self.my_dog.body_stop()
        await self.reset_head()
        # Reset the head position to the last known state

    async def reset_head(self):
        if self.state.head_position == "forward":
            await self.perform_action("look_forward")
        elif self.state.head_position == "left":
            await self.perform_action("look_left")
        elif self.state.head_position == "right":
            await self.perform_action("look_right")
        elif self.state.head_position == "up":
            await self.perform_action("look_up")
        elif self.state.head_position == "down":
            await self.perform_action("look_down")
        elif self.state.head_position == "up left":
            await self.perform_action("look_up_left")
        elif self.state.head_position == "up right":
            await self.perform_action("look_up_right")
        elif self.state.head_position == "down left":
            await self.perform_action("look_down_left")
        elif self.state.head_position == "down right":       
            await self.perform_action("look_down_right")
        else:
            await self.perform_action("look_forward")

    def get_available_actions(self):
        """Returns the list of all available actions the robot dog can perform."""
        return [
            "wag_tail", "bark", "bark_harder", "pant", "howling", "stretch", "push_up",
            "scratch", "handshake", "high_five", "lick_hand", "shake_head", "relax_neck",
            "nod", "think", "recall", "look_down", "look_up", "look_down_left", "look_down_right",
            "look_up_left", "look_up_right", "look_forward", "look_left", "look_right", 
            "fluster", "surprise", "alert", "attack_posture", "body_twisting", "feet_shake", 
            "sit_2_stand", "bored", "walk_forward", "walk_backward", "lie", "stand", "sit",
            "walk_left", "walk_right", "tilt_head_left", "tilt_head_right", "doze_off"
        ]

    async def create_new_persona_action(self, persona_description, client):
        """Handles the actions associated with creating and switching to a new persona."""
        print(f"[ActionManager] Creating new persona: {persona_description}")
        self.isTakingAction = True
        self.isPlayingSound = True
        music = self.speak("audio/angelic_ascending.mp3")
        self.lightbar_boom('white')
        new_persona = None # Initialize new_persona
        try:
            new_persona = await generate_persona(persona_description)
            self.reset_state_for_new_persona()
            # Pass the full persona object, not just the name
            await client.reconnect(new_persona['name'], new_persona)
        finally:
            if music:
                music.music_stop()
            self.isPlayingSound = False
            self.isTakingAction = False
            self.lightbar_breath()
        # Check if new_persona was successfully created before accessing its name
        persona_name = new_persona.get('name', 'Unknown') if new_persona else 'Unknown'
        print(f"[ActionManager] Successfully created and switched to new persona: {persona_name}")
        return "success"

    async def handle_persona_switch_effects(self, persona_name, client):
        """Handles the visual and audio effects during a persona switch."""
        print(f"[ActionManager] Handling persona switch effects for: {persona_name}")
        self.isTakingAction = True
        self.isPlayingSound = True
        self.lightbar_boom('green')
        music = self.speak("audio/angelic_short.mp3")
        try:
            self.reset_state_for_new_persona()
            await client.reconnect(persona_name)
        #exception handling for when the persona is not found
        except Exception as e:
            print(f"[ActionManager] Error during persona switch: {e}")
            return f"Error during persona switch: {e}"
        finally:
            if music:
                music.music_stop()
            self.lightbar_breath()
            self.isTakingAction = False
            self.isPlayingSound = False
        print(f"[ActionManager] Persona switch effects completed for: {persona_name}")


    async def detect_status(self, audio_manager, client):
        """
        Background task that detects changes in environment and updates the goal.
        Also periodically reminds the model of its default goal if it's been inactive.
        """
        is_change = False
        self.last_change_time = 0  # Track the last time a change was noticed
        self.last_reminder_time = time.time()  # Track the last time we reminded of the default goal
        reminder_interval = 15  # 15 seconds
        
        while True:
            try:
                # print("Volume: ", audio_manager.latest_volume)
                # Detect individual changes
                petting_changed = self.detect_petting_change()
                sound_changed = self.detect_sound_direction_change()
                face_changed = await self.detect_face_change()
                orientation_changed = self.detect_orientation_change()

                # Combine for overall change
                is_change = petting_changed or sound_changed or face_changed or orientation_changed

                # Ignore changes if within the last 5 seconds or if talking movement is active
                current_time = time.time()
                if is_change and (current_time - self.last_change_time < 5 or self.isTalkingMovement):
                    is_change = False

                new_goal = ""

                if self.isTalkingMovement or self.isTakingAction or self.isPlayingSound:
                    last_reminder_time = current_time # Reset reminder timer when talking or taking action

                if audio_manager.latest_volume > 30:
                    last_reminder_time = current_time # Reset reminder timer when sound is detected

                if is_change and (not self.isTalkingMovement):
                    new_goal = ""
                    new_status_update = ""
                    self.last_change_time = current_time  # Update the last change time
                    if petting_changed:
                        if (current_time - self.state.petting_detected_at) < 10:
                            new_goal = "You are being petted!  You must say and do something in reaction to this."
                        # else:
                        #     new_status_update = "You are no longer being petted."
                    if sound_changed:
                        if (audio_manager.latest_volume > 30):
                            new_status_update = f"Sound (is someone talking?) came from direction: {self.state.last_sound_direction}. You don't need to react to this if someone is talking..."
                    if face_changed:
                        if (current_time - self.state.face_detected_at) < 10:
                            new_goal = f"A face is detected! You are looking {self.state.head_position}. You must say and do something in reaction to this."
                        # else:
                        #     new_status_update = f"A face is no longer detected. You are looking {self.state.head_position}"
                    if orientation_changed:
                        new_goal = self.state.last_orientation_description

                    if(len(new_status_update) > 0):
                        await client.send_text_message(new_status_update)

                    if(len(new_goal) > 0):
                        self.state.goal = new_goal
                        print(f"Sending awareness of new (temporary) goal: {new_goal}")
                        display_message("New Goal", new_goal)
                        await client.send_awareness()
                        # TODO: force response creation?
                        self.last_reminder_time = current_time  # Reset reminder timer when we have a new goal
                else:
                    # Check if we need to remind of default goal
                    elapsed_since_reminder = current_time - self.last_reminder_time
                    if (not self.isTalkingMovement and 
                        not self.isTakingAction and
                        elapsed_since_reminder > reminder_interval and 
                        client.persona is not None):
                        
                        #start a thread to take a photo
                        #call this in a new thread as a background task: TakePictureAndReportBack(question="Describe the current scene in front of you.")
                        #50% of the time do this
                        if random.random() < 0.5:
                            # Perform inline photo action
                            await self.perform_inline_photo(client)
                            await client.force_response()
                        else:
                            await self.remind_of_default_goal(client)

                        self.last_reminder_time = current_time
                        # reminder_interval = random.randint(45, 60)  # Randomize next interval

                await asyncio.sleep(0.3)
                is_change = False
            except Exception as e:
                print(f"[ActionManager::detect_status] Error: {e}")
                await asyncio.sleep(1)  # Prevent tight loop on failure

    async def perform_inline_photo(self, client):
        #log persona to console
        print(f"[ActionManager] Performing inline photo with persona: {client.persona}")
        self.vision_description = await TakePictureAndReportBack(
                            client.persona['image_prompt'] + f" Describe the current scene in front of you."
                        )
        client.send_text_message(f"In the direction your head is facing ({self.state.head_position}), you can see: {self.vision_description}")

    async def remind_of_default_goal(self, client):
        """
        Reminds the model of its default goal or motivation based on the current persona.
        """
        try:
            default_motivation = client.persona.get("default_motivation", "You should engage with your surroundings.")
            self.state.goal = f"You haven't responded in a while. {default_motivation}"
            print(f"[ActionManager] Reminding of default goal: {self.state.goal}")
            await client.send_awareness()
        except Exception as e:
            print(f"[ActionManager::remind_of_default_goal] Error: {e}")






