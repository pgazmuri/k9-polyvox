import math
import os
import time
from typing import Optional, TYPE_CHECKING

from realtime_client import RealtimeClient

from actions import (
    attack_posture,
    head_up_down,
    tilt_head_left,
    tilt_head_right,
    wag_tail,
)
from state_manager import RobotDogState


if TYPE_CHECKING:
    from audio_manager import AudioManager
    from pidog import Pidog


class SensorMonitor:
    """Aggregates low-level sensor reads and interpretations."""

    def __init__(self, dog: "Pidog", state: RobotDogState) -> None:
        self._dog: "Pidog" = dog
        self._state = state
        self._sound_debounce_time = 2.0  # Don't report sound changes more often than this
        self._last_sound_report_time = 0.0
        self._sound_volume_threshold = float(os.environ.get("SOUND_DIRECTION_VOLUME_THRESHOLD", "45"))
        self._playback_grace_period = float(os.environ.get("SOUND_PLAYBACK_GRACE_PERIOD", "0.25"))
        self._sound_debug_logging = os.environ.get("SOUND_DETECTION_DEBUG", "0") == "1"

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

    def detect_sound_direction_change(
        self,
        client: Optional[RealtimeClient] = None,
        audio_manager: Optional["AudioManager"] = None,
    ) -> bool:
        """Detect sound direction changes with debouncing and voice activity awareness.
        
        Args:
            client: Optional realtime client to check voice activity state
            
        Returns:
            True if sound direction changed and should be reported
        """
        now = time.time()
        if not self._dog.ears.isdetected():
            return False
        
        # Avoid reacting while the robot is speaking or recently spoke
        if audio_manager:
            playback_active = audio_manager.is_playback_active()
            if playback_active:
                if self._sound_debug_logging:
                    print("[SensorMonitor] Skipping sound detection: playback active.")
                return False
            playback_recent = audio_manager.playback_recently_active(self._playback_grace_period)
            if playback_recent:
                if self._sound_debug_logging:
                    last_end = audio_manager.get_last_playback_end_time()
                    since_end = now - last_end if last_end > 0.0 else None
                    if since_end is not None:
                        print(
                            f"[SensorMonitor] Skipping sound detection: playback ended {since_end:.3f}s ago (grace {self._playback_grace_period}s)."
                        )
                    else:
                        print(
                            f"[SensorMonitor] Skipping sound detection: playback recently active (grace {self._playback_grace_period}s)."
                        )
                return False

        # Don't interrupt if user is speaking or model is responding
        if client:
            if client.isDetectingUserSpeech:
                return False
            if client.isReceivingAudio:
                return False
            if getattr(client, '_response_active', False):
                return False

        measured_volume: Optional[float] = None
        if audio_manager:
            measured_volume = audio_manager.get_recent_peak_volume()
            if self._sound_debug_logging and measured_volume is not None:
                avg_volume = audio_manager.get_recent_average_volume()
                avg_text = f"{avg_volume:.1f}" if avg_volume is not None else "n/a"
                print(
                    f"[SensorMonitor] Volume window check -> peak={measured_volume:.1f}, avg={avg_text}, threshold={self._sound_volume_threshold}."
                )
        elif client and hasattr(client, "audio_manager"):
            manager = getattr(client, "audio_manager")
            measured_volume = getattr(manager, "get_recent_peak_volume", lambda: 0.0)()

        if measured_volume is not None and measured_volume < self._sound_volume_threshold:
            if self._sound_debug_logging:
                print(
                    f"[SensorMonitor] Volume {measured_volume:.1f} below threshold {self._sound_volume_threshold}; ignoring sound direction change."
                )
            return False
        
        # Time-based debounce - don't report too frequently
        if (now - self._last_sound_report_time) < self._sound_debounce_time:
            if self._sound_debug_logging:
                wait_remaining = self._sound_debounce_time - (now - self._last_sound_report_time)
                print(
                    f"[SensorMonitor] Debounce active for another {wait_remaining:.3f}s; ignoring sound direction change."
                )
            return False

        current_direction = self.detect_sound_direction()
        if current_direction and self._state.last_sound_direction != current_direction:
            self._state.last_sound_direction = current_direction
            if measured_volume is not None:
                setattr(self._state, "last_sound_volume", measured_volume)
            self._last_sound_report_time = now
            vol_text = f"{measured_volume:.1f}" if measured_volume is not None else "n/a"
            print(
                f"[SensorMonitor] Sound direction change detected -> direction={current_direction} (peak={vol_text})"
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

    