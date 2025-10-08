import asyncio
import os
from types import MethodType

from robot_hat import utils

from actions import LOCAL_SOUND_DIR, SOUND_DIR


class AudioController:
    """Wraps PiDog audio playback utilities."""

    def __init__(self, dog) -> None:
        self._dog = dog
        self._ensure_music_patch()

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

    def _ensure_music_patch(self) -> None:
        music = getattr(self._dog, "music", None)
        if not music or getattr(music, "_polyvox_volume_patch", False):
            return

        original_music_play = music.music_play

        def patched_music_play(music_self, filename, loops=1, start=0.0, volume=None):
            try:
                music_self.pygame.mixer.music.load(filename)
            except Exception:
                # Fallback to original implementation if load fails here
                return original_music_play(filename, loops=loops, start=start, volume=volume)

            target_volume = volume
            if target_volume is None:
                target_volume = getattr(music_self, "_polyvox_last_volume", None)
            if target_volume is not None:
                music_self.music_set_volume(target_volume)
                music_self._polyvox_last_volume = target_volume
            else:
                current = music_self.pygame.mixer.music.get_volume()
                music_self._polyvox_last_volume = round(current * 100, 2)

            music_self.pygame.mixer.music.play(loops, start)

        music.music_play = MethodType(patched_music_play, music)
        music._polyvox_volume_patch = True
        music._polyvox_original_music_play = original_music_play
