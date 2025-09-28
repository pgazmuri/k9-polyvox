import os
import time
from vilib import Vilib
from time import sleep
import asyncio


# ---------------------------------------------------------------------------
# Runtime configuration (tunable via environment variables)
# ---------------------------------------------------------------------------
CAMERA_WIDTH = int(os.environ.get("CAMERA_WIDTH", "640"))
CAMERA_HEIGHT = int(os.environ.get("CAMERA_HEIGHT", "480"))
CAMERA_FRAME_RATE = int(os.environ.get("CAMERA_FRAME_RATE", "10"))
CAMERA_HFLIP = os.environ.get("CAMERA_HFLIP", "0") == "1"
CAMERA_VFLIP = os.environ.get("CAMERA_VFLIP", "0") == "1"
WEB_STREAM_ENABLED = os.environ.get("VILIB_WEB_STREAM", "0") == "1"
FACE_DETECT_ENABLED = os.environ.get("FACE_DETECT_ENABLED", "1") == "1"
FACE_DETECT_FRAME_SKIP = max(1, int(os.environ.get("FACE_DETECT_FRAME_SKIP", "1")))


# ---------------------------------------------------------------------------
# Camera bring-up with reduced resolution/frame rate to save CPU cycles
# ---------------------------------------------------------------------------
CAMERA_SIZE = (CAMERA_WIDTH, CAMERA_HEIGHT)
Vilib.camera_start(vflip=CAMERA_VFLIP, hflip=CAMERA_HFLIP, size=CAMERA_SIZE)

if CAMERA_FRAME_RATE > 0:
    try:
        Vilib.set_controls({"FrameRate": CAMERA_FRAME_RATE})
        print(f"[t2_vision] Camera frame rate capped at {CAMERA_FRAME_RATE} fps")
    except Exception as e:
        print(f"[t2_vision] Unable to set camera frame rate: {e}")

Vilib.display(local=False, web=WEB_STREAM_ENABLED)
if not WEB_STREAM_ENABLED:
    print("[t2_vision] Web streaming disabled")


# ---------------------------------------------------------------------------
# Face detection throttling – run detector every N frames instead of every frame
# ---------------------------------------------------------------------------
if FACE_DETECT_ENABLED:
    Vilib.face_detect_switch(True)
    if FACE_DETECT_FRAME_SKIP > 1 and hasattr(Vilib, "face_detect_work"):
        _original_face_detect = Vilib.face_detect_work
        _face_state = {"counter": FACE_DETECT_FRAME_SKIP - 1}

        def _throttled_face_detect(img, width, height):
            _face_state["counter"] = (_face_state["counter"] + 1) % FACE_DETECT_FRAME_SKIP
            if _face_state["counter"] == 0:
                return _original_face_detect(img, width, height)
            return img

        Vilib.face_detect_work = _throttled_face_detect
        print(f"[t2_vision] Face detection throttled: every {FACE_DETECT_FRAME_SKIP} frame(s)")
else:
    Vilib.face_detect_switch(False)

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

def get_face_metrics():
    try:
        params = getattr(Vilib, "detect_obj_parameter", {})
        people = params.get('human_n', 0) or 0
        metrics = {
            "count": people,
            "x": params.get('human_x'),
            "y": params.get('human_y'),
            "width": params.get('human_w'),
            "height": params.get('human_h'),
            "frame_width": CAMERA_WIDTH,
            "frame_height": CAMERA_HEIGHT,
            "center_x": CAMERA_WIDTH / 2,
            "center_y": CAMERA_HEIGHT / 2,
            "timestamp": time.time(),
        }
        return metrics
    except Exception as e:
        print(f"Error retrieving face metrics: {e}")
        return {
            "count": 0,
            "x": None,
            "y": None,
            "width": None,
            "height": None,
            "frame_width": CAMERA_WIDTH,
            "frame_height": CAMERA_HEIGHT,
            "center_x": CAMERA_WIDTH / 2,
            "center_y": CAMERA_HEIGHT / 2,
            "timestamp": time.time(),
        }

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


