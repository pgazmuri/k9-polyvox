import asyncio
import math
from typing import Optional

from state_manager import HeadPose


class HeadController:
    """Coordinates PiDog head orientation with support for talk offsets and posture bias."""

    def __init__(
        self,
        my_dog,
        *,
        yaw_limits: tuple[float, float] = (-80.0, 80.0),
        pitch_limits: tuple[float, float] = (-35.0, 35.0),
        roll_limits: tuple[float, float] = (-35.0, 35.0),
        update_interval: float = 0.05,
        speed: int = 95,
    ) -> None:
        self.my_dog = my_dog
        self.yaw_limits = yaw_limits
        self.pitch_limits = pitch_limits
        self.roll_limits = roll_limits
        self.update_interval = update_interval
        self.speed = speed

        self._base_pose = HeadPose()
        self._bias_pose = HeadPose()
        self._talk_offset = HeadPose()
        self._last_command: Optional[HeadPose] = None

        self._lock = asyncio.Lock()
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None

        self._talk_enabled = False
        self._talk_task: Optional[asyncio.Task] = None
        self._talk_params = {
            "yaw_amp": 4.0,
            "pitch_amp": 3.5,
            "roll_amp": 1.5,
            "frequency": 1.4,
        }

    # ------------------------------------------------------------------
    # Lifecycle control
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        loop = asyncio.get_running_loop()
        self._loop_task = loop.create_task(self._run_loop())

    async def stop(self) -> None:
        await self.disable_talking()
        if not self._running:
            return
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

    # ------------------------------------------------------------------
    # Pose management
    # ------------------------------------------------------------------
    async def set_pose(self, *, yaw: Optional[float] = None, pitch: Optional[float] = None, roll: Optional[float] = None) -> None:
        async with self._lock:
            if yaw is not None:
                self._base_pose.yaw = float(yaw)
            if pitch is not None:
                self._base_pose.pitch = float(pitch)
            if roll is not None:
                self._base_pose.roll = float(roll)

    async def adjust_pose(self, *, delta_yaw: float = 0.0, delta_pitch: float = 0.0, delta_roll: float = 0.0) -> HeadPose:
        async with self._lock:
            self._base_pose.yaw += delta_yaw
            self._base_pose.pitch += delta_pitch
            self._base_pose.roll += delta_roll
            return self._base_pose.copy()

    async def sync_with_hardware(self) -> HeadPose:
        yaw, roll, pitch = self.my_dog.head_current_angles
        async with self._lock:
            self._base_pose = HeadPose(
                yaw=yaw - self._bias_pose.yaw,
                pitch=pitch - self._bias_pose.pitch,
                roll=roll - self._bias_pose.roll,
            )
            return self._base_pose.copy()

    async def set_posture_bias(self, *, pitch_bias: float = 0.0) -> None:
        async with self._lock:
            actual_pitch = self._base_pose.pitch + self._bias_pose.pitch
            self._bias_pose.pitch = pitch_bias
            self._base_pose.pitch = actual_pitch - pitch_bias

    def current_pose(self) -> HeadPose:
        return self._base_pose.copy()

    # ------------------------------------------------------------------
    # Talking offsets
    # ------------------------------------------------------------------
    async def enable_talking(self) -> None:
        async with self._lock:
            if self._talk_enabled:
                return
            self._talk_enabled = True
        loop = asyncio.get_running_loop()
        self._talk_task = loop.create_task(self._talk_loop())

    async def disable_talking(self) -> None:
        async with self._lock:
            self._talk_enabled = False
        if self._talk_task:
            self._talk_task.cancel()
            try:
                await self._talk_task
            except asyncio.CancelledError:
                pass
            self._talk_task = None
        async with self._lock:
            self._talk_offset = HeadPose()

    async def _talk_loop(self) -> None:
        try:
            start = asyncio.get_running_loop().time()
            while True:
                async with self._lock:
                    if not self._talk_enabled:
                        break
                    params = dict(self._talk_params)
                now = asyncio.get_running_loop().time()
                t = now - start
                offset = HeadPose(
                    yaw=params["yaw_amp"] * math.sin(2 * math.pi * params["frequency"] * 0.8 * t),
                    pitch=params["pitch_amp"] * math.sin(2 * math.pi * params["frequency"] * t + math.pi / 4),
                    roll=params["roll_amp"] * math.sin(2 * math.pi * params["frequency"] * 1.3 * t),
                )
                async with self._lock:
                    if not self._talk_enabled:
                        break
                    self._talk_offset = offset
                await asyncio.sleep(self.update_interval)
        except asyncio.CancelledError:
            pass
        finally:
            async with self._lock:
                self._talk_offset = HeadPose()

    # ------------------------------------------------------------------
    # Internal update loop
    # ------------------------------------------------------------------
    async def _run_loop(self) -> None:
        try:
            while self._running:
                await self._apply_current_pose()
                await asyncio.sleep(self.update_interval)
        except asyncio.CancelledError:
            pass

    async def _apply_current_pose(self) -> None:
        async with self._lock:
            pose = HeadPose(
                yaw=self._base_pose.yaw + self._bias_pose.yaw + self._talk_offset.yaw,
                pitch=self._base_pose.pitch + self._bias_pose.pitch + self._talk_offset.pitch,
                roll=self._base_pose.roll + self._bias_pose.roll + self._talk_offset.roll,
            )
        pose = pose.clamp(self.yaw_limits, self.pitch_limits, self.roll_limits)
        if not self._should_send(pose):
            return
        try:
            self.my_dog.head_move_raw([[pose.yaw, pose.roll, pose.pitch]], immediately=True, speed=self.speed)
            self._last_command = pose
        except Exception as exc:
            print(f"[HeadController] Failed to apply head pose: {exc}")

    def _should_send(self, pose: HeadPose, threshold: float = 0.4) -> bool:
        if self._last_command is None:
            return True
        diff_yaw = abs(pose.yaw - self._last_command.yaw)
        diff_pitch = abs(pose.pitch - self._last_command.pitch)
        diff_roll = abs(pose.roll - self._last_command.roll)
        return diff_yaw > threshold or diff_pitch > threshold or diff_roll > threshold

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------
    async def home(self) -> None:
        await self.set_pose(yaw=0.0, pitch=0.0, roll=0.0)

    async def set_speed(self, speed: int) -> None:
        self.speed = speed

    async def set_talk_profile(self, *, yaw_amp: float | None = None, pitch_amp: float | None = None,
                               roll_amp: float | None = None, frequency: float | None = None) -> None:
        async with self._lock:
            if yaw_amp is not None:
                self._talk_params["yaw_amp"] = yaw_amp
            if pitch_amp is not None:
                self._talk_params["pitch_amp"] = pitch_amp
            if roll_amp is not None:
                self._talk_params["roll_amp"] = roll_amp
            if frequency is not None:
                self._talk_params["frequency"] = frequency