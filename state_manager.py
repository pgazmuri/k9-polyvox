from dataclasses import dataclass
from typing import Optional


@dataclass
class HeadPose:
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0

    def copy(self) -> "HeadPose":
        return HeadPose(self.yaw, self.pitch, self.roll)

    def clamp(self,
              yaw_limits: tuple[float, float] = (-80.0, 80.0),
              pitch_limits: tuple[float, float] = (-35.0, 35.0),
              roll_limits: tuple[float, float] = (-35.0, 35.0)) -> "HeadPose":
        """Return a new pose with each axis clamped to supplied limits."""
        return HeadPose(
            yaw=min(max(self.yaw, yaw_limits[0]), yaw_limits[1]),
            pitch=min(max(self.pitch, pitch_limits[0]), pitch_limits[1]),
            roll=min(max(self.roll, roll_limits[0]), roll_limits[1]),
        )

    def describe(self) -> str:
        yaw = self.yaw
        pitch = self.pitch
        roll = self.roll

        def _dir(value: float, pos_label: str, neg_label: str, threshold: float = 8.0) -> Optional[str]:
            if value > threshold:
                return pos_label
            if value < -threshold:
                return neg_label
            return None

        pitch_dir = _dir(pitch, "up", "down")
        yaw_dir = _dir(yaw, "to the left", "to the right")
        components = [c for c in (pitch_dir, yaw_dir) if c]
        if components:
            direction_desc = " and ".join(components)
        else:
            direction_desc = "straight ahead"

        roll_desc = _dir(roll, "tilted toward the left ear", "tilted toward the right ear")
        orientation_parts = [f"looking {direction_desc}"]
        if roll_desc:
            orientation_parts.append(roll_desc)
        orientation = "; ".join(orientation_parts)

        return (
            f"yaw={yaw:.1f}°, pitch={pitch:.1f}°, roll={roll:.1f}° "
            f"({orientation})"
        )


class RobotDogState:
    def __init__(self):
        self.reset()

    def __str__(self):
        return (f"State:\n"
                f"  Volume of your voice: {self.volume} (0.0-3.0)\n"
                f"  Current Goal: {self.goal}\n"
                f"  Face Detected At: {self.face_detected_at}\n"
                f"  Last Sound Direction: {self.last_sound_direction}\n"
                f"  Head Pose: {self.head_pose.describe()}")

    def reset(self) -> None:
        self.volume = 1
        self.face_detected_at = None
        self.petting_detected_at = None
        self.is_being_petted = False
        self.last_sound_direction = None
        self.last_orientation_description = None
        self.goal = "You just woke up"
        self.last_awareness_event_time = None
        self.posture = "sitting"
        self.head_pose = HeadPose()
        self.face_present = False
        self.face_last_seen_at = None
        self.pending_stimulus = None
