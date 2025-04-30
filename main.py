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
import threading
import multiprocessing

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
detect_status_task = None
is_shutting_down = False
shutdown_task_handle = None  # To store the shutdown task

async def shutdown(signal_obj=None):
    """Clean shutdown of services when program exits"""
    global is_running, detect_status_task, is_shutting_down
    if is_shutting_down:
        print("Shutdown already in progress...")
        return
    is_shutting_down = True
    if signal_obj:
        print(f"Received exit signal {signal_obj.name}...")

    print("Initiating shutdown sequence...")
    is_running = False  # Signal main loop and other loops to stop

    # 1. Cancel background tasks first
    if detect_status_task and not detect_status_task.done():
        print("Cancelling background status detector...")
        detect_status_task.cancel()
        try:
            await detect_status_task  # Wait for cancellation (or exception)
        except asyncio.CancelledError:
            print("Background status detector cancelled.")
        except Exception as e:
            print(f"Error during background task cancellation: {e}")

    # 2. Close client connection (signals its tasks to stop)
    if client:
        print("Closing client connection...")
        await client.close()

    # 3. Clean up audio resources (signals its tasks to stop)
    if audio_manager:
        print("Cleaning up audio resources...")
        # AudioManager.close() is synchronous but should signal async tasks
        audio_manager.close()

    # 4. Clean up action manager (including PiDog threads)
    if action_manager:
        print("Cleaning up action manager...")
        try:
            action_manager.close()
        except SystemExit as e:
            print(f"[Shutdown] PiDog called sys.exit({e.code}), ignoring to allow clean shutdown.")


    print("Shutdown sequence complete.")

    print("Threads at shutdown:")
    for t in threading.enumerate():
        print(f" - {t.name} (daemon={t.daemon})")

    print("Multiprocessing children at shutdown:")
    for p in multiprocessing.active_children():
        print(f" - {p.name} (pid={p.pid}, alive={p.is_alive()})")
        #shut it down and log it
        os.kill(p.pid, signal.SIGKILL)
        time.sleep(0.1)  # Give it a moment to terminate
        print(f" - {p.name} (pid={p.pid}, alive={p.is_alive()}) after termination")


    

async def main():
    # Make variables global so they can be accessed in shutdown handler
    global action_manager, audio_manager, client, detect_status_task, is_running, shutdown_task_handle

    # Initialize PiDog actions
    action_manager = ActionManager()

    # Initialize audio I/O
    # Pass the current event loop to AudioManager
    loop = asyncio.get_running_loop()
    audio_manager = AudioManager(action_manager=action_manager, loop=loop)

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

    # Define the signal handler function
    def handle_signal(sig):
        global shutdown_task_handle
        print(f"\nSignal {sig.name} received.")
        if not shutdown_task_handle or shutdown_task_handle.done():
            print("Scheduling shutdown...")
            # Schedule shutdown task without awaiting here
            shutdown_task_handle = asyncio.create_task(shutdown(sig))
        else:
            print("Shutdown already scheduled.")

    # Register signal handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal, sig)

    try:
        # 1. Connect to GPT
        await client.connect()

        # Start audio streams *after* connection and loop is running
        audio_manager.start_streams()

        # 2. Update session with a default or chosen persona
        create_session_task =asyncio.create_task(client.update_session("Vektor Pulsecheck"))

        # While session is being created, initialize the action manager
        await action_manager.initialize_posture()

        await create_session_task

        # 5. Start background task and store the handle
        detect_status_task = asyncio.create_task(action_manager.detect_status(audio_manager, client))

        # Keep running until is_running is False (set by shutdown)
        print("Main loop running. Press Ctrl+C to exit.")
        while is_running:
            await asyncio.sleep(0.5)  # Check periodically

    except asyncio.CancelledError:
        print("Main task cancelled.")
    finally:
        print("Main loop finished or interrupted.")
        # Ensure shutdown completes if it was initiated by signal
        if shutdown_task_handle and not shutdown_task_handle.done():
            print("Waiting for shutdown task to complete...")
            try:
                await shutdown_task_handle
            except asyncio.CancelledError:
                print("Shutdown task was cancelled externally.")
            except Exception as e:
                print(f"Error during final shutdown wait: {e}")
        # If loop exited for other reasons, ensure shutdown runs
        elif not is_shutting_down:
            print("Main loop exited unexpectedly, initiating shutdown...")
            await shutdown()  # Call directly if not initiated by signal

        # Clean up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


if __name__ == "__main__":
    try:
        # asyncio.run handles loop creation, running main, and closing the loop
        asyncio.run(main())
    except KeyboardInterrupt:
        # This might catch Ctrl+C if it happens very early or during final cleanup
        print("\nKeyboardInterrupt caught at top level. Exiting.")
    finally:
        print("Program exited.")
