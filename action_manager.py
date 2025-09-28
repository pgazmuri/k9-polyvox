import math
import time
import psutil
import asyncio
import random
import os
from typing import Optional

from state_manager import RobotDogState, HeadPose
from robot_hat import utils
from head_controller import HeadController
from vilib import Vilib

FACE_TRACK_UPDATE_INTERVAL = float(os.environ.get("FACE_TRACK_UPDATE_INTERVAL", "0.05"))
FACE_TRACK_RECENTER_TIMEOUT = float(os.environ.get("FACE_TRACK_RECENTER_TIMEOUT", "2.0"))
FACE_TRACK_RECENTER_STEP = float(os.environ.get("FACE_TRACK_RECENTER_STEP", "2.0"))
HEAD_POSTURE_PITCH_COMP = {
    "sitting": float(os.environ.get("SITTING_HEAD_PITCH_COMP", "-20")),
    "standing": float(os.environ.get("STANDING_HEAD_PITCH_COMP", "0")),
}

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

from t2_vision import (
    capture_image,
    is_person_detected,
    close_camera,
    CAMERA_WIDTH,
    CAMERA_HEIGHT,
)
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
            self.PIDOG_SPEAKER_DISABLED = True
            from unittest.mock import patch
            from unittest.mock import MagicMock
            # Mock the enable_speaker function to do nothing
            noop = MagicMock()
            with patch("robot_hat.music.enable_speaker", new=noop):
                self.my_dog = Pidog()
        else:
            self.PIDOG_SPEAKER_DISABLED = False
            self.my_dog = Pidog()
        print("PiDog Initiated...")

        self.head_controller = HeadController(self.my_dog, update_interval=FACE_TRACK_UPDATE_INTERVAL)
        self.head_controller.start()
        self._face_tracking_task: Optional[asyncio.Task] = None
        self._face_tracking_people: int = 0
        self._face_tracking_last_seen: float = 0.0
        self._face_tracking_enabled: bool = os.environ.get("FACE_DETECT_ENABLED", "1") == "1"
        self._face_tracking_return_pose = HeadPose()
        
        display_message("Status", "PiDog Loaded...")
        time.sleep(1)  # small delay for hardware init
        self.reset_state_for_new_persona()
        self._schedule_initial_head_pose()
        if self._face_tracking_enabled:
            self._start_face_tracking()

    def _schedule_initial_head_pose(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._initialize_head_pose_async())

    async def _initialize_head_pose_async(self) -> None:
        pitch_bias = HEAD_POSTURE_PITCH_COMP.get(self.state.posture, 0.0)
        await self.head_controller.set_posture_bias(pitch_bias=pitch_bias)
        await self.head_controller.home()
        self._sync_head_pose()
        self._face_tracking_return_pose = self.state.head_pose.copy()

    def _sync_head_pose(self) -> None:
        self.state.head_pose = self.head_controller.current_pose()

    async def _set_head_pose(
        self,
        *,
        yaw: Optional[float] = None,
        pitch: Optional[float] = None,
        roll: Optional[float] = None,
        update_return: bool = True,
    ) -> None:
        await self.head_controller.set_pose(yaw=yaw, pitch=pitch, roll=roll)
        self._sync_head_pose()
        if update_return:
            self._face_tracking_return_pose = self.state.head_pose.copy()

    async def _adjust_head_pose(
        self,
        *,
        delta_yaw: float = 0.0,
        delta_pitch: float = 0.0,
        delta_roll: float = 0.0,
        update_return: bool = False,
    ) -> None:
        await self.head_controller.adjust_pose(delta_yaw=delta_yaw, delta_pitch=delta_pitch, delta_roll=delta_roll)
        self._sync_head_pose()
        if update_return:
            self._face_tracking_return_pose = self.state.head_pose.copy()

    async def _update_posture_bias(self, old_posture: Optional[str], new_posture: Optional[str]) -> None:
        if old_posture == new_posture:
            return
        pitch_bias = HEAD_POSTURE_PITCH_COMP.get(new_posture, 0.0)
        await self.head_controller.set_posture_bias(pitch_bias=pitch_bias)
        self._sync_head_pose()

    async def _sync_head_from_hardware(self, update_return: bool = False) -> None:
        pose = await self.head_controller.sync_with_hardware()
        self.state.head_pose = pose
        if update_return:
            self._face_tracking_return_pose = pose.copy()

    def _start_face_tracking(self) -> None:
        if self._face_tracking_task and not self._face_tracking_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._face_tracking_task = loop.create_task(self._face_tracking_loop())

    async def _stop_face_tracking(self) -> None:
        if not self._face_tracking_task:
            return
        self._face_tracking_task.cancel()
        try:
            await self._face_tracking_task
        except asyncio.CancelledError:
            pass
        self._face_tracking_task = None

    async def _face_tracking_loop(self) -> None:
        center_x = CAMERA_WIDTH / 2.0
        center_y = CAMERA_HEIGHT / 2.0
        yaw_min, yaw_max = self.head_controller.yaw_limits
        pitch_min, pitch_max = self.head_controller.pitch_limits
        try:
            while True:
                try:
                    people = int(Vilib.detect_obj_parameter.get('human_n', 0))
                    self._face_tracking_people = people
                    now = time.time()

                    if people > 0:
                        self._face_tracking_last_seen = now
                        if not self._face_tracking_active:
                            self._face_tracking_active = True

                        ex = float(Vilib.detect_obj_parameter.get('human_x', center_x)) - center_x
                        ey = float(Vilib.detect_obj_parameter.get('human_y', center_y)) - center_y

                        yaw_step = 0.0
                        if ex > 15:
                            yaw_step = -0.5 * math.ceil(ex / 30.0)
                        elif ex < -15:
                            yaw_step = 0.5 * math.ceil(-ex / 30.0)

                        pitch_step = 0.0
                        if ey > 25:
                            pitch_step = -1.0 * math.ceil(ey / 50.0)
                        elif ey < -25:
                            pitch_step = 1.0 * math.ceil(-ey / 50.0)

                        if yaw_step != 0.0 or pitch_step != 0.0:
                            pose = self.state.head_pose
                            target_yaw = max(yaw_min, min(yaw_max, pose.yaw + yaw_step))
                            target_pitch = max(pitch_min, min(pitch_max, pose.pitch + pitch_step))
                            await self._set_head_pose(yaw=target_yaw, pitch=target_pitch, update_return=False)

                        self.state.face_detected_at = now
                    else:
                        if self._face_tracking_active and (now - self._face_tracking_last_seen) > FACE_TRACK_RECENTER_TIMEOUT:
                            await self._recenter_head_step()
                            if abs(self.state.head_pose.yaw - self._face_tracking_return_pose.yaw) < 0.5 \
                               and abs(self.state.head_pose.pitch - self._face_tracking_return_pose.pitch) < 0.5:
                                self._face_tracking_active = False

                except Exception as face_err:
                    print(f"[ActionManager] Face tracking iteration error: {face_err}")
                    await asyncio.sleep(0.1)

                await asyncio.sleep(FACE_TRACK_UPDATE_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def _recenter_head_step(self) -> None:
        pose = self.state.head_pose
        target = self._face_tracking_return_pose
        yaw_diff = target.yaw - pose.yaw
        pitch_diff = target.pitch - pose.pitch
        roll_diff = target.roll - pose.roll

        step_yaw = max(-FACE_TRACK_RECENTER_STEP, min(FACE_TRACK_RECENTER_STEP, yaw_diff))
        step_pitch = max(-FACE_TRACK_RECENTER_STEP, min(FACE_TRACK_RECENTER_STEP, pitch_diff))
        step_roll = max(-FACE_TRACK_RECENTER_STEP, min(FACE_TRACK_RECENTER_STEP, roll_diff))

        if abs(step_yaw) < 0.05 and abs(step_pitch) < 0.05 and abs(step_roll) < 0.05:
            await self._set_head_pose(
                yaw=target.yaw,
                pitch=target.pitch,
                roll=target.roll,
                update_return=False,
            )
        else:
            await self._adjust_head_pose(
                delta_yaw=step_yaw,
                delta_pitch=step_pitch,
                delta_roll=step_roll,
                update_return=False,
            )

    async def close(self):
        await self._stop_face_tracking()
        await self.head_controller.stop()
        close_camera()
        try:
            await self.perform_action('lie')
        except Exception as e:
            print(f"[ActionManager] Error performing shutdown pose: {e}")
        self.my_dog.close()
        try:
            self.my_dog.sensory_process.stop()
            time.sleep(.5)  # Wait for the process to stop
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
        await self.perform_action('sit,turn_head_forward')
        await self._sync_head_from_hardware(update_return=True)
        await powerup_lightbar_task  # Wait for the power-up sequence to finish
        # Guard against speak() returning False/None
        try:
            if music and hasattr(music, 'music_stop'):
                music.music_stop()
        except Exception as e:
            print(f"[ActionManager] Error stopping music in initialize_posture: {e}")
        self.isPlayingSound = False
        self.lightbar_breath()
    
    def reset_state_for_new_persona(self):
        self.sound_direction_status = ""
        self.vision_description = ""
        self.isTalkingMovement = False
        self.isPlayingSound = False
        self.isTakingAction = False
        self.state = RobotDogState()
        self.state.head_pose = self.head_controller.current_pose()
        self._face_tracking_people = 0
        self._face_tracking_last_seen = 0.0
        self._face_tracking_return_pose = self.state.head_pose.copy()
        self._face_tracking_active = False
        self.last_change_time = 0  # Track the last time a change was noticed
        self.last_reminder_time = time.time()  # Track the last time we reminded of the default goal
        # Tuning knobs for environment polling
        self.face_detection_interval = float(os.environ.get("FACE_DETECTION_INTERVAL", 0.8))
        self.environment_poll_interval = float(os.environ.get("ENVIRONMENT_POLL_INTERVAL", 0.5))
        self._last_face_check_time = 0.0
        self._last_face_log_state = None

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
        now = time.time()
        if now - getattr(self, "_last_face_check_time", 0.0) < self.face_detection_interval:
            return False
        self._last_face_check_time = now

        if self._face_tracking_enabled:
            detected = self._face_tracking_people > 0
        else:
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
    
        if retVal or detected != self._last_face_log_state:
            print(f"[DEBUG] Face change detected: {detected}, last face seen at: {self.state.face_detected_at}")
            self._last_face_log_state = detected
    
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
        status_parts.append(f"Head Pose: {self.state.head_pose.describe()}")

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

        # System status (non-blocking instantaneous CPU sample to avoid stall)
        cpu_usage = psutil.cpu_percent(interval=None)
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
        Gathers basic info about the robot's state, including posture, head pose,
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

        # Posture and Head Pose
        status_parts.append(f"Posture: {self.state.posture}")
        status_parts.append(f"Head Pose: {self.state.head_pose.describe()}")

        # Last Sound Direction
        last_sound = self.state.last_sound_direction if self.state.last_sound_direction else "None detected yet"
        status_parts.append(f"Last Sound Direction: {last_sound}")

        return "\n".join(status_parts)

    async def take_photo(self, persona, question="", silent=False, client=None):
        """Capture an image and send to realtime API. Lightbar effect only (no sound)."""
    # New realtime image capture path (no legacy GPT vision call)
        self.isTakingAction = True
        image_path = None
        try:
            if not silent:
                self.lightbar_boom()
            image_path = capture_image()
            if client and image_path:
                await client.send_image_and_request_response(image_path)
            self.vision_description = "Image captured and sent." if image_path else "Image capture failed."
        except Exception as e:
            print(f"[ActionManager] Error taking photo: {e}")
            self.vision_description = "Error taking photo."
        finally:
            if not silent:
                self.lightbar_breath()
            self.isPlayingSound = False
            self.isTakingAction = False
        return self.vision_description

    async def perform_action(self, action_name):
        """Executes one or more PiDog actions by name (comma-separated)."""
        print(f"[ActionManager] Performing action(s): {action_name}")
        self.isTakingAction = True
        if not action_name:
            self.isTakingAction = False
            return
        actions = [a.strip() for a in action_name.split(',') if a.strip()]
        for action in actions:
            try:
                old_posture = self.state.posture
                if action == 'wag_tail':
                    wag_tail(self.my_dog, step_count=5, speed=100)
                elif action == 'bark':
                    bark(self.my_dog)
                elif action == 'bark_harder':
                    bark_action(self.my_dog, speak='single_bark_2')
                    self.state.posture = "standing"
                elif action == 'pant':
                    pant(self.my_dog)
                elif action == 'howling':
                    howling(self.my_dog)
                    self.state.posture = "sitting"
                elif action == 'stretch':
                    stretch(self.my_dog)
                    self.state.posture = "sitting"
                elif action == 'push_up':
                    if self.state.posture == "sitting":
                        sit_2_stand(self.my_dog)
                    push_up(self.my_dog)
                    self.state.posture = "standing"
                elif action == 'scratch':
                    if self.state.posture == "standing":
                        sit_down(self.my_dog)
                    scratch(self.my_dog)
                    self.state.posture = "sitting"
                elif action == 'handshake':
                    if self.state.posture == "standing":
                        sit_down(self.my_dog)
                    hand_shake(self.my_dog)
                    self.state.posture = "sitting"
                elif action == 'high_five':
                    if self.state.posture == "standing":
                        sit_down(self.my_dog)
                    high_five(self.my_dog)
                    self.state.posture = "sitting"
                elif action == 'lick_hand':
                    if self.state.posture == "standing":
                        sit_down(self.my_dog)
                    lick_hand(self.my_dog)
                    self.state.posture = "sitting"
                elif action == 'shake_head':
                    shake_head(self.my_dog)
                    await self._sync_head_from_hardware(update_return=False)
                elif action == 'relax_neck':
                    relax_neck(self.my_dog)
                    await self._sync_head_from_hardware(update_return=False)
                elif action == 'nod':
                    nod(self.my_dog)
                    await self._sync_head_from_hardware(update_return=False)
                elif action == 'think':
                    think(self.my_dog)
                    await self._sync_head_from_hardware(update_return=True)
                elif action == 'recall':
                    recall(self.my_dog)
                    await self._sync_head_from_hardware(update_return=True)
                elif action == 'turn_head_down':
                    await self._set_head_pose(pitch=-25.0)
                elif action == 'turn_head_up':
                    await self._set_head_pose(pitch=25.0)
                elif action == 'turn_head_down_left':
                    await self._set_head_pose(yaw=25.0, pitch=-25.0)
                elif action == 'turn_head_down_right':
                    await self._set_head_pose(yaw=-25.0, pitch=-25.0)
                elif action == 'turn_head_up_left':
                    await self._set_head_pose(yaw=25.0, pitch=25.0)
                elif action == 'turn_head_up_right':
                    await self._set_head_pose(yaw=-25.0, pitch=25.0)
                elif action == 'turn_head_forward':
                    await self._set_head_pose(yaw=0.0, pitch=0.0, roll=0.0)
                elif action == 'turn_head_left':
                    await self._set_head_pose(yaw=60.0)
                elif action == 'turn_head_right':
                    await self._set_head_pose(yaw=-60.0)
                elif action == 'fluster':
                    fluster(self.my_dog)
                elif action == 'surprise':
                    surprise(self.my_dog)
                    self.state.posture = "sitting"
                elif action == 'alert':
                    alert(self.my_dog)
                    self.state.posture = "sitting"
                elif action == 'attack_posture':
                    attack_posture(self.my_dog)
                    self.state.posture = "standing"
                elif action == 'body_twisting':
                    body_twisting(self.my_dog)
                elif action == 'feet_shake':
                    feet_shake(self.my_dog)
                elif action == 'sit_2_stand':
                    sit_2_stand(self.my_dog)
                    self.state.posture = "sitting"
                elif action == 'bored':
                    waiting(self.my_dog)
                elif action == 'walk_forward':
                    if self.state.posture == "sitting":
                        sit_2_stand(self.my_dog)
                    walk_forward(self.my_dog, step_count=5, speed=100)
                    self.state.posture = "standing"
                elif action == 'walk_backward':
                    if self.state.posture == "sitting":
                        sit_2_stand(self.my_dog)
                    walk_backward(self.my_dog, step_count=5, speed=100)
                    self.state.posture = "standing"
                elif action == 'lie':
                    lie_down(self.my_dog)
                    # Choose sitting as a neutral/resting classification (was 'standing' previously)
                    self.state.posture = "sitting"
                elif action == 'stand':
                    if self.state.posture == "sitting":
                        sit_2_stand(self.my_dog)
                    else:
                        stand_up(self.my_dog)
                    self.state.posture = "standing"
                elif action == 'sit':
                    sit_down(self.my_dog)
                    self.state.posture = "sitting"
                elif action == 'walk_left':
                    if self.state.posture == "sitting":
                        sit_2_stand(self.my_dog)
                    turn_left(self.my_dog, step_count=5, speed=100)
                    self.state.posture = "standing"
                elif action == 'walk_right':
                    if self.state.posture == "sitting":
                        sit_2_stand(self.my_dog)
                    turn_right(self.my_dog, step_count=5, speed=100)
                    self.state.posture = "standing"
                elif action == 'tilt_head_left':
                    tilt_head_left(self.my_dog)
                    await self._sync_head_from_hardware(update_return=True)
                elif action == 'tilt_head_right':
                    tilt_head_right(self.my_dog)
                    await self._sync_head_from_hardware(update_return=True)
                elif action == 'doze_off':
                    doze_off(self.my_dog, speed=100)
                    self.state.posture = "standing"
                else:
                    print(f"[ActionManager] Unknown action: {action}")

                # Apply head pitch compensation if posture changed
                if old_posture != self.state.posture:
                    await self._update_posture_bias(old_posture, self.state.posture)
            except Exception as e:
                print(f"[ActionManager] Error during action '{action}': {e}")
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
        self.isTalkingMovement = True
        await self.head_controller.enable_talking()

    async def stop_talking(self):
        print("[ActionManager] Stop Talking...")
        self.isTalkingMovement = False
        await self.head_controller.disable_talking()
        self.lightbar_breath()
        self.my_dog.body_stop()
        # Keep head oriented toward current target (face tracking or manual)

    async def reset_head(self):
        await self._set_head_pose(yaw=0.0, pitch=0.0, roll=0.0)

    def get_available_actions(self):
        """Returns the list of all available actions the robot dog can perform."""
        return [
            "wag_tail", "bark", "bark_harder", "pant", "howling", "stretch", "push_up",
            "scratch", "handshake", "high_five", "lick_hand", "shake_head", "relax_neck",
            "nod", "think", "recall", "turn_head_down", "turn_head_up", "turn_head_down_left", "turn_head_down_right",
            "turn_head_up_left", "turn_head_up_right", "turn_head_forward", "turn_head_left", "turn_head_right", 
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

                if self.isTalkingMovement or self.isTakingAction or self.isPlayingSound or client.isDetectingUserSpeech or client.isReceivingAudio:
                    self.last_reminder_time = current_time # Reset reminder timer when talking or taking action
                    is_change = False

                if is_change and (not self.isTalkingMovement):
                    goal_messages = []
                    status_messages = []
                    self.last_change_time = current_time  # Update the last change time
                    if petting_changed:
                        if (current_time - self.state.petting_detected_at) < 10:
                            goal_messages.append("You are being petted! You must say and do something in reaction to this.")
                    if sound_changed:
                        direction = self.state.last_sound_direction or "an unknown direction"
                        if audio_manager.latest_volume > 30:
                            goal_messages.append(
                                f"A loud sound came from your {direction}. You must react, look that way, and respond."
                            )
                        else:
                            status_messages.append(
                                f"A quiet sound came from your {direction}."
                            )
                    if face_changed:
                        if (current_time - self.state.face_detected_at) < 10:
                            goal_messages.append(
                                "A face is detected! You are looking "
                                f"{self.state.head_pose.describe()}. You must say and do something in reaction to this."
                            )
                    if orientation_changed:
                        orientation_msg = self.state.last_orientation_description or "Your orientation changed."
                        goal_messages.append(f"{orientation_msg} You must say and do something in reaction to this.")

                    if status_messages:
                        await client.send_text_message(" ".join(status_messages))

                    if goal_messages:
                        new_goal = " ".join(goal_messages)
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
                        # if random.random() < 0.3:
                        #     # Perform inline photo action
                            
                        #     await client.force_response()
                        # else:
                        await self.perform_inline_photo(client)

                        await self.remind_of_default_goal(client)

                        self.last_reminder_time = current_time
                        # reminder_interval = random.randint(45, 60)  # Randomize next interval

                await asyncio.sleep(self.environment_poll_interval)
                is_change = False
            except Exception as e:
                print(f"[ActionManager::detect_status] Error: {e}")
                await asyncio.sleep(1)  # Prevent tight loop on failure

    async def perform_inline_photo(self, client):
        print(f"[ActionManager] Performing inline photo (wake-up) with persona: {client.persona}")
        try:
            self.lightbar_boom()
            image_path = capture_image()
            if image_path:
                await client.send_image_and_request_response(image_path)
        except Exception as e:
            print(f"[ActionManager] Inline photo error: {e}")
        finally:
            self.lightbar_breath()

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






