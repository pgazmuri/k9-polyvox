import asyncio
import os
from typing import Optional, Tuple

from head_controller import HeadController
from state_manager import HeadPose, RobotDogState


HEAD_POSTURE_PITCH_COMP = {
    "sitting": float(os.environ.get("SITTING_HEAD_PITCH_COMP", "-20")),
    "standing": float(os.environ.get("STANDING_HEAD_PITCH_COMP", "0")),
}


class HeadPoseManager:
    """Encapsulates head pose orchestration and state synchronization."""

    def __init__(
        self,
        controller: HeadController,
        state: RobotDogState,
        *,
        posture_pitch_comp: Optional[dict[str, float]] = None,
    ) -> None:
        self._controller = controller
        self._state = state
        self._posture_pitch_comp = posture_pitch_comp or HEAD_POSTURE_PITCH_COMP
        self._return_pose = state.head_pose.copy()

    @property
    def yaw_limits(self) -> Tuple[float, float]:
        return self._controller.yaw_limits

    @property
    def pitch_limits(self) -> Tuple[float, float]:
        return self._controller.pitch_limits

    @property
    def roll_limits(self) -> Tuple[float, float]:
        return self._controller.roll_limits

    @property
    def return_pose(self) -> HeadPose:
        return self._return_pose.copy()

    def mark_current_pose_as_return(self) -> None:
        self._return_pose = self._state.head_pose.copy()

    def set_return_pose(self, pose: HeadPose) -> None:
        self._return_pose = pose.copy()

    def schedule_initialization(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.initialize())

    async def initialize(self) -> None:
        await self._apply_posture_bias(self._state.posture)
        await self._controller.home()
        self._sync_from_controller(update_return=True)

    async def _apply_posture_bias(self, posture: Optional[str]) -> None:
        pitch_bias = self._posture_pitch_comp.get(posture, 0.0)
        await self._controller.set_posture_bias(pitch_bias=pitch_bias)

    def _sync_from_controller(self, *, update_return: bool = False) -> HeadPose:
        pose = self._controller.current_pose()
        self._state.head_pose = pose
        if update_return:
            self._return_pose = pose.copy()
        return pose

    async def sync_from_hardware(self, *, update_return: bool = False) -> HeadPose:
        pose = await self._controller.sync_with_hardware()
        self._state.head_pose = pose
        if update_return:
            self._return_pose = pose.copy()
        return pose

    async def set_pose(
        self,
        *,
        yaw: Optional[float] = None,
        pitch: Optional[float] = None,
        roll: Optional[float] = None,
        update_return: bool = True,
    ) -> HeadPose:
        await self._controller.set_pose(yaw=yaw, pitch=pitch, roll=roll)
        return self._sync_from_controller(update_return=update_return)

    async def adjust_pose(
        self,
        *,
        delta_yaw: float = 0.0,
        delta_pitch: float = 0.0,
        delta_roll: float = 0.0,
        update_return: bool = False,
    ) -> HeadPose:
        await self._controller.adjust_pose(
            delta_yaw=delta_yaw,
            delta_pitch=delta_pitch,
            delta_roll=delta_roll,
        )
        return self._sync_from_controller(update_return=update_return)

    async def handle_posture_change(
        self,
        old_posture: Optional[str],
        new_posture: Optional[str],
    ) -> None:
        if old_posture == new_posture:
            return
        await self._apply_posture_bias(new_posture)
        self._sync_from_controller(update_return=False)

