import os

# Set before importing anything pygame-related
# os.environ["SDL_AUDIODRIVER"] = "alsa"
# os.environ["AUDIODEV"] = "hw:0,0"

import asyncio
import time
import signal
import os
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

# Global references for cleanup during shutdown
action_manager = None
audio_manager = None
client = None
is_running = True

async def shutdown(signal=None):
    """Clean shutdown of services when program exits"""
    if signal:
        print(f"Received exit signal...")
    
    print("Shutting down...")
    
    # Close client connection first
    if client:
        print("Closing client connection...")
        await client.close()
    
    # Clean up audio resources
    if audio_manager:
        print("Cleaning up audio resources...")
        audio_manager.close()

    if action_manager:
        print("Cleaning up action manager...")
        action_manager.close()

    is_running = False

    print("Shutdown complete.")

async def main():
    # Make variables global so they can be accessed in shutdown handler
    global action_manager, audio_manager, client
    
    # Initialize PiDog actions
    action_manager = ActionManager()

    # Initialize audio I/O
    audio_manager = AudioManager(action_manager=action_manager)

    # We define a function here so function_call_manager can reconnect
    # using the RealtimeClient's logic.
    client = None
    
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
        client=client
    )

    client.function_call_manager = function_call_manager

    

    # 1. Connect to GPT
    await client.connect()
    
    audio_manager.start_streams()

    # 2. Update session with a default or chosen persona
    await client.update_session("Vektor Pulsecheck")

    
    await action_manager.initialize_posture()

    # 5. Start background task to watch for changes and remind of default goal
    asyncio.create_task(action_manager.detect_status(audio_manager, client))

    # Keep running
    try:
        while is_running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("Keyboard interrupt received...")
    finally:
        await shutdown()

if __name__ == "__main__":
    # # Register signal handlers for graceful shutdown
    # for sig in (signal.SIGINT, signal.SIGTERM):
    #     signal.signal(sig, lambda s, _: asyncio.create_task(shutdown(s)))
    
    asyncio.run(main())
