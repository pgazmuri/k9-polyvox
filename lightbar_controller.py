import asyncio
import math
from typing import List


class LightbarController:
    """Handles all lightbar visual effects for the PiDog."""

    def __init__(self, rgb_strip) -> None:
        self._strip = rgb_strip

    def breath(self, color: str = "pink", bps: float = 0.5) -> None:
        self._strip.set_mode(style="breath", color=color, bps=bps)

    def boom(self, color: str = "blue", bps: float = 3.0) -> None:
        self._strip.set_mode(style="boom", color=color, bps=bps)

    def bark(self) -> None:
        self._strip.set_mode(style="bark", color="#a10a0a", bps=10, brightness=0.5)

    def set_mode(
        self,
        *,
        style: str,
        color: str = "#ffffff",
        bps: float = 1.0,
        brightness: float = 1.0,
    ) -> None:
        self._strip.set_mode(style=style, color=color, bps=bps, brightness=brightness)

    def set_direct(self, r: int, g: int, b: int, brightness: float = 1.0) -> None:
        r_scaled = min(int(r * brightness), 255)
        g_scaled = min(int(g * brightness), 255)
        b_scaled = min(int(b * brightness), 255)

        self._strip.style = None
        lights = [[r_scaled, g_scaled, b_scaled]] * self._strip.light_num
        adjusted = self._adjust_lights_based_on_brightness(lights, r_scaled, g_scaled, b_scaled, brightness)
        self._strip.display(adjusted)

    def _adjust_lights_based_on_brightness(
        self,
        lights: List[List[int]],
        r: int,
        g: int,
        b: int,
        brightness: float,
    ) -> List[List[int]]:
        num_lights = len(lights)
        middle_index = num_lights // 2

        if brightness > 0:
            brightness = math.log1p(brightness * 9) / math.log1p(20)

        for i in range(num_lights):
            if brightness == 0:
                lights[i] = [0, 0, 0] if i != middle_index else [r, g, b]
            elif brightness == 1:
                lights[i] = [r, g, b]
            else:
                distance_from_middle = abs(i - middle_index)
                max_distance = max(middle_index, num_lights - middle_index - 1)
                scaled_brightness = max(0, brightness - (distance_from_middle / max_distance) * (1 - brightness))
                lights[i] = [
                    int(r * scaled_brightness),
                    int(g * scaled_brightness),
                    int(b * scaled_brightness),
                ]
        return lights

    async def power_up_sequence(self) -> None:
        total_steps = 40
        red = (255, 0, 0)
        orange = (255, 165, 0)
        yellow = (255, 255, 0)
        white = (255, 255, 255)

        red_to_orange_steps = 13
        orange_to_yellow_steps = 13
        yellow_to_white_steps = total_steps - red_to_orange_steps - orange_to_yellow_steps

        for i in range(1, total_steps + 1):
            brightness = i / total_steps

            if i <= red_to_orange_steps:
                progress = i / red_to_orange_steps
                color = (
                    int(red[0] + (orange[0] - red[0]) * progress),
                    int(red[1] + (orange[1] - red[1]) * progress),
                    int(red[2] + (orange[2] - red[2]) * progress),
                )
            elif i <= red_to_orange_steps + orange_to_yellow_steps:
                progress = (i - red_to_orange_steps) / orange_to_yellow_steps
                color = (
                    int(orange[0] + (yellow[0] - orange[0]) * progress),
                    int(orange[1] + (yellow[1] - orange[1]) * progress),
                    int(orange[2] + (yellow[2] - orange[2]) * progress),
                )
            else:
                progress = (i - red_to_orange_steps - orange_to_yellow_steps) / yellow_to_white_steps
                color = (
                    int(yellow[0] + (white[0] - yellow[0]) * progress),
                    int(yellow[1] + (white[1] - yellow[1]) * progress),
                    int(yellow[2] + (white[2] - yellow[2]) * progress),
                )

            r, g, b = (max(0, min(255, component)) for component in color)
            self.set_direct(r, g, b, brightness=brightness)
            await asyncio.sleep(0.1)

        self.breath()
