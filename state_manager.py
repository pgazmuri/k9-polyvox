from dataclasses import dataclass


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
        """Return a concise textual description plus numeric angles."""
        yaw_threshold = 12.0
        pitch_threshold = 10.0
        roll_threshold = 12.0

        # Determine yaw direction (left/right)
        if self.yaw > yaw_threshold:
            yaw_dir = "left"
        elif self.yaw < -yaw_threshold:
            yaw_dir = "right"
        else:
            yaw_dir = "forward"

        # Determine pitch direction (up/down)
        if self.pitch > pitch_threshold:
            pitch_dir = "up"
        elif self.pitch < -pitch_threshold:
            pitch_dir = "down"
        else:
            pitch_dir = "level"

        # Build combined facing string
        if yaw_dir == "forward" and pitch_dir == "level":
            direction = "forward"
        elif yaw_dir == "forward":
            direction = pitch_dir
        elif pitch_dir == "level":
            direction = yaw_dir
        else:
            direction = f"{pitch_dir}-{yaw_dir}"

        # Note roll if beyond threshold
        roll_note = ""
        if self.roll > roll_threshold:
            roll_note = " (tilted left)"
        elif self.roll < -roll_threshold:
            roll_note = " (tilted right)"

        return (f"direction={direction}{roll_note} | "
                f"yaw={self.yaw:.1f}°, pitch={self.pitch:.1f}°, roll={self.roll:.1f}°")


class RobotDogState:
    def __init__(self):
        # State attributes
        self.volume = 1  # Volume level (0-3)
        self.face_detected_at = None  # Timestamp of the last detected face
        self.petting_detected_at = None  # Timestamp of the last pet
        self.last_sound_direction = None  # Direction of the last detected sound
        self.last_orientation_description = None  # Description of the last detected position
        self.goal = "You just woke up"
        self.last_awareness_event_time = None  # Timestamp of the last awareness event
        self.posture = "sitting"  # sitting | standing
        self.head_pose = HeadPose()

    def __str__(self):
        return (f"State:\n"
                f"  Volume of your voice: {self.volume} (0.0-3.0)\n"
                f"  Current Goal: {self.goal}\n"
                f"  Face Detected At: {self.face_detected_at}\n"
                f"  Last Sound Direction: {self.last_sound_direction}\n"
                f"  Head Pose: {self.head_pose.describe()}")
