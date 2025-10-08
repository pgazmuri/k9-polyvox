from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


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


@dataclass
class InteractionState:
    goal: str = "You just woke up"
    pending_stimulus: Optional[str] = None


@dataclass
class AudioState:
    volume: float = 1.0


@dataclass
class PerceptionState:
    face_present: bool = False
    face_detected_at: Optional[float] = None
    face_last_seen_at: Optional[float] = None
    last_sound_direction: Optional[str] = None
    last_orientation_description: Optional[str] = None
    is_being_petted: bool = False
    petting_detected_at: Optional[float] = None


@dataclass
class MotionState:
    posture: str = "sitting"
    head_pose: HeadPose = field(default_factory=HeadPose)


@dataclass
class MetaState:
    last_awareness_event_time: Optional[float] = None
    current_action: Optional[str] = None
    last_action: Optional[str] = None


class RobotState:
    """Centralized robot state container with compatibility aliases for legacy code."""

    def __init__(self) -> None:
        self.audio = AudioState()
        self.interaction = InteractionState()
        self.perception = PerceptionState()
        self.motion = MotionState()
        self.meta = MetaState()

    # ------------------------------------------------------------------
    # Compatibility shims
    # ------------------------------------------------------------------
    @property
    def volume(self) -> float:
        return self.audio.volume

    @volume.setter
    def volume(self, value: float) -> None:
        try:
            self.audio.volume = float(value)
        except (TypeError, ValueError):
            raise ValueError("Volume must be numeric")

    @property
    def goal(self) -> str:
        return self.interaction.goal

    @goal.setter
    def goal(self, value: str) -> None:
        self.interaction.goal = value

    @property
    def pending_stimulus(self) -> Optional[str]:
        return self.interaction.pending_stimulus

    @pending_stimulus.setter
    def pending_stimulus(self, value: Optional[str]) -> None:
        self.interaction.pending_stimulus = value

    @property
    def last_awareness_event_time(self) -> Optional[float]:
        return self.meta.last_awareness_event_time

    @last_awareness_event_time.setter
    def last_awareness_event_time(self, value: Optional[float]) -> None:
        self.meta.last_awareness_event_time = value

    @property
    def face_detected_at(self) -> Optional[float]:
        return self.perception.face_detected_at

    @face_detected_at.setter
    def face_detected_at(self, value: Optional[float]) -> None:
        self.perception.face_detected_at = value

    @property
    def petting_detected_at(self) -> Optional[float]:
        return self.perception.petting_detected_at

    @petting_detected_at.setter
    def petting_detected_at(self, value: Optional[float]) -> None:
        self.perception.petting_detected_at = value

    @property
    def is_being_petted(self) -> bool:
        return self.perception.is_being_petted

    @is_being_petted.setter
    def is_being_petted(self, value: bool) -> None:
        self.perception.is_being_petted = bool(value)

    @property
    def last_sound_direction(self) -> Optional[str]:
        return self.perception.last_sound_direction

    @last_sound_direction.setter
    def last_sound_direction(self, value: Optional[str]) -> None:
        self.perception.last_sound_direction = value

    @property
    def last_orientation_description(self) -> Optional[str]:
        return self.perception.last_orientation_description

    @last_orientation_description.setter
    def last_orientation_description(self, value: Optional[str]) -> None:
        self.perception.last_orientation_description = value

    @property
    def posture(self) -> str:
        return self.motion.posture

    @posture.setter
    def posture(self, value: str) -> None:
        self.motion.posture = value

    @property
    def head_pose(self) -> HeadPose:
        return self.motion.head_pose

    @head_pose.setter
    def head_pose(self, value: HeadPose) -> None:
        if not isinstance(value, HeadPose):
            raise TypeError("head_pose must be a HeadPose instance")
        self.motion.head_pose = value

    @property
    def face_present(self) -> bool:
        return self.perception.face_present

    @face_present.setter
    def face_present(self, value: bool) -> None:
        self.perception.face_present = bool(value)

    @property
    def face_last_seen_at(self) -> Optional[float]:
        return self.perception.face_last_seen_at

    @face_last_seen_at.setter
    def face_last_seen_at(self, value: Optional[float]) -> None:
        self.perception.face_last_seen_at = value

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Restore state to default values."""
        self.audio = AudioState()
        self.interaction = InteractionState()
        self.perception = PerceptionState()
        self.motion = MotionState()
        self.meta = MetaState()

    def snapshot(self) -> Dict[str, Any]:
        """Return a structured snapshot suitable for serialization."""
        return {
            "audio": asdict(self.audio),
            "interaction": asdict(self.interaction),
            "perception": asdict(self.perception),
            "motion": {
                **asdict(self.motion),
                "head_pose_description": self.motion.head_pose.describe(),
            },
            "meta": asdict(self.meta),
        }

    def __str__(self) -> str:
        return (
            "State:\n"
            f"  Volume of your voice: {self.volume} (0.0-3.0)\n"
            f"  Current Goal: {self.goal}\n"
            f"  Face Detected At: {self.face_detected_at}\n"
            f"  Last Sound Direction: {self.last_sound_direction}\n"
            f"  Head Pose: {self.head_pose.describe()}"
        )


# Backwards compatibility alias
RobotDogState = RobotState
