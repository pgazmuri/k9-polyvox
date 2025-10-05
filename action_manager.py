import asyncio
import os
import time
import wave
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from typing import AsyncIterator, Awaitable, Callable, Dict, Optional

from audio_controller import AudioController
from face_tracker import FaceTracker
from head_controller import HeadController
from head_pose_manager import HeadPoseManager
from lightbar_controller import LightbarController
from sensor_monitor import SensorMonitor
from state_manager import RobotDogState
from status_reporter import StatusReporter

FACE_TRACK_UPDATE_INTERVAL = float(os.environ.get("FACE_TRACK_UPDATE_INTERVAL", "0.05"))
FACE_TRACK_RECENTER_TIMEOUT = float(os.environ.get("FACE_TRACK_RECENTER_TIMEOUT", "2.0"))
FACE_TRACK_RECENTER_STEP = float(os.environ.get("FACE_TRACK_RECENTER_STEP", "2.0"))
STIMULUS_MIN_INTERVAL = float(os.environ.get("STIMULUS_MIN_INTERVAL", "5.0"))  # Minimum time between same stimulus type
STIMULUS_QUIET_PERIOD = float(os.environ.get("STIMULUS_QUIET_PERIOD", "3.0"))  # How long to wait for quiet before reacting
STIMULUS_GRACE_AFTER_FIRST_UTTERANCE = float(os.environ.get("STIMULUS_GRACE_AFTER_FIRST_UTTERANCE", "15.0"))  # Cooldown after conversation starts
SOUND_PASSIVE_WAIT = float(os.environ.get("SOUND_PASSIVE_WAIT", "2.0"))

# External dependencies
from pidog import Pidog

# Sound file paths
User = os.popen('echo ${SUDO_USER:-$LOGNAME}').readline().strip()
UserHome = os.popen('getent passwd %s | cut -d: -f 6' % User).readline().strip()
SOUND_DIR = f"{UserHome}/pidog/sounds/"
LOCAL_SOUND_DIR = "audio/"

# Volume settings (0-100) for system sound effects
STARTUP_SOUND_VOLUME = int(os.environ.get("STARTUP_SOUND_VOLUME", "5"))
PERSONA_TRANSITION_VOLUME = int(os.environ.get("PERSONA_TRANSITION_VOLUME", "5"))


