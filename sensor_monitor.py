import math
import time
from typing import Optional

from actions import (
    attack_posture,
    head_up_down,
    tilt_head_left,
    tilt_head_right,
    wag_tail,
)
from state_manager import RobotDogState


class SensorMonitor:
    """Aggregates low-level sensor reads and interpretations."""

    def __init__(self, dog, state: RobotDogState) -> None:
        self._dog = dog
        self._state = state
        self._sound_debounce_time = 2.0  # Don't report sound changes more often than this
        self._last_sound_report_time = 0.0

    def detect_petting_change(self) -> bool:
        status = self._dog.dual_touch.read()
        now = time.time()

        was_petted = getattr(self._state, "is_being_petted", False)
        is_petted = status != "N"

        if is_petted:
            self._state.petting_detected_at = now
        self._state.is_being_petted = is_petted

        changed = is_petted and not was_petted

        return changed

    def detect_sound_direction(self) -> Optional[str]:
        if not self._dog.ears.isdetected():
            return None

        direction = self._dog.ears.read()
        ranges = [
            ((337.5, 360), "front"),
            ((0, 22.5), "front"),
            ((22.5, 67.5), "front right"),
            ((67.5, 112.5), "right"),
            ((112.5, 157.5), "back right"),
            ((157.5, 202.5), "back"),
            ((202.5, 247.5), "back left"),
            ((247.5, 292.5), "left"),
            ((292.5, 337.5), "front left"),
        ]

        for (low, high), label in ranges:
            if low <= direction < high:
                return label

        return "unknown"

    def detect_sound_direction_change(self, client=None) -> bool:
        """Detect sound direction changes with debouncing and voice activity awareness.
        
        Args:
            client: Optional realtime client to check voice activity state
            
        Returns:
            True if sound direction changed and should be reported
        """
        if not self._dog.ears.isdetected():
            return False
        
        # Don't interrupt if user is speaking or model is responding
        if client:
            if client.isDetectingUserSpeech:
                return False
            if client.isReceivingAudio:
                return False
            if getattr(client, '_response_active', False):
                return False
        
        # Time-based debounce - don't report too frequently
        now = time.time()
        if (now - self._last_sound_report_time) < self._sound_debounce_time:
            return False

        current_direction = self.detect_sound_direction()
        if current_direction and self._state.last_sound_direction != current_direction:
            self._state.last_sound_direction = current_direction
            self._last_sound_report_time = now
            print(
                f"[SensorMonitor] Sound direction change detected -> direction={current_direction}"
            )
            return True
        return False

    def detect_orientation_change(self) -> bool:
        description = self.get_orientation_description()
        if self._state.last_orientation_description is None:
            self._state.last_orientation_description = description
            return False

        if description != self._state.last_orientation_description:
            self._state.last_orientation_description = description
            print(f"[SensorMonitor] Orientation change detected: {description}")
            return True
        return False

    def get_orientation_description(self) -> str:
        ax, ay, az = self._dog.accData

        body_pitch = math.atan2(ay, math.sqrt(ax**2 + az**2)) * 180 / math.pi
        body_roll = math.atan2(-ax, az) * 180 / math.pi

        if body_roll <= -80:
            return "You are upside down!"
        if -40 <= body_pitch <= 15:
            if 65 <= body_roll <= 105:
                return "You are upright."
            if 155 <= abs(body_roll) <= 190:
                return "You are on your left side!" if body_roll > 0 else "You are on your right side!"
        if body_pitch >= 75:
            return "You are hanging by your tail!"
        if body_pitch <= -75:
            return "You are hanging by your nose!"

        return "The dog's orientation is unclear."

    