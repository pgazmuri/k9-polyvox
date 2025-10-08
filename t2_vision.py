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
WEB_STREAM_PORT = int(os.environ.get("VILIB_WEB_PORT", "9000"))
WEB_STREAM_PATH = os.environ.get("VILIB_WEB_PATH", "/mjpg")
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
_web_stream_enabled = WEB_STREAM_ENABLED
_current_frame_rate = CAMERA_FRAME_RATE if CAMERA_FRAME_RATE > 0 else None
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
        global _web_stream_enabled
        _web_stream_enabled = False
        print("Camera stopped.")
    except Exception as e:
        print(f"Error stopping camera: {e}")


def set_web_stream(enabled: bool, frame_rate: int | None = None) -> dict[str, object]:
    """Enable or disable the Vilib web stream at runtime."""
    global _web_stream_enabled, _current_frame_rate

    try:
        if frame_rate is not None:
            if frame_rate <= 0:
                raise ValueError("frame_rate must be positive when provided")
            Vilib.set_controls({"FrameRate": frame_rate})
            _current_frame_rate = frame_rate
    except Exception as exc:
        raise RuntimeError(f"Failed to update camera frame rate: {exc}") from exc

    try:
        Vilib.display(local=False, web=enabled)
        _web_stream_enabled = enabled
    except Exception as exc:
        raise RuntimeError(f"Failed to {'enable' if enabled else 'disable'} web stream: {exc}") from exc

    return get_web_stream_status()


def get_web_stream_status() -> dict[str, object]:
    """Return the current status of the Vilib web stream."""
    return {
        "enabled": _web_stream_enabled,
        "frame_rate": _current_frame_rate,
        "port": WEB_STREAM_PORT,
        "path": WEB_STREAM_PATH,
    }

## Legacy GPT vision request removed; realtime API now handles image messages directly.


