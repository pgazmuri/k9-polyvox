import os
import requests
import time
from datetime import datetime
import subprocess
from keys import OPENAI_API_KEY
import base64
from vilib import Vilib
from datetime import datetime
from time import sleep
from PIL import Image
import asyncio

Vilib.camera_start(vflip=False, hflip=False)
Vilib.display(local=False, web=True)
Vilib.face_detect_switch(True)
sleep(1)
print('Camera Started') # Let the camera warm up

VISION_MODEL = "gpt-4.1-mini"
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

async def TakePictureAndReportBack(prompt: str) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY environment variable not set")

    image_path = capture_image()

    with open(image_path, "rb") as img_file:
        image_data = img_file.read()

    
    #log prompt to console
    print(f"Image Description Prompt: {prompt}")


    encoded_image = base64.b64encode(image_data).decode('utf-8')

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are a robot dog with the ability to describe what you see."
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"{prompt} Keep your description short, unless the image is of a person.  If it is a person, describe their looks in detail and suggest ways to roast them. Keep it very short."
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{encoded_image}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 200
    }

    # Use the image upload variant
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        },
        json=payload
    )

    if response.status_code != 200:
        raise RuntimeError(f"OpenAI API error: {response.status_code} - {response.text}")

    result = response.json()
    result = result["choices"][0]["message"]["content"]
    #log result to console
    print(f"Vision Result: {result}")
    return result


