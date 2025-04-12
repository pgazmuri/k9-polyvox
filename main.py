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
    asyncio.create_task(audio_manager.visualize_audio())

    # 4. Start processing function calls and audio from GPT
    asyncio.create_task(client.process_function_calls())
    asyncio.create_task(client.process_outgoing_audio())
    
    audio_manager.start_streams()
    
    # 2. Update session with a default or chosen persona
    await client.update_session("Vektor Pulsecheck")

    # 5. Start background task to watch for changes and remind of default goal
    asyncio.create_task(action_manager.detect_status(audio_manager, client))

    # Keep running
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
