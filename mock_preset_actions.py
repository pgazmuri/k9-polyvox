import asyncio
import time
import os

# Mock implementations for preset actions. These do nothing.

User = os.popen('echo ${SUDO_USER:-$LOGNAME}').readline().strip()
UserHome = os.popen('getent passwd %s | cut -d: -f 6' %User).readline().strip()
SOUND_DIR = f"{UserHome}/pidog/sounds/"
LOCAL_SOUND_DIR = f"audio/"

def scratch(my_dog):
    print("[Mock Action] scratch called")
    pass

def hand_shake(my_dog):
    print("[Mock Action] hand_shake called")
    pass

def high_five(my_dog):
    print("[Mock Action] high_five called")
    pass

def pant(my_dog, yrp=None, pitch_comp=0, speed=80, volume=100):
    print("[Mock Action] pant called")
    pass

def body_twisting(my_dog):
    print("[Mock Action] body_twisting called")
    pass

def bark_action(my_dog, yrp=None, speak=None, volume=100):
    print("[Mock Action] bark_action called")
    pass

def shake_head(my_dog, yrp=None):
    print("[Mock Action] shake_head called")
    pass

def shake_head_smooth(my_dog, pitch_comp=0, amplitude=40, speed=90):
    print("[Mock Action] shake_head_smooth called")
    pass

def bark(my_dog, yrp=None, pitch_comp=0, roll_comp=0, volume=100):
    print("[Mock Action] bark called")
    pass

def push_up(my_dog, speed=80):
    print("[Mock Action] push_up called")
    pass

def howling(my_dog, volume=100):
    print("[Mock Action] howling called")
    pass

def attack_posture(my_dog):
    print("[Mock Action] attack_posture called")
    pass

def lick_hand(my_dog):
    print("[Mock Action] lick_hand called")
    pass

def waiting(my_dog, pitch_comp):
    print("[Mock Action] waiting called")
    pass

def feet_shake(my_dog, step=None):
    print("[Mock Action] feet_shake called")
    pass

def sit_2_stand(my_dog, speed=75):
    print("[Mock Action] sit_2_stand called")
    pass

def relax_neck(my_dog, pitch_comp=-35):
    print("[Mock Action] relax_neck called")
    pass

def nod(my_dog, pitch_comp=-35, amplitude=20, step=2, speed=90):
    print("[Mock Action] nod called")
    pass

async def talk(my_dog, pitch_comp=-15, amplitude=4, duration=1.5, speed=85, fps=10):
    print("[Mock Action] talk called")
    await asyncio.sleep(duration) # Simulate talking duration
    pass

async def wait_head_done(my_dog):
    print("[Mock Action] wait_head_done called")
    await asyncio.sleep(0.1) # Simulate waiting
    pass

def look_forward(my_dog, pitch_comp=0):
    print("[Mock Action] look_forward called")
    pass

def look_up(my_dog, pitch_comp=0):
    print("[Mock Action] look_up called")
    pass

def look_down(my_dog, pitch_comp=0):
    print("[Mock Action] look_down called")
    pass

def look_left(my_dog, pitch_comp=0):
    print("[Mock Action] look_left called")
    pass

def look_right(my_dog, pitch_comp=0):
    print("[Mock Action] look_right called")
    pass

def head_up_left(my_dog, pitch_comp=0):
    print("[Mock Action] head_up_left called")
    pass

def head_up_right(my_dog, pitch_comp=0):
    print("[Mock Action] head_up_right called")
    pass

def head_down_left(my_dog, pitch_comp=0):
    print("[Mock Action] head_down_left called")
    pass

def head_down_right(my_dog, pitch_comp=0):
    print("[Mock Action] head_down_right called")
    pass

def think(my_dog, pitch_comp=0):
    print("[Mock Action] think called")
    pass

def recall(my_dog, pitch_comp=0):
    print("[Mock Action] recall called")
    pass

def fluster(my_dog, pitch_comp=0):
    print("[Mock Action] fluster called")
    pass

def alert(my_dog, pitch_comp=0):
    print("[Mock Action] alert called")
    pass

def surprise(my_dog, pitch_comp=0, status='sit'):
    print("[Mock Action] surprise called")
    pass

def stretch(my_dog):
    print("[Mock Action] stretch called")
    pass

def wag_tail(my_dog, step_count=5, speed=100):
    print(f"[Mock Action] wag_tail called with step_count={step_count}, speed={speed}")
    pass

def head_up_down(my_dog):
    print("[Mock Action] head_up_down called")
    pass

def tilt_head_left(my_dog):
    print("[Mock Action] tilt_head_left called")
    pass

def tilt_head_right(my_dog):
    print("[Mock Action] tilt_head_right called")
    pass

def walk_forward(my_dog, step_count=5, speed=100):
    print(f"[Mock Action] walk_forward called with step_count={step_count}, speed={speed}")
    pass

def walk_backward(my_dog, step_count=5, speed=100):
    print(f"[Mock Action] walk_backward called with step_count={step_count}, speed={speed}")
    pass

def lie_down(my_dog):
    print("[Mock Action] lie_down called")
    pass

def stand_up(my_dog, speed=80):
    print(f"[Mock Action] stand_up called with speed={speed}")
    pass

def sit_down(my_dog, speed=80):
    print(f"[Mock Action] sit_down called with speed={speed}")
    pass

def turn_left(my_dog, step_count=5, speed=100):
    print(f"[Mock Action] turn_left called with step_count={step_count}, speed={speed}")
    pass

def turn_right(my_dog, step_count=5, speed=100):
    print(f"[Mock Action] turn_right called with step_count={step_count}, speed={speed}")
    pass

def doze_off(my_dog, speed=100):
    print(f"[Mock Action] doze_off called with speed={speed}")
    pass

# Add any other functions from preset_actions.py here as no-ops

if __name__ == "__main__":
    print("This is the mock preset_actions file. Run main.py to use it.")

