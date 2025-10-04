import asyncio
import math
import time
from typing import Optional

from vilib import Vilib

from head_pose_manager import HeadPoseManager
from state_manager import RobotDogState


class FaceTracker:
    """Handles asynchronous face tracking and head recentering."""

    def __init__(
        self,
        head_pose: HeadPoseManager,
        state: RobotDogState,
        *,
        camera_width: float,
        camera_height: float,
        update_interval: float,
        recenter_timeout: float,
        recenter_step: float,
        enabled: bool,
    ) -> None:
        self._head_pose = head_pose
        self._state = state
        self._camera_width = camera_width
        self._camera_height = camera_height
        self._update_interval = update_interval
        self._recenter_timeout = recenter_timeout
        self._recenter_step = recenter_step
        self._enabled = enabled

        self._people: int = 0
        self._last_seen: float = 0.0
        self._active: bool = False
        self._task: Optional[asyncio.Task] = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def people_detected(self) -> int:
        return self._people

    async def start(self) -> None:
        if not self._enabled or (self._task and not self._task.done()):
            return
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._run())

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def mark_return_pose(self) -> None:
        self._head_pose.mark_current_pose_as_return()

    async def _run(self) -> None:
        center_x = self._camera_width / 2.0
        center_y = self._camera_height / 2.0
        yaw_min, yaw_max = self._head_pose.yaw_limits
        pitch_min, pitch_max = self._head_pose.pitch_limits
        try:
            while True:
                try:
                    people = int(Vilib.detect_obj_parameter.get("human_n", 0))
                    self._people = people
                    now = time.time()

                    if people > 0:
                        self._last_seen = now
                        if not self._active:
                            self._active = True

                        ex = float(Vilib.detect_obj_parameter.get("human_x", center_x)) - center_x
                        ey = float(Vilib.detect_obj_parameter.get("human_y", center_y)) - center_y

                        yaw_step = _compute_step(ex, threshold=15, divisor=30.0, scale=-0.5)
                        pitch_step = _compute_step(ey, threshold=25, divisor=50.0, scale=-1.0)

                        if yaw_step or pitch_step:
                            pose = self._state.head_pose
                            target_yaw = max(yaw_min, min(yaw_max, pose.yaw + yaw_step))
                            target_pitch = max(pitch_min, min(pitch_max, pose.pitch + pitch_step))
                            await self._head_pose.set_pose(
                                yaw=target_yaw,
                                pitch=target_pitch,
                                update_return=False,
                            )

                        self._state.face_detected_at = now
                        self._state.face_last_seen_at = now
                    else:
                        if self._active and (now - self._last_seen) > self._recenter_timeout:
                            await self._recenter_head_step()
                            if self._is_at_return_pose():
                                self._active = False

                except Exception as face_err:  # pragma: no cover - hardware specific
                    print(f"[FaceTracker] Face tracking iteration error: {face_err}")
                    await asyncio.sleep(0.1)

                await asyncio.sleep(self._update_interval)
        except asyncio.CancelledError:
            pass

    async def _recenter_head_step(self) -> None:
        pose = self._state.head_pose
        target = self._head_pose.return_pose

        yaw_diff = target.yaw - pose.yaw
        pitch_diff = target.pitch - pose.pitch
        roll_diff = target.roll - pose.roll

        step_yaw = _clamp(yaw_diff, self._recenter_step)
        step_pitch = _clamp(pitch_diff, self._recenter_step)
        step_roll = _clamp(roll_diff, self._recenter_step)

        if all(abs(step) < 0.05 for step in (step_yaw, step_pitch, step_roll)):
            await self._head_pose.set_pose(
                yaw=target.yaw,
                pitch=target.pitch,
                roll=target.roll,
                update_return=False,
            )
        else:
            await self._head_pose.adjust_pose(
                delta_yaw=step_yaw,
                delta_pitch=step_pitch,
                delta_roll=step_roll,
                update_return=False,
            )

    def _is_at_return_pose(self) -> bool:
        pose = self._state.head_pose
        target = self._head_pose.return_pose
        return (
            abs(pose.yaw - target.yaw) < 0.5
            and abs(pose.pitch - target.pitch) < 0.5
            and abs(pose.roll - target.roll) < 0.5
        )


def _compute_step(delta: float, *, threshold: float, divisor: float, scale: float) -> float:
    if delta > threshold:
        return scale * math.ceil(delta / divisor)
    if delta < -threshold:
        return -scale * math.ceil(-delta / divisor)
    return 0.0


def _clamp(value: float, max_magnitude: float) -> float:
    return max(-max_magnitude, min(max_magnitude, value))
