import os
import pygame
import time

# Force ALSA and use card 0, device 0 (headphones)
os.environ["SDL_AUDIODRIVER"] = "alsa"
os.environ["AUDIODEV"] = "hw:0,0"  # bypass default and softvol

try:
    pygame.mixer.init()
    print("✅ pygame.mixer initialized")
except pygame.error as e:
    print(f"❌ pygame.mixer failed to init: {e}")
    exit(1)

print("Mixer settings:", pygame.mixer.get_init())
print("Channels available:", pygame.mixer.get_num_channels())

try:
    sound = pygame.mixer.Sound("/usr/share/sounds/alsa/Front_Center.wav")
    print("✅ Sound loaded")
    sound.play()
    print("🔊 Playing sound...")
    time.sleep(2)
except Exception as e:
    print(f"❌ Failed to play sound: {e}")
