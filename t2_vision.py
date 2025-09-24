import os
import time
from vilib import Vilib
from time import sleep
import asyncio

Vilib.camera_start(vflip=False, hflip=False)
Vilib.display(local=False, web=True)
Vilib.face_detect_switch(True)
sleep(1)
print('Camera Started') # Let the camera warm up

CAPTURED_IMAGE = "pidog_vision.jpg"

async def is_person_detected():
    try:
        people = Vilib.detect_obj_parameter['human_n']
        return people > 0
    except Exception as e:
        print(f"Error detecting person: {e}")
        return False

def capture_image(path: str = "pidog_vision"):
    try:
        # Ensure the directory exists
        directory = "."
        full_path = directory + f"/{path}.jpg"
        # Attempt to take a photo
        Vilib.take_photo(photo_name=path, path=directory)
        print(f"Photo captured and saved to {full_path}")
        return full_path
    except Exception as e:
        print(f"Error capturing image: {e}")
        return None
    
def close_camera():
    try:
        Vilib.camera_close()
        if Vilib.flask_thread != None:
            try:
                Vilib.flask_thread.stop()
            except Exception as e:
                print(f"Error stopping Flask thread: {e}")
        print("Camera stopped.")
    except Exception as e:
        print(f"Error stopping camera: {e}")

## Legacy GPT vision request removed; realtime API now handles image messages directly.


