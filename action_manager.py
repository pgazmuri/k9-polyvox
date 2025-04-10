import math
import time
import psutil
from state_manager import RobotDogState

# External dependencies
from pidog import Pidog
from robot_hat import Ultrasonic
from preset_actions import *
from t2_vision import TakePictureAndReportBack, is_person_detected

class ActionManager:
    """
    Manages all PiDog-specific actions and sensor interactions.
    """

    def __init__(self):
        self.my_dog = Pidog()
        time.sleep(1)  # small delay for hardware init
        self.sound_direction_status = ""
        self.vision_description = ""
        self.isTalkingMovement = False
        self.state = RobotDogState()
        # self.my_dog.ultrasonic.set_mode(Ultrasonic.MODE_CONTINUOUS)

    def initialize_posture(self):
        """Sets an initial posture after power up."""
        print("[ActionManager] Initializing posture...")
        self.my_dog.speak("powerup")
        self.my_dog.do_action('sit', speed=80)
        self.perform_action('look_forward')
        self.state.posture = "sitting"
        self.state.head_position = "forward"
        self.lightbar_breath()
        
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
                print(f"[DEBUG] Sound direction change detected: {current_direction}")
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
            if self.state.face_detected_at and time.time() - self.state.face_detected_at > 10:
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
        elif -26 <= body_pitch <= 15:
            if 65 <= body_roll <= 105:
                return "You are sitting, lying, or standing: upright."
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
            self.my_dog.do_action('wag_tail', speed=100)
        
        if status == 'LS':   # front to back
            self.my_dog.do_action('head_up_down')
        elif status == 'RS': # back to front
            attack_posture(self.my_dog)
        elif status == 'R':
            self.my_dog.do_action('tilting_head_right')
        elif status == 'L':
            self.my_dog.do_action('tilting_head_left')

    def get_status(self):
        """
        Gathers info about battery, pitch, CPU usage, memory usage,
        disk usage, top processes, uptime, and the last sound direction.
        Returns them as a formatted string.
        """
        status_parts = []

        if self.my_dog.dual_touch.read() != 'N':
            status_parts.append("Someone is petting my head RIGHT NOW!")
        elif self.state.petting_detected_at and time.time() - self.state.petting_detected_at < 10:
            status_parts.append("Someone petted my head recently!")

        person_detected = is_person_detected()
        #if a person is detected, write a status that there is a person in front of you
        if person_detected:
            status_parts.append("A person is in front of you!")
        elif self.state.face_detected_at and time.time() - self.state.face_detected_at < 10:
            status_parts.append("A person was just in front of you!")
        else:
            status_parts.append("No person in front of you (that we can detect).")

        # Report on posture and head position
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

        status_parts.append(f"Your orientation: {self.get_orientation_description()}")

        # Gyroscope angular velocity
        status_parts.append(f"Gyro Angular Velocity: gx={gx:.2f}, gy={gy:.2f}, gz={gz:.2f}")

        # Distance Sensor
        try:
            # us = new Ultrasonic()
            distance = self.my_dog.distance
            distance = round(distance, 2)
            status_parts.append(f"Space in front of you: {distance} cm (ultrasonic distance)")
        except AttributeError:
            status_parts.append("Ultrasonic sensor is not functional or not initialized.")
        except Exception as e:
            status_parts.append(f"Error reading ultrasonic sensor: {str(e)}")

        # Sound direction
        status_parts.append(f"Last Sound Direction: {self.state.last_sound_direction}")

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

    async def take_photo(self, persona_prompt="", question=""):
        """
        Asks PiDog to flash a certain LED style, then triggers the camera routine
        and calls `TakePictureAndReportBack` with the prompt. Then reverts LED style.
        """
        self.lightbar_boom()
        try:
            # optionally play a "camera shutter" or "beep" sound
            # speak(self.my_dog, "calc")  # If you want a beep or something
            music = speak(self.my_dog, "calc")
            self.vision_description = await TakePictureAndReportBack(
                persona_prompt + f" {question}"
            )
            music.music_stop()
        finally:
            self.lightbar_breath()
        
        print("[ActionManager] Vision result: ", self.vision_description)
        return self.vision_description

    async def perform_action(self, action_name):
        """
        Executes one or more PiDog actions by name. 
        If multiple actions are comma-separated, executes them sequentially.
        """
        print(f"[ActionManager] Performing action(s): {action_name}")
        actions = [a.strip() for a in action_name.split(',')]

        for action in actions:
            if action == 'wag_tail':
                self.my_dog.do_action('wag_tail', step_count=5, speed=100)
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
                    self.my_dog.do_action('sit')
                scratch(self.my_dog)
                self.state.posture = "sitting"
                await self.reset_head()
            elif action == 'handshake':
                if self.state.posture == "standing":
                    self.my_dog.do_action('sit')
                hand_shake(self.my_dog)
                self.state.posture = "sitting"
                await self.reset_head()
            elif action == 'high_five':
                if self.state.posture == "standing":
                    self.my_dog.do_action('sit')
                high_five(self.my_dog)
                self.state.posture = "sitting"
                await self.reset_head()
            elif action == 'lick_hand':
                if self.state.posture == "standing":
                    self.my_dog.do_action('sit')
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
                self.my_dog.do_action('forward', step_count=5, speed=100)
                self.state.posture = "standing"
                await self.reset_head()
            elif action == 'walk_backward':
                if self.state.posture == "sitting":
                    sit_2_stand(self.my_dog)
                self.my_dog.do_action('backward', step_count=5, speed=100)
                self.state.posture = "standing"
                await self.reset_head()
            elif action == 'lie':
                self.my_dog.do_action('lie')
                self.state.posture = "standing"
                await self.reset_head()
            elif action == 'stand':
                if self.state.posture == "sitting":
                    sit_2_stand(self.my_dog)
                else:
                    self.my_dog.do_action('stand')
                self.state.posture = "standing"
                await self.reset_head()
            elif action == 'sit':
                self.my_dog.do_action('sit')
                self.state.posture = "sitting"
                await self.reset_head()
            elif action == 'walk_left':
                if self.state.posture == "sitting":
                    sit_2_stand(self.my_dog)
                self.my_dog.do_action('turn_left', step_count=5, speed=100)
                self.state.posture = "standing"
                await self.reset_head()
            elif action == 'walk_right':
                if self.state.posture == "sitting":
                    sit_2_stand(self.my_dog)
                self.my_dog.do_action('turn_right', step_count=5, speed=100)
                self.state.posture = "standing"
                await self.reset_head()
            elif action == 'tilt_head_left':
                self.my_dog.do_action('tilting_head_left')
            elif action == 'tilt_head_right':
                self.my_dog.do_action('tilting_head_right')
            elif action == 'doze_off':
                self.my_dog.do_action('doze_off', speed=100)
                self.state.posture = "standing"
                await self.reset_head()
            else:
                print(f"[ActionManager] Unknown action: {action}")
            
        self.my_dog.wait_all_done()
        print("[ActionManager] Done performing actions.")

    def lightbar_breath(self):
        self.my_dog.rgb_strip.set_mode(style="breath", color='pink', bps=0.5)

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
            
        




