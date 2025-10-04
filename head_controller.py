import asyncio
import math
from typing import Callable, Optional

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
            "yaw_amp": 3.5,      # Horizontal head shake - reduced
            "pitch_amp": 4.0,    # Vertical nod - reduced  
            "roll_amp": 1.5,     # Head tilt - reduced
            "frequency": 0.9,    # Slower, more natural base speed
        }
        
        # Amplitude-based motion scaling
        self._amplitude_callback: Optional[Callable[[], float]] = None
        self._amp_scale_min = 0.4  # Minimum motion scale even when quiet
        self._amp_scale_max = 1.0  # Maximum motion scale at full volume
        self._amp_threshold = 0.05  # Amplitude below this = no motion
        self._phase_accum = 0.0  # Phase accumulator driven by amplitude

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
            self._phase_accum = 0.0  # Reset phase for next talking session

    async def _talk_loop(self) -> None:
        try:
            last_time = asyncio.get_running_loop().time()
            while True:
                async with self._lock:
                    if not self._talk_enabled:
                        break
                    params = dict(self._talk_params)
                    amp_threshold = self._amp_threshold
                
                # Get current amplitude
                raw_amp = 0.0
                if self._amplitude_callback:
                    try:
                        raw_amp = self._amplitude_callback()
                    except Exception:
                        pass
                
                # If no callback, use default behavior (always move)
                if not self._amplitude_callback:
                    raw_amp = 1.0
                
                now = asyncio.get_running_loop().time()
                dt = now - last_time
                last_time = now
                
                # Advance phase when amplitude is above threshold
                if raw_amp > amp_threshold:
                    # Constant frequency for smooth, predictable motion
                    self._phase_accum += 2 * math.pi * params["frequency"] * dt
                    
                    # Map amplitude to motion scale with smoother curve
                    # Use power curve for more natural response
                    amp_normalized = max(0.0, min(1.0, raw_amp))
                    amp_scale = self._amp_scale_min + (self._amp_scale_max - self._amp_scale_min) * (amp_normalized ** 0.7)
                    
                    # Use single phase for coordinated, organic motion
                    # Different frequency ratios create natural head movement
                    phase = self._phase_accum
                    offset = HeadPose(
                        yaw=params["yaw_amp"] * amp_scale * math.sin(phase * 0.7),           # Slower yaw
                        pitch=params["pitch_amp"] * amp_scale * math.sin(phase * 1.0),       # Primary rhythm
                        roll=params["roll_amp"] * amp_scale * math.sin(phase * 1.3),         # Faster roll for interest
                    )
                else:
                    # No amplitude = no motion (smoothly return to neutral)
                    offset = HeadPose()
                
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
    
    def set_amplitude_callback(self, callback: Optional[Callable[[], float]]) -> None:
        """Set callback to get current speech amplitude (0.0-1.0) for motion scaling."""
        self._amplitude_callback = callback
    
    def set_amplitude_scale_range(self, min_scale: float = 0.4, max_scale: float = 1.0) -> None:
        """Set the range for amplitude-based motion scaling."""
        self._amp_scale_min = max(0.0, min(min_scale, 1.0))
        self._amp_scale_max = max(self._amp_scale_min, min(max_scale, 1.0))
    
    def set_amplitude_threshold(self, threshold: float = 0.05) -> None:
        """Set amplitude threshold below which motion pauses (0.0-1.0)."""
        self._amp_threshold = max(0.0, min(threshold, 1.0))