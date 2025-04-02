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

    def __str__(self):
        return (f"State:\n"
                f"  Volume of your voice: {self.volume} (0.0-3.0)\n"
                f"  Current Goal: {self.goal}\n"
                f"  Face Detected At: {self.face_detected_at}\n"
                f"  Last Sound Direction: {self.last_sound_direction}")