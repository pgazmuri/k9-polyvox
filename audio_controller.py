import asyncio
import os

from robot_hat import utils

from actions import LOCAL_SOUND_DIR, SOUND_DIR


class AudioController:
    """Wraps PiDog audio playback utilities."""

    def __init__(self, dog) -> None:
        self._dog = dog

    async def play_file_async(self, filename: str, volume: int = 100) -> None:
        if not filename:
            return
        await asyncio.to_thread(self._dog.speak_block, filename, volume)

    def play(self, name: str, volume = 100):
        if not name:
            return False

        utils.run_command("sudo killall pulseaudio")

        potential_paths = [
            name,
            os.path.join(LOCAL_SOUND_DIR, name),
            os.path.join(LOCAL_SOUND_DIR, f"{name}.mp3"),
            os.path.join(LOCAL_SOUND_DIR, f"{name}.wav"),
            os.path.join(SOUND_DIR, f"{name}.mp3"),
            os.path.join(SOUND_DIR, f"{name}.wav"),
        ]

        for path in potential_paths:
            if os.path.isfile(path):
                self._dog.music.music_play(path, volume)
                return self._dog.music
        return False
