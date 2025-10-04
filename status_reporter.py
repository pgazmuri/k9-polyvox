import math
import time
from typing import List

import psutil

from sensor_monitor import SensorMonitor
from state_manager import RobotDogState


class StatusReporter:
    """Builds textual summaries of robot state and system metrics."""

    def __init__(self, dog, state: RobotDogState, sensors: SensorMonitor) -> None:
        self._dog = dog
        self._state = state
        self._sensors = sensors

    def detailed_status(self) -> str:
        parts: List[str] = []

        parts.append(f"Current Goal: {self._state.goal}")

        if self._dog.dual_touch.read() != "N":
            parts.append("Someone is petting my head RIGHT NOW!")
        elif self._state.petting_detected_at and time.time() - self._state.petting_detected_at < 10:
            parts.append("Someone petted my head recently!")

        face_present = getattr(self._state, "face_present", False)
        last_seen = getattr(self._state, "face_last_seen_at", None)
        if face_present:
            parts.append("Someone is in front of you right now!")
        elif last_seen and (time.time() - last_seen < 10):
            delta = time.time() - last_seen
            parts.append(f"A person was here {delta:.1f} seconds ago.")
        else:
            parts.append("No person detected recently.")

        parts.append(f"Posture: {self._state.posture}")
        parts.append(f"Head Pose: {self._state.head_pose.describe()}")

        voltage = self._dog.get_battery_voltage()
        parts.append(f"Battery Voltage: {voltage:.2f}V (7.6 is nominal)")

        ax, ay, az = self._dog.accData
        gx, gy, gz = self._dog.gyroData

        body_pitch = math.atan2(ay, math.sqrt(ax**2 + az**2)) * 180 / math.pi
        body_roll = math.atan2(-ax, az) * 180 / math.pi

        dt = 0.01
        if not hasattr(self, "_yaw_angle"):
            self._yaw_angle = 0.0
        self._yaw_angle += gz * dt
        body_yaw = self._yaw_angle

        parts.append(f"Body Pitch: {body_pitch:.2f}°")
        parts.append(f"Body Roll: {body_roll:.2f}°")
        parts.append(f"Body Yaw: {body_yaw:.2f}°")

        orientation_desc = (
            self._state.last_orientation_description
            if self._state.last_orientation_description
            else self._sensors.get_orientation_description()
        )
        parts.append(f"Your orientation: {orientation_desc}")

        parts.append(f"Gyro Angular Velocity: gx={gx:.2f}, gy={gy:.2f}, gz={gz:.2f}")

        try:
            distance = round(self._dog.distance, 2)
            parts.append(f"Space in front of you: {distance} cm (ultrasonic distance)")
        except AttributeError:
            parts.append("Ultrasonic sensor is not functional or not initialized.")
        except Exception as exc:  # pragma: no cover - hardware specific
            parts.append(f"Error reading ultrasonic sensor: {exc}")

        last_sound = self._state.last_sound_direction or "None detected yet"
        parts.append(f"Last Sound Direction: {last_sound}")

        cpu_usage = psutil.cpu_percent(interval=None)
        memory_info = psutil.virtual_memory()
        disk_info = psutil.disk_usage("/")
        top_processes = sorted(
            psutil.process_iter(["pid", "name", "cpu_percent"]),
            key=lambda proc: proc.info["cpu_percent"],
            reverse=True,
        )[:5]

        parts.append(f"CPU Usage: {cpu_usage}%")
        parts.append(f"Memory Usage: {memory_info.percent}%")
        parts.append(f"Disk Usage: {disk_info.percent}%")

        top_info = ", ".join(
            [
                f"{proc.info['name']} (PID {proc.info['pid']}): {proc.info['cpu_percent']}%"
                for proc in top_processes
            ]
        )
        parts.append(f"Top Processes: {top_info}")

        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        uptime_string = time.strftime("%H:%M:%S", time.gmtime(uptime_seconds))
        parts.append(f"Uptime: {uptime_string}")

        return ". ".join(parts) + "."

    def simple_status(self) -> str:
        parts: List[str] = []

        parts.append(f"Current Goal: {self._state.goal}")

        if self._dog.dual_touch.read() != "N":
            parts.append("Someone is petting my head RIGHT NOW!")
        elif self._state.petting_detected_at:
            elapsed = time.time() - self._state.petting_detected_at
            parts.append(f"Last petting was {elapsed:.1f} seconds ago.")
        else:
            parts.append("No petting detected yet.")

        if getattr(self._state, "face_present", False):
            parts.append("A face is in view right now.")
        elif getattr(self._state, "face_last_seen_at", None):
            elapsed = time.time() - self._state.face_last_seen_at
            parts.append(f"Last face detected {elapsed:.1f} seconds ago.")
        else:
            parts.append("No face detected yet.")

        parts.append(f"Posture: {self._state.posture}")
        parts.append(f"Head Pose: {self._state.head_pose.describe()}")

        last_sound = self._state.last_sound_direction or "None detected yet"
        parts.append(f"Last Sound Direction: {last_sound}")

        return "\n".join(parts)