def get_sound_duration(sound_name: str) -> float:
    """Get the duration of a WAV sound file by reading its header.
    
    Args:
        sound_name: Name of the sound file (without extension)
        
    Returns:
        Duration in seconds, or 0.0 if file not found or error reading
    """
    # Try both local and system sound directories
    possible_paths = [
        os.path.join(LOCAL_SOUND_DIR, f"{sound_name}.wav"),
        os.path.join(SOUND_DIR, f"{sound_name}.wav"),
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            try:
                with wave.open(path, 'r') as wav_file:
                    frames = wav_file.getnframes()
                    rate = wav_file.getframerate()
                    duration = frames / float(rate)
                    print(f"[ActionManager] Sound '{sound_name}' duration: {duration:.2f}s (from {path})")
                    return duration
            except Exception as e:
                print(f"[ActionManager] Error reading sound file {path}: {e}")
                continue
    
    print(f"[ActionManager] Warning: Sound file '{sound_name}.wav' not found, using 0s duration")
    return 0.0


@dataclass(frozen=True)
class ActionSpec:
    runner: Callable[[], Awaitable[None]]
    ensure_posture: Optional[str] = None
    posture_after: Optional[str] = None
    exclusive: bool = False

# Conditionally import actions (real or mock)
from actions import *  # noqa: F401,F403

from t2_vision import (
    capture_image,
    is_person_detected,
    close_camera,
    CAMERA_WIDTH,
    CAMERA_HEIGHT,
)
from persona_generator import generate_persona
from system_prompts import personas

from display_manager import display_message

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
        
        # Configure amplitude-based motion parameters from environment
        amp_min = float(os.environ.get("TALK_AMP_SCALE_MIN", "0.4"))
        amp_max = float(os.environ.get("TALK_AMP_SCALE_MAX", "1.0"))
        amp_threshold = float(os.environ.get("TALK_AMP_THRESHOLD", "0.05"))
        self.head_controller.set_amplitude_scale_range(amp_min, amp_max)
        self.head_controller.set_amplitude_threshold(amp_threshold)
        
        # Configure talking motion amplitudes from environment
        yaw_amp = float(os.environ.get("TALK_YAW_AMP", "3.5"))
        pitch_amp = float(os.environ.get("TALK_PITCH_AMP", "4.0"))
        roll_amp = float(os.environ.get("TALK_ROLL_AMP", "1.5"))
        freq = float(os.environ.get("TALK_FREQUENCY", "0.9"))
        asyncio.create_task(self.head_controller.set_talk_profile(
            yaw_amp=yaw_amp, pitch_amp=pitch_amp, roll_amp=roll_amp, frequency=freq
        ))

        self.audio = AudioController(self.my_dog)
        self.lightbar = LightbarController(self.my_dog.rgb_strip)

        self.state = RobotDogState()
        self.sensors = SensorMonitor(self.my_dog, self.state)
        self.status_reporter = StatusReporter(self.my_dog, self.state, self.sensors)
        self.head_pose = HeadPoseManager(self.head_controller, self.state)

        face_detect_enabled = os.environ.get("FACE_DETECT_ENABLED", "1") == "1"
        self.face_tracker = FaceTracker(
            self.head_pose,
            self.state,
            camera_width=CAMERA_WIDTH,
            camera_height=CAMERA_HEIGHT,
            update_interval=FACE_TRACK_UPDATE_INTERVAL,
            recenter_timeout=FACE_TRACK_RECENTER_TIMEOUT,
            recenter_step=FACE_TRACK_RECENTER_STEP,
            enabled=face_detect_enabled,
        )

        self._initialize_runtime_flags()
        
        display_message("Status", "PiDog Loaded...")
        time.sleep(1)  # small delay for hardware init
        self.reset_state_for_new_persona()
        self._action_specs: Dict[str, ActionSpec] = self._build_action_specs()
        self._schedule_head_initialization()

    def _initialize_runtime_flags(self) -> None:
        self.sound_direction_status = ""
        self.vision_description = ""
        self.isTalkingMovement = False
        self.isPlayingSound = False
        self.isTakingAction = False
        self.last_change_time = 0
        self.last_reminder_time = time.time()
        self.face_detection_interval = float(os.environ.get("FACE_DETECTION_INTERVAL", 0.8))
        self.environment_poll_interval = float(os.environ.get("ENVIRONMENT_POLL_INTERVAL", 0.5))
        self._last_face_check_time = 0.0
        self._last_face_log_state = None
        self._stimulus_last_sent = {}
        self.stimulus_min_interval = STIMULUS_MIN_INTERVAL
        self.stimulus_quiet_period = STIMULUS_QUIET_PERIOD
        self._wakeup_active = False
        self._persona_switch_task: Optional[asyncio.Task] = None
        self._first_utterance_time: Optional[float] = None
        self._pending_sound_stimulus: Optional[tuple[float, str, str]] = None

    def _schedule_head_initialization(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._initialize_head_pose())

    async def _initialize_head_pose(self) -> None:
        await self.head_pose.initialize()
        self.face_tracker.mark_return_pose()
        if self.face_tracker.enabled:
            await self.face_tracker.start()

    async def _notify_stimulus(
        self,
        client,
        message: str,
        *,
        instructions: Optional[str] = None,
        title: str = "Stimulus",
    ) -> None:
        """Force the model to react to an environmental stimulus and log the details."""
        if not message:
            return

        sanitized_message = " ".join(message.split())
        display_message(title, sanitized_message[:60] + ("…" if len(sanitized_message) > 60 else ""))
        if instructions:
            final_instructions = (
                f"{sanitized_message} "
                f"{' '.join(instructions.split())}"
            ).strip()
        else:
            final_instructions = (
                f"{sanitized_message} React immediately to this stimulus, describe what you notice, and respond in character."
            )

        print(
            "[ActionManager] Stimulus -> message='%s' instructions='%s'" %
            (sanitized_message, final_instructions)
        )

        try:
            await client.force_response(final_instructions)
        except Exception as force_err:
            print(f"[ActionManager] Error forcing response: {force_err}")

    def _allow_stimulus(self, event_key: str, now: float) -> bool:
        # Don't allow stimulus until initial wake-up period is over (5 seconds after first utterance)
        if self._first_utterance_time is not None:
            time_since_first = now - self._first_utterance_time
            if time_since_first < 5.0:
                # Still in initial wake-up period
                return False
            elif time_since_first < STIMULUS_GRACE_AFTER_FIRST_UTTERANCE:
                # In grace period after initial wake-up (but allow face tracking)
                if event_key != "face":
                    return False
        
        last_sent = self._stimulus_last_sent.get(event_key)
        if last_sent is None:
            return True
        return (now - last_sent) >= self.stimulus_min_interval

    def _mark_stimulus_sent_for_keys(self, event_keys: list[str], timestamp: float) -> None:
        for key in event_keys:
            self._stimulus_last_sent[key] = timestamp

    def _can_send_stimulus(self, client, event_key: str = "generic") -> bool:
        # Use configured quiet period for all stimulus types
        quiet_period = self.stimulus_quiet_period
        
        # Check if system is quiet (no user speech for sufficient time)
        # Note: We use is_quiet_for when available, which checks for actual speech activity
        # Don't block on detecting_speech alone - only block if actually receiving/responding
        is_quiet = True
        if hasattr(client, "is_quiet_for"):
            is_quiet = client.is_quiet_for(quiet_period)
        else:
            # Fallback: only block if actually receiving audio or responding
            is_quiet = not (client.isReceivingAudio or getattr(client, "has_active_response", False))

        if not is_quiet:
            return False

        # Check if model is currently responding or system is busy with actions
        # NOTE: We deliberately don't check isDetectingUserSpeech here - that's too sensitive
        # and blocks legitimate stimulus responses during ambient noise
        return not (
            self.isTalkingMovement
            or self.isTakingAction
            or self.isPlayingSound
            or self._wakeup_active
            or client.isReceivingAudio
            or getattr(client, "_response_active", False)
            or getattr(client, "has_active_response", False)
        )

    async def _dispatch_stimulus(
        self,
        client,
        message: str,
        *,
        instructions: Optional[str] = None,
        title: str = "Stimulus",
        event_keys: Optional[list[str]] = None,
    ) -> None:
        event_keys = event_keys or ["generic"]
        primary_key = event_keys[0] if event_keys else "generic"
        
        if not self._can_send_stimulus(client, event_key=primary_key):
            print("[ActionManager] Stimulus dropped because system is busy or not quiet enough.")
            return

        await self._notify_stimulus(
            client,
            message,
            instructions=instructions,
            title=title,
        )
        self._mark_stimulus_sent_for_keys(event_keys, time.time())
        
        # Track first utterance time for grace period
        if self._first_utterance_time is None:
            self._first_utterance_time = time.time()
            print(f"[ActionManager] First utterance at {self._first_utterance_time:.1f}, stimulus grace period active for {STIMULUS_GRACE_AFTER_FIRST_UTTERANCE}s")

    async def _set_head_pose(
        self,
        *,
        yaw: Optional[float] = None,
        pitch: Optional[float] = None,
        roll: Optional[float] = None,
        update_return: bool = True,
    ) -> None:
        await self.head_pose.set_pose(
            yaw=yaw,
            pitch=pitch,
            roll=roll,
            update_return=update_return,
        )

    async def _adjust_head_pose(
        self,
        *,
        delta_yaw: float = 0.0,
        delta_pitch: float = 0.0,
        delta_roll: float = 0.0,
        update_return: bool = False,
    ) -> None:
        await self.head_pose.adjust_pose(
            delta_yaw=delta_yaw,
            delta_pitch=delta_pitch,
            delta_roll=delta_roll,
            update_return=update_return,
        )

    async def _update_posture_bias(self, old_posture: Optional[str], new_posture: Optional[str]) -> None:
        await self.head_pose.handle_posture_change(old_posture, new_posture)

    async def _sync_head_from_hardware(self, update_return: bool = False) -> None:
        await self.head_pose.sync_from_hardware(update_return=update_return)

    async def close(self):
        await self.face_tracker.stop()
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

    async def speak_async(self, filename, volume=100):
        """
        Asynchronously plays a sound file.
        """
        if not filename:
            return
        self.isPlayingSound = True
        await self.audio.play_file_async(filename, volume)
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
        return self.audio.play(name, volume)

    async def initialize_posture(self):
        """Sets an initial posture after power up."""
        print("[ActionManager] Initializing posture...")
        powerup_lightbar_task = asyncio.create_task(self.lightbar.power_up_sequence())
        self.isPlayingSound = True
        music = self.speak("powerup", STARTUP_SOUND_VOLUME)
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
        self.lightbar.breath()
    
    def reset_state_for_new_persona(self):
        self.state.reset()
        self.state.head_pose = self.head_controller.current_pose()
        self._initialize_runtime_flags()
        # Reset first utterance time so wake-up grace period applies to new persona
        self._first_utterance_time = None
        print("[ActionManager] Reset state for new persona - wake-up grace period will apply")
        if self.face_tracker.enabled:
            self.face_tracker.mark_return_pose()

    def _wrap_sync_action(self, func: Callable[[], None], *, sync_head: Optional[bool] = None, has_sound: bool = False, sound_duration: float = 0.0) -> Callable[[], Awaitable[None]]:
        """Wrap a synchronous action to make it async-compatible.
        
        Args:
            func: The synchronous action function to execute
            sync_head: Whether to sync head position after action
            has_sound: Whether this action plays a sound that we need to wait for
            sound_duration: Duration in seconds to wait for sound to complete
        """
        async def runner() -> None:
            func()
            
            # Wait for sound to complete if action has one
            if has_sound and sound_duration > 0:
                print(f"[ActionManager] Waiting {sound_duration}s for sound to complete...")
                await asyncio.sleep(sound_duration)
            
            if sync_head is not None:
                await self._sync_head_from_hardware(update_return=sync_head)

        return runner

    async def _ensure_posture(self, target: Optional[str]) -> None:
        if not target:
            return

        current = getattr(self.state, "posture", None)

        if target == "sitting" and current != "sitting":
            sit_down(self.my_dog)
            self.state.posture = "sitting"
        elif target == "standing" and current != "standing":
            if current == "sitting":
                sit_2_stand(self.my_dog)
            else:
                stand_up(self.my_dog)
            self.state.posture = "standing"

    def _build_action_specs(self) -> Dict[str, ActionSpec]:
        wrap = self._wrap_sync_action

        return {
            "wag_tail": ActionSpec(runner=wrap(lambda: wag_tail(self.my_dog, step_count=5, speed=100))),
            "bark": ActionSpec(runner=wrap(lambda: bark(self.my_dog), has_sound=True, sound_duration=get_sound_duration("single_bark_1"))),
            "bark_harder": ActionSpec(runner=wrap(lambda: bark_action(self.my_dog, speak='single_bark_2'), has_sound=True, sound_duration=get_sound_duration("single_bark_2")), posture_after="standing"),
            "pant": ActionSpec(runner=wrap(lambda: pant(self.my_dog), has_sound=True, sound_duration=get_sound_duration("pant"))),
            "howling": ActionSpec(runner=wrap(lambda: howling(self.my_dog), has_sound=True, sound_duration=get_sound_duration("howling")), posture_after="sitting"),
            "stretch": ActionSpec(runner=wrap(lambda: stretch(self.my_dog)), posture_after="sitting"),
            "push_up": ActionSpec(runner=wrap(lambda: push_up(self.my_dog)), ensure_posture="standing", posture_after="standing"),
            "scratch": ActionSpec(runner=wrap(lambda: scratch(self.my_dog)), ensure_posture="sitting", posture_after="sitting"),
            "handshake": ActionSpec(runner=wrap(lambda: hand_shake(self.my_dog)), ensure_posture="sitting", posture_after="sitting"),
            "high_five": ActionSpec(runner=wrap(lambda: high_five(self.my_dog)), ensure_posture="sitting", posture_after="sitting"),
            "lick_hand": ActionSpec(runner=wrap(lambda: lick_hand(self.my_dog)), ensure_posture="sitting", posture_after="sitting"),
            "shake_head": ActionSpec(runner=wrap(lambda: shake_head(self.my_dog), sync_head=False)),
            "relax_neck": ActionSpec(runner=wrap(lambda: relax_neck(self.my_dog), sync_head=False)),
            "nod": ActionSpec(runner=wrap(lambda: nod(self.my_dog), sync_head=False)),
            "think": ActionSpec(runner=wrap(lambda: think(self.my_dog), sync_head=True)),
            "recall": ActionSpec(runner=wrap(lambda: recall(self.my_dog), sync_head=True)),
            "turn_head_down": ActionSpec(runner=partial(self._set_head_pose, pitch=-25.0)),
            "turn_head_up": ActionSpec(runner=partial(self._set_head_pose, pitch=25.0)),
            "turn_head_down_left": ActionSpec(runner=partial(self._set_head_pose, yaw=25.0, pitch=-25.0)),
            "turn_head_down_right": ActionSpec(runner=partial(self._set_head_pose, yaw=-25.0, pitch=-25.0)),
            "turn_head_up_left": ActionSpec(runner=partial(self._set_head_pose, yaw=25.0, pitch=25.0)),
            "turn_head_up_right": ActionSpec(runner=partial(self._set_head_pose, yaw=-25.0, pitch=25.0)),
            "turn_head_forward": ActionSpec(runner=partial(self._set_head_pose, yaw=0.0, pitch=0.0, roll=0.0)),
            "turn_head_left": ActionSpec(runner=partial(self._set_head_pose, yaw=60.0)),
            "turn_head_right": ActionSpec(runner=partial(self._set_head_pose, yaw=-60.0)),
            "fluster": ActionSpec(runner=wrap(lambda: fluster(self.my_dog))),
            "surprise": ActionSpec(runner=wrap(lambda: surprise(self.my_dog)), posture_after="sitting"),
            "alert": ActionSpec(runner=wrap(lambda: alert(self.my_dog)), posture_after="sitting"),
            "attack_posture": ActionSpec(runner=wrap(lambda: attack_posture(self.my_dog)), posture_after="standing"),
            "body_twisting": ActionSpec(runner=wrap(lambda: body_twisting(self.my_dog)), exclusive=True),
            "feet_shake": ActionSpec(runner=wrap(lambda: feet_shake(self.my_dog)), exclusive=True),
            "sit_2_stand": ActionSpec(runner=wrap(lambda: sit_2_stand(self.my_dog)), posture_after="sitting"),
            "bored": ActionSpec(runner=wrap(lambda: waiting(self.my_dog))),
            "walk_forward": ActionSpec(runner=wrap(lambda: walk_forward(self.my_dog, step_count=5, speed=100)), ensure_posture="standing", posture_after="standing"),
            "walk_backward": ActionSpec(runner=wrap(lambda: walk_backward(self.my_dog, step_count=5, speed=100)), ensure_posture="standing", posture_after="standing"),
            "lie": ActionSpec(runner=wrap(lambda: lie_down(self.my_dog)), posture_after="sitting"),
            "stand": ActionSpec(runner=self._run_stand, posture_after="standing"),
            "sit": ActionSpec(runner=wrap(lambda: sit_down(self.my_dog)), posture_after="sitting"),
            "walk_left": ActionSpec(runner=wrap(lambda: turn_left(self.my_dog, step_count=5, speed=100)), ensure_posture="standing", posture_after="standing"),
            "walk_right": ActionSpec(runner=wrap(lambda: turn_right(self.my_dog, step_count=5, speed=100)), ensure_posture="standing", posture_after="standing"),
            "tilt_head_left": ActionSpec(runner=wrap(lambda: tilt_head_left(self.my_dog), sync_head=True)),
            "tilt_head_right": ActionSpec(runner=wrap(lambda: tilt_head_right(self.my_dog), sync_head=True)),
            "doze_off": ActionSpec(runner=wrap(lambda: doze_off(self.my_dog, speed=100)), posture_after="standing"),
        }

    async def _run_stand(self) -> None:
        current = getattr(self.state, "posture", None)
        if current == "sitting":
            sit_2_stand(self.my_dog)
        else:
            stand_up(self.my_dog)

    async def _execute_single_action(self, action: str) -> None:
        spec = self._action_specs.get(action)
        if not spec:
            print(f"[ActionManager] Unknown action: {action}")
            return

        old_posture = getattr(self.state, "posture", None)

        if spec.ensure_posture:
            await self._ensure_posture(spec.ensure_posture)

        await spec.runner()

        if spec.posture_after:
            self.state.posture = spec.posture_after

        if old_posture != self.state.posture:
            await self._update_posture_bias(old_posture, self.state.posture)

    def detect_petting_change(self):
        return self.sensors.detect_petting_change()

    def detect_sound_direction(self):
        return self.sensors.detect_sound_direction()

    def detect_sound_direction_change(self, client=None):
        # Don't detect sound direction when robot is talking (it's just our own voice!)
        if self.isTalkingMovement or self.isPlayingSound:
            return False
        return self.sensors.detect_sound_direction_change(client)

    async def detect_face_change(self):
        """Detects if a face is in front of the dog."""
        now = time.time()
        if now - getattr(self, "_last_face_check_time", 0.0) < self.face_detection_interval:
            return False
        self._last_face_check_time = now

        if self.face_tracker.enabled:
            detected = self.face_tracker.people_detected > 0
        else:
            detected = await is_person_detected()

        previous_present = getattr(self.state, "face_present", False)
        if detected:
            self.state.face_detected_at = now
            self.state.face_last_seen_at = now

        change = detected != previous_present
        if change:
            self.state.face_present = detected
            if not detected:
                # Face just disappeared; keep last_seen timestamp but clear active detection
                self.state.face_detected_at = None
            print(
                f"[DEBUG] Face presence changed -> detected={detected} last_seen={self.state.face_last_seen_at}"
            )
            self._last_face_log_state = detected
            return True

        if detected != getattr(self, "_last_face_log_state", None):
            print(
                f"[DEBUG] Face change detected: {detected}, last face seen at: {self.state.face_last_seen_at}"
            )
            self._last_face_log_state = detected

        return False
    

    def detect_orientation_change(self):
        return self.sensors.detect_orientation_change()

    def get_orientation_description(self):
        return self.sensors.get_orientation_description()

    def get_status(self):
        return self.status_reporter.detailed_status()

    def get_simple_status(self):
        return self.status_reporter.simple_status()

    async def take_photo(self, persona, question="", silent=False, client=None):
        """Capture an image and send to realtime API. Lightbar effect only (no sound)."""
    # New realtime image capture path (no legacy GPT vision call)
        self.isTakingAction = True
        image_path = None
        try:
            if not silent:
                self.lightbar.boom()
            image_path = capture_image()
            if client and image_path:
                await client.send_image_and_request_response(image_path)
            self.vision_description = "Image captured and sent." if image_path else "Image capture failed."
        except Exception as e:
            print(f"[ActionManager] Error taking photo: {e}")
            self.vision_description = "Error taking photo."
        finally:
            if not silent:
                self.lightbar.breath()
            self.isPlayingSound = False
            self.isTakingAction = False
        return self.vision_description

    async def perform_action(self, action_name):
        """Executes one or more PiDog actions by name (comma-separated)."""
        print(f"[ActionManager] Performing action(s): {action_name}")
        self.isTakingAction = True
        try:
            if not action_name:
                return

            actions = [a.strip() for a in action_name.split(',') if a.strip()]

            if len(actions) > 1:
                filtered_actions: list[str] = []
                for action in actions:
                    spec = self._action_specs.get(action)
                    if spec and spec.exclusive:
                        print(
                            f"[ActionManager] Skipping exclusive action '{action}' when combined with other commands."
                        )
                        continue
                    filtered_actions.append(action)

                if not filtered_actions:
                    print(
                        "[ActionManager] Ignoring combined request because all actions were exclusive-only."
                    )
                    return

                actions = filtered_actions

            for action in actions:
                try:
                    await self._execute_single_action(action)
                except Exception as e:
                    print(f"[ActionManager] Error during action '{action}': {e}")
        finally:
            self.my_dog.wait_all_done()
            self.isTakingAction = False

        print("[ActionManager] Done performing actions.")

    def lightbar_breath(self, color: str = "pink", bps: float = 0.5):
        self.lightbar.breath(color=color, bps=bps)

    async def power_up_sequence(self):  # Backwards compatibility wrapper
        await self.lightbar.power_up_sequence()

    def lightbar_boom(self, color: str = "blue"):
        self.lightbar.boom(color=color)

    def lightbar_bark(self):
        self.lightbar.bark()

    def set_lightbar_mode(
        self,
        style: str,
        color: str = "#ffffff",
        bps: float = 1.0,
        brightness: float = 1.0,
    ) -> None:
        print(
            f"[ActionManager] Setting lightbar mode: style={style}, color={color}, bps={bps}, brightness={brightness}"
        )
        self.lightbar.set_mode(style=style, color=color, bps=bps, brightness=brightness)

    def set_lightbar_direct(self, r: int, g: int, b: int, brightness: float = 1.0) -> None:
        self.lightbar.set_direct(r, g, b, brightness=brightness)
    
    async def start_talking(self):
        print(f"[ActionManager] Starting to talk... (isTalkingMovement: False -> True) at {time.time():.3f}")
        self.isTalkingMovement = True
        await self.head_controller.enable_talking()
        
        # Wire up amplitude callback if audio manager is available
        if hasattr(self, 'audio_manager') and self.audio_manager:
            self.head_controller.set_amplitude_callback(
                lambda: getattr(self.audio_manager, 'current_speech_amplitude', 0.0)
            )

    async def stop_talking(self):
        print(f"[ActionManager] Stop Talking... (isTalkingMovement: True -> False) at {time.time():.3f}")
        self.isTalkingMovement = False
        self.head_controller.set_amplitude_callback(None)  # Clear amplitude callback
        await self.head_controller.disable_talking()
        self.lightbar_breath()
        self.my_dog.body_stop()
        # Keep head oriented toward current target (face tracking or manual)

    async def interrupt_actions(self, *, reset_posture: bool = False) -> None:
        print(f"[ActionManager] Interrupting actions (reset_posture={reset_posture})")
        self.isTakingAction = False
        self.isPlayingSound = False
        try:
            self.my_dog.body_stop()
        except Exception as exc:
            print(f"[ActionManager] Error stopping body: {exc}")

        if self.isTalkingMovement:
            try:
                await self.stop_talking()
            except Exception as exc:
                print(f"[ActionManager] Error stopping talking movement: {exc}")

        if reset_posture:
            await self._reset_posture_after_interrupt()

    async def _reset_posture_after_interrupt(self) -> None:
        target_posture = getattr(self.state, "posture", "sitting") or "sitting"
        try:
            if target_posture == "standing":
                stand_up(self.my_dog)
            else:
                sit_down(self.my_dog)
        except Exception as exc:
            print(f"[ActionManager] Error resetting posture to '{target_posture}': {exc}")
        try:
            await self._sync_head_from_hardware(update_return=True)
        except Exception as exc:
            print(f"[ActionManager] Error syncing head pose after reset: {exc}")

    async def reset_head(self):
        await self._set_head_pose(yaw=0.0, pitch=0.0, roll=0.0)

    def get_available_actions(self):
        """Returns the list of all available actions the robot dog can perform."""
        return list(self._action_specs.keys())

    @asynccontextmanager
    async def _persona_transition(self, color: str, audio_file: Optional[str], volume: int = PERSONA_TRANSITION_VOLUME) -> AsyncIterator[None]:
        """Context manager for persona transitions with music playing in background."""
        print(f"[ActionManager] _persona_transition: Starting (color={color}, audio={audio_file})...")
        self.isTakingAction = True
        self.isPlayingSound = True
        self.lightbar_boom(color)
        
        # Start music playing in background (non-blocking)
        music = None
        if audio_file:
            print(f"[ActionManager] Starting background music: {audio_file}")
            music = self.speak(audio_file, volume)
        
        try:
            print("[ActionManager] _persona_transition: Yielding control...")
            yield
            print("[ActionManager] _persona_transition: Returned from yield, entering cleanup...")
        finally:
            print("[ActionManager] _persona_transition: In finally block...")
            # Stop music if still playing
            if music:
                try:
                    print("[ActionManager] Stopping persona transition music...")
                    music.music_stop()
                    print("[ActionManager] Music stopped successfully.")
                except Exception as stop_error:
                    print(f"[ActionManager] Error stopping persona audio: {stop_error}")
            print("[ActionManager] Resetting lightbar...")
            self.lightbar_breath()
            print("[ActionManager] Clearing action flags...")
            self.isTakingAction = False
            self.isPlayingSound = False
            print("[ActionManager] _persona_transition: Finally block complete.")

    async def create_new_persona_action(self, persona_description, client):
        """Handles the actions associated with creating and switching to a new persona.
        Creates a background task so it survives session reconnect (same pattern as persona switching)."""
        print(f"[ActionManager] Creating new persona: {persona_description}")
        
        if hasattr(self, '_persona_creation_task') and self._persona_creation_task and not self._persona_creation_task.done():
            print("[ActionManager] Cancelling existing persona creation task...")
            self._persona_creation_task.cancel()

        async def _perform_creation():
            new_persona = None
            try:
                print("[ActionManager] Entering persona transition context...")
                async with self._persona_transition("white", "audio/angelic_ascending.mp3"):
                    print("[ActionManager] Inside context, generating persona (music playing in background)...")
                    new_persona = await generate_persona(persona_description)
                    print(f"[ActionManager] Persona generated: {new_persona.get('name', 'Unknown') if new_persona else 'None'}")
                    
                    print("[ActionManager] Resetting state...")
                    self.reset_state_for_new_persona()
                    
                    print("[ActionManager] About to call reconnect...")
                    await client.reconnect(new_persona['name'], new_persona)
                    print("[ActionManager] Reconnect returned successfully.")
                
                print("[ActionManager] Exited persona transition context successfully.")
                # Check if new_persona was successfully created before accessing its name
                persona_name = new_persona.get('name', 'Unknown') if new_persona else 'Unknown'
                print(f"[ActionManager] Successfully created and switched to new persona: {persona_name}")
            except asyncio.CancelledError:
                print(f"[ActionManager] Persona creation task cancelled")
            except Exception as e:
                print(f"[ActionManager] ERROR in persona creation: {e}")
                import traceback
                traceback.print_exc()

        self._persona_creation_task = asyncio.create_task(_perform_creation())

    async def handle_persona_switch_effects(self, persona_name, client):
        """Handles the visual and audio effects during a persona switch."""
        print(f"[ActionManager] Handling persona switch effects for: {persona_name}")
        if self._persona_switch_task and not self._persona_switch_task.done():
            self._persona_switch_task.cancel()

        async def _perform_switch():
            try:
                async with self._persona_transition('green', "audio/angelic_short.mp3"):
                    self.reset_state_for_new_persona()
                    await client.reconnect(persona_name)
                    print(f"[ActionManager] Persona switch effects completed for: {persona_name}")
            except asyncio.CancelledError:
                print(f"[ActionManager] Persona switch task cancelled for: {persona_name}")
            except Exception as e:
                print(f"[ActionManager] Error during persona switch: {e}")

        self._persona_switch_task = asyncio.create_task(_perform_switch())


    async def detect_status(self, audio_manager, client):
        """
        Background task that detects changes in environment and updates the goal.
        Also periodically reminds the model of its default goal if it's been inactive.
        """
        is_change = False
        reminder_interval = 15  # seconds between spontaneous prompts when idle
        self.last_change_time = 0  # Track the last time a change was noticed
        # Backdate reminder timer so the first loop can trigger an immediate wake-up prompt once ready
        self.last_reminder_time = time.time() - reminder_interval
        
        while True:
            try:
                # print("Volume: ", audio_manager.latest_volume)
                # Detect individual changes
                petting_changed = self.detect_petting_change()
                sound_changed = self.detect_sound_direction_change(client)
                face_changed = await self.detect_face_change()
                orientation_changed = self.detect_orientation_change()

                # Combine for overall change
                is_change = petting_changed or sound_changed or face_changed or orientation_changed

                current_time = time.time()
                status_messages = []
                event_entries: list[tuple[str, str]] = []

                if petting_changed and getattr(self.state, "is_being_petted", False):
                    if self._allow_stimulus("petting", current_time):
                        event_entries.append(
                            (
                                "petting",
                                "You are being petted! You must say and do something in reaction to this.",
                            )
                        )

                # Sound direction: passive update, only force response if no speech detected
                if sound_changed:
                    direction = self.state.last_sound_direction or "an unknown direction"
                    if getattr(audio_manager, "latest_volume", 0) > 30:
                        message = f"A loud sound came from your {direction}. React, look that way, and respond."
                    else:
                        message = f"A quiet sound came from your {direction}. Still acknowledge it, look briefly that way, and respond."
                    
                    # Store as pending - will trigger only if no speech detected within SOUND_PASSIVE_WAIT
                    if self._allow_stimulus("sound", current_time):
                        self._pending_sound_stimulus = (current_time, direction, message)
                        print(f"[ActionManager] Sound detected from {direction} - waiting {SOUND_PASSIVE_WAIT}s to see if speech follows...")
                
                # Check if pending sound should trigger (no speech detected in time)
                if self._pending_sound_stimulus is not None:
                    pending_time, pending_dir, pending_msg = self._pending_sound_stimulus
                    if (current_time - pending_time) >= SOUND_PASSIVE_WAIT:
                        if not client.isDetectingUserSpeech and self._allow_stimulus("sound", current_time):
                            event_entries.append(("sound", pending_msg))
                            print(f"[ActionManager] No speech detected, triggering sound stimulus from {pending_dir}")
                        else:
                            print(f"[ActionManager] Speech detected, canceling sound stimulus from {pending_dir}")
                        self._pending_sound_stimulus = None

                if face_changed:
                    if self.state.face_present:
                        if self._allow_stimulus("face", current_time):
                            event_entries.append(
                                (
                                    "face",
                                    "A face is detected! You are looking "
                                    f"{self.state.head_pose.describe()}. You must say and do something in reaction to this.",
                                )
                            )
                    else:
                        status_messages.append("The face you were watching just disappeared.")

                if orientation_changed and self._allow_stimulus("orientation", current_time):
                    orientation_msg = self.state.last_orientation_description or "Your orientation changed."
                    event_entries.append(("orientation", f"{orientation_msg} You must act or speak in response."))

                if event_entries:
                    print(
                        "[ActionManager] Sensor change detected -> petting=%s sound=%s face=%s orientation=%s volume=%.1f direction=%s"
                        % (
                            petting_changed,
                            sound_changed,
                            face_changed,
                            orientation_changed,
                            getattr(audio_manager, "latest_volume", -1),
                            self.state.last_sound_direction or "unknown",
                        )
                    )

                # Update reminder time when actually busy (not just detecting speech)
                busy = (
                    self.isTalkingMovement
                    or self.isTakingAction
                    or self.isPlayingSound
                )
                model_active = client.isReceivingAudio or getattr(client, "has_active_response", False)
                if busy or model_active:
                    self.last_reminder_time = current_time

                if status_messages:
                    status_summary = " ".join(status_messages)
                    print(f"[ActionManager] Status notice (no forced response): {status_summary}")

                if event_entries:
                    event_keys = [key for key, _ in event_entries]
                    combined_event = " ".join(message for _, message in event_entries)
                    instruction_suffix = (
                        "React immediately to what you just noticed, in character. You will express how much you love or hate what happened."
                    )
                    full_instructions = f"{combined_event} {instruction_suffix}"
                    if self._can_send_stimulus(client):
                        print(
                            "[ActionManager] Forcing response due to stimulus -> message='%s'" % combined_event
                        )
                        await self._dispatch_stimulus(
                            client,
                            combined_event,
                            instructions=full_instructions,
                            title="Stimulus",
                            event_keys=event_keys,
                        )
                        self.last_change_time = current_time
                        self.last_reminder_time = current_time
                    else:
                        quiet_period = self.stimulus_quiet_period
                        quiet_ok = True
                        quiet_age = None
                        if hasattr(client, "is_quiet_for"):
                            quiet_ok = client.is_quiet_for(quiet_period)
                            if hasattr(client, "last_model_audio_time"):
                                last_activity = max(
                                    getattr(client, "last_model_audio_time", 0.0),
                                    getattr(client, "last_user_speech_time", 0.0),
                                    getattr(client, "last_response_created_time", 0.0),
                                )
                                if last_activity:
                                    quiet_age = time.time() - last_activity

                        blocking_flags = []
                        if self.isTalkingMovement:
                            blocking_flags.append("isTalkingMovement")
                        if self.isTakingAction:
                            blocking_flags.append("isTakingAction")
                        if self.isPlayingSound:
                            blocking_flags.append("isPlayingSound")
                        if self._wakeup_active:
                            blocking_flags.append("_wakeup_active")
                        if client.isReceivingAudio:
                            blocking_flags.append("client.isReceivingAudio")
                        if getattr(client, "_response_active", False):
                            blocking_flags.append("client._response_active")
                        if getattr(client, "has_active_response", False):
                            blocking_flags.append("client.has_active_response")
                        if getattr(client, "isDetectingUserSpeech", False):
                            blocking_flags.append("client.isDetectingUserSpeech")

                        print(
                            "[ActionManager] Stimulus ignored (busy or not quiet) -> talking=%s action=%s sound=%s receiving_audio=%s active_response=%s | quiet_ok=%s quiet_age=%.2fs (required %.1fs) | blocking=%s"
                            % (
                                self.isTalkingMovement,
                                self.isTakingAction,
                                self.isPlayingSound,
                                client.isReceivingAudio,
                                getattr(client, "has_active_response", False),
                                quiet_ok,
                                quiet_age if quiet_age is not None else -1.0,
                                quiet_period,
                                ", ".join(blocking_flags) if blocking_flags else "<none>",
                            )
                        )
                else:
                    # Check if we need to remind of default goal
                    elapsed_since_reminder = current_time - self.last_reminder_time
                    if (
                        not self.isTalkingMovement and
                        not self.isTakingAction and
                        not client.isReceivingAudio and
                        not client.isDetectingUserSpeech and
                        not getattr(client, "has_active_response", False) and
                        elapsed_since_reminder > reminder_interval and
                        client.persona is not None
                    ):
                        if client.first_response_event.is_set():
                            self._wakeup_active = True
                            try:
                                await self.perform_inline_photo(client)
                                await self.remind_of_default_goal(client)
                            finally:
                                self._wakeup_active = False
                            self.last_reminder_time = current_time
                        else:
                            print("[ActionManager] Skipping reminder until model speaks at least once.")
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
            default_motivation = client.persona.get(
                "default_motivation",
                "Take a moment to stretch, relax, or look around.",
            )
            self.state.goal = default_motivation
            reminder_message = (
                f"Reminder: {default_motivation}"
                f" Current head pose: {self.state.head_pose.describe()}."
            )
            print(f"[ActionManager] Default goal reminder: {reminder_message}")
            await self._notify_stimulus(
                client,
                reminder_message,
                instructions=(
                    "Check in with your surroundings, describe what you see, and consider doing something relaxing."
                ),
                title="Reminder",
            )
            await client.send_awareness()
        except Exception as e:
            print(f"[ActionManager::remind_of_default_goal] Error: {e}")






