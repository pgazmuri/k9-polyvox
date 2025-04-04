import asyncio
import time
from action_manager import ActionManager
from audio_manager import AudioManager
from function_call_manager import FunctionCallManager
from realtime_client import RealtimeClient

from keys import OPENAI_API_KEY  # Adjust to wherever your key is
# Or define OPENAI_API_KEY = "..."

WS_URL = "wss://api.openai.com/v1/realtime"
MODEL = "gpt-4o-realtime-preview"

headers = {
    "Authorization": f"Bearer {OPENAI_API_KEY}",
    "OpenAI-Beta": "realtime=v1"
}

async def main():
    # Initialize PiDog actions
    action_manager: ActionManager = ActionManager()
    action_manager.initialize_posture()

    # Initialize audio I/O
    audio_manager = AudioManager(action_manager=action_manager)

    # We define a function here so function_call_manager can reconnect
    # using the RealtimeClient's logic.
    client = None
    async def reconnect_cb(persona_name, persona_object=None):
        if client is not None:
            await client.reconnect(persona_name, persona_object)

   

    # Realtime client
    client = RealtimeClient(
        ws_url=WS_URL,
        model=MODEL,
        headers=headers,
        function_call_manager=None,
        audio_manager=audio_manager,
        action_manager=action_manager
    )

    
    


    # Initialize function call manager
    function_call_manager = FunctionCallManager(
        action_manager=action_manager, 
        reconnect_callback=reconnect_cb,
        client=client
    )

    client.function_call_manager = function_call_manager

    # 1. Connect to GPT
    await client.connect()

    # 3. Start microphone capture & speaker playback tasks
    #asyncio.create_task(asyncio.to_thread(audio_manager.capture_microphone))
    asyncio.create_task(audio_manager.visualize_audio())

    # asyncio.create_task(client.capture_microphone())
    # 4. Start processing function calls and audio from GPT
    asyncio.create_task(client.process_function_calls())
    asyncio.create_task(client.process_outgoing_audio())
    
    audio_manager.start_streams()
    
    # 2. Update session with a default or chosen persona
    await client.update_session("Vektor Pulsecheck")

    # 5. Example background task to watch for petting
    async def detect_status():
        is_change = False
        last_change_time = 0  # Track the last time a change was noticed
        while True:
            try:
                print("Volume: ", audio_manager.latest_volume)
                # Also check if a new sound direction came in
                # Detect individual changes
                petting_changed = action_manager.detect_petting_change()
                sound_changed = action_manager.detect_sound_direction_change()
                face_changed = await action_manager.detect_face_change()
                orientation_changed = action_manager.detect_orientation_change()

                # Combine for overall change
                is_change = petting_changed or sound_changed or face_changed or orientation_changed

                # Ignore changes if within the last 5 seconds or if talking movement is active
                current_time = time.time()
                if is_change and (current_time - last_change_time < 5 or action_manager.isTalkingMovement):
                    is_change = False

                new_goal = ""

                if is_change:
                    new_goal = ""
                    last_change_time = current_time  # Update the last change time
                    if petting_changed:
                        if (current_time - action_manager.state.petting_detected_at) < 10:
                            new_goal = "You are being petted!"
                        else:
                            new_goal = "You are no longer being petted."
                    if sound_changed:
                        if (not action_manager.isTalkingMovement) and (audio_manager.latest_volume > 30):
                            new_goal = f"Sound (is someone talking?) came from direction: {action_manager.state.last_sound_direction}"
                    if face_changed:
                        if (current_time - action_manager.state.face_detected_at) < 10:
                            new_goal = "A face is detected!"
                        else:
                            new_goal = "A face is no longer detected."
                    if orientation_changed:
                        new_goal = action_manager.state.last_orientation_description

                    if(len(new_goal) > 0):
                        action_manager.state.goal = new_goal
                        client.send_awareness()

                await asyncio.sleep(0.3)
                is_change = False
            except Exception as e:
                print(f"[detect_status] Error: {e}")
                await asyncio.sleep(1)  # Prevent tight loop on failure


    asyncio.create_task(detect_status())

   

    # Keep running
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
