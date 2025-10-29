import asyncio
import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from google import genai

from function_call_manager import admin_tools, get_base_tools
from system_prompts import personas
from prompt_builder import build_persona_instructions
from tool_builder import build_function_tools_gemini


@dataclass
class _QueuedAction:
    name: str
    enqueued_at: float
    source: str = "perform_action"
    action_id: str = ""


class RealtimeClient:
    """Realtime client powered by Google Gemini Live API."""

    def __init__(
        self,
        model: str,
        api_key: str,
        function_call_manager,
        audio_manager,
        action_manager,
    ) -> None:
        self.model = model
        self.api_key = api_key

        self.function_call_manager = function_call_manager
        self.audio_manager = audio_manager
        self.action_manager = action_manager

        self.is_shutdown = False
        self.client: Optional[genai.Client] = None
        self.session = None
        self._event_task: Optional[asyncio.Task] = None
        self._outgoing_audio_task: Optional[asyncio.Task] = None
        self._action_worker_task: Optional[asyncio.Task] = None

        # Conversation state
        self.isReceivingAudio = False
        self.isDetectingUserSpeech = False
        self._available_actions_cache: List[str] = []

        self._queued_actions: "asyncio.Queue[_QueuedAction]" = asyncio.Queue()
        self._current_action_task: Optional[asyncio.Task] = None
        self._audio_idle_event = asyncio.Event()
        self._audio_idle_event.set()
        self._action_completion_events: Dict[str, asyncio.Event] = {}  # Track action completions

        self.persona = None
        self.first_response_event = asyncio.Event()
        self._touch_activity()  # Initialize all timestamps

        # Response state tracking to prevent race conditions
        self._response_active = False
        self._pending_awareness_request = None
        self._last_awareness_time = 0
        self._awareness_debounce = 1.5  # seconds - increased to prevent race conditions

        # Initialize Gemini client
        self.client = genai.Client(api_key=self.api_key)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the realtime session and stop all background tasks."""
        self.is_shutdown = True

        await self._cancel_current_action(reason="shutdown")
        await self._drain_action_queue(reason="shutdown")
        self._audio_idle_event.set()

        for task in (self._event_task, self._outgoing_audio_task, self._action_worker_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._event_task = None
        self._outgoing_audio_task = None
        self._action_worker_task = None
        self._current_action_task = None

        if self.session:
            try:
                await self.session.close()
            except:
                pass
            self.session = None

        # Reset response/awareness state so new connections start cleanly
        self._response_active = False
        self._pending_awareness_request = None
        self.isReceivingAudio = False
        self.isDetectingUserSpeech = False
        self.last_user_speech_time = 0.0

        print("[RealtimeClient] Session closed.")

    async def update_session(self, persona: str = "Vektor Pulsecheck") -> None:
        """Send persona-specific instructions and tools to the model."""
        if not self.function_call_manager:
            raise RuntimeError("FunctionCallManager not configured before update_session.")
        if not self.session:
            raise RuntimeError("Realtime session is not connected.")

        character_by_name = {char["name"]: char for char in personas}
        if persona not in character_by_name:
            raise ValueError(f"Unknown persona '{persona}'")

        self.persona = character_by_name[persona]

        available_actions = self.action_manager.get_available_actions()
        self._available_actions_cache = list(available_actions)
        instructions = build_persona_instructions(self.persona, available_actions, personas)
        tools = build_function_tools_gemini(
            self.function_call_manager,
            self.persona["name"],
            available_actions,
            personas,
            get_base_tools,
            admin_tools
        )

        # Update session configuration
        # Note: Gemini Live API manages voice through speech_config
        # We'll store instructions and tools for when we reconnect
        self._current_instructions = instructions
        self._current_tools = tools

        print(f"[RealtimeClient] Session updated for persona '{persona}'.")

    async def reconnect(self, persona: str, persona_object: Optional[Dict[str, Any]] = None) -> None:
        """Tear down and re-establish the realtime connection, optionally adding a persona."""
        print(f"[RealtimeClient] ===== RECONNECT CALLED: persona={persona}, has_object={persona_object is not None} =====")
        try:
            print("[RealtimeClient] Closing old session...")
            await self.close()
            print("[RealtimeClient] Old session closed.")

            print("[RealtimeClient] Interrupting playback before reconnect...")
            self.audio_manager.interrupt_playback(reason="reconnect")

            # Stop audio streams to prevent queuing audio during reconnect
            print("[RealtimeClient] Stopping audio streams...")
            self.audio_manager.stop_streams()

            await asyncio.sleep(0.2)

            print("[RealtimeClient] Connecting new session...")
            await self.connect()
            print("[RealtimeClient] New session connected.")

            print("[RealtimeClient] Starting audio streams...")
            self.audio_manager.start_streams()

            if persona_object and (existing := next((p for p in personas if p["name"] == persona_object["name"]), None)):
                print(f"[RealtimeClient] Updating existing persona: {persona_object['name']}")
                existing.update(persona_object)
            elif persona_object:
                print(f"[RealtimeClient] Adding new persona: {persona_object['name']}")
                personas.append(persona_object)

            print(f"[RealtimeClient] Updating session with persona: {persona}")
            await self.update_session(persona)
            print("[RealtimeClient] Session updated.")

            print("[RealtimeClient] Sending awareness...")
            await self.send_awareness()
            print("[RealtimeClient] Awareness sent. Reconnect complete.")
        except Exception as exc:
            print(f"[RealtimeClient] ERROR in reconnect: {exc}")
            import traceback
            traceback.print_exc()
            # Ensure streams restart even on error
            try:
                self.audio_manager.start_streams()
            except:
                pass
            raise

    # ------------------------------------------------------------------
    # Messaging helpers
    # ------------------------------------------------------------------
    @property
    def has_active_response(self) -> bool:
        """Backward compatibility property for action_manager."""
        return self._response_active

    async def send_awareness(self) -> None:
        """Request initial awareness status when waking up."""
        # Debounce: Don't send if recently sent
        now = time.time()
        if now - self._last_awareness_time < self._awareness_debounce:
            print("[RealtimeClient] Debouncing awareness request (too soon)")
            return

        # Don't send if response is active - queue instead
        if self._response_active:
            print("[RealtimeClient] Response active, queueing awareness request")
            self._pending_awareness_request = now
            return

        await self._do_send_awareness()

    async def _do_send_awareness(self) -> None:
        """Actually send the awareness request."""
        if not self.session:
            return
        await asyncio.sleep(0.1)  # Brief delay to ensure session update is complete
        print("[RealtimeClient] Sending awareness wake-up request...")
        await self.send_text_message("Please call get_awareness_status to get your current status.", role="user")
        self.action_manager.state.last_awareness_event_time = time.time()
        self._last_awareness_time = time.time()

    async def force_response(self, instructions: str = "Respond out loud to what just happened.") -> None:
        """Inject stimulus via awareness status and trigger response."""
        if not self.action_manager or not self.action_manager.state:
            return

        # Store the stimulus in the state so get_awareness_status will return it
        self.action_manager.state.pending_stimulus = instructions
        print(f"[RealtimeClient] Forcing response with stimulus: {instructions}")

        await self.send_awareness()

    async def make_out_of_band_request(self, request: str, topic: str = "self_motivation") -> None:
        """Send a request message to the agent."""
        print(f"[RealtimeClient] Making out-of-band request: {request}")
        await self.send_text_message(request, role="user")

    async def send_text_message(self, text: str, *, role: str = "user") -> None:
        """Send a text message to the session."""
        if not self.session:
            raise RuntimeError("Cannot send message: session not connected")

        try:
            print(f"[RealtimeClient] Sending {role} message: {text}")
            await self.session.send_client_content(
                turns={"role": role, "parts": [{"text": text or ""}]},
                turn_complete=True
            )
        except Exception as exc:
            print(f"[RealtimeClient] Error sending message: {exc}")
            if "Not connected" in str(exc) or "not connected" in str(exc).lower():
                self.session = None  # Mark as disconnected
            raise

    async def send_image_and_request_response(self, image_path: str) -> None:
        """Send an image to the session."""
        if not self.session:
            return
        try:
            with open(image_path, "rb") as f:
                image_data = f.read()

            # Gemini uses inline_data format for images
            await self.session.send_client_content(
                turns={"role": "user", "parts": [{
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64.b64encode(image_data).decode('utf-8')
                    }
                }]},
                turn_complete=True
            )
        except Exception as exc:
            print(f"[RealtimeClient] Error sending image: {exc}")

    async def wait_for_first_response(self, timeout: Optional[float] = None) -> None:
        """Wait for the first response from the model."""
        if not self.first_response_event.is_set():
            await asyncio.wait_for(self.first_response_event.wait(), timeout) if timeout else await self.first_response_event.wait()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Establish the realtime session and start background tasks."""
        self.is_shutdown = False
        print("[RealtimeClient] Connecting via Google Gemini Live API...")

        # Configure session
        config = {
            "response_modalities": ["AUDIO"],
        }

        # Connect to Gemini Live API
        try:
            self.session = self.client.aio.live.connect(model=self.model, config=config)
            await self.session.__aenter__()
            print("[RealtimeClient] Connected to Gemini Live API.")
        except Exception as exc:
            print(f"[RealtimeClient] Failed to connect: {exc}")
            raise

        self._event_task = asyncio.create_task(self._dispatch_session_events())
        self._outgoing_audio_task = asyncio.create_task(self.process_outgoing_audio())
        self._audio_idle_event.set()
        self._action_worker_task = asyncio.create_task(self._run_action_worker())

    async def _dispatch_session_events(self) -> None:
        """Listen for and dispatch events from the Gemini session."""
        if not self.session:
            return
        print("[RealtimeClient] Listening for session events...")
        try:
            async for response in self.session.receive():
                try:
                    await self._handle_session_event(response)
                except Exception as event_exc:
                    print(f"[RealtimeClient] Error handling event: {event_exc}")
                    import traceback
                    traceback.print_exc()
        except asyncio.CancelledError:
            print("[RealtimeClient] Event loop cancelled.")
            raise
        except Exception as exc:
            print(f"[RealtimeClient] Error in event loop: {exc}")
            import traceback
            traceback.print_exc()
            self.session = None

    async def _handle_session_event(self, response) -> None:
        """Handle events from Gemini Live API."""
        # Gemini responses contain different fields
        # Check for audio data
        if hasattr(response, 'data') and response.data:
            await self._handle_audio_data(response.data)

        # Check for text
        if hasattr(response, 'text') and response.text:
            self._handle_text_response(response.text)

        # Check for function calls
        if hasattr(response, 'tool_call') and response.tool_call:
            await self._handle_tool_call(response.tool_call)

        # Check for server content (includes function calls)
        if hasattr(response, 'server_content'):
            await self._handle_server_content(response.server_content)

    async def _handle_audio_data(self, audio_data: bytes) -> None:
        """Handle incoming audio from Gemini."""
        if not self.isReceivingAudio:
            self.isReceivingAudio = True
            self.last_model_audio_time = time.time()
            # Pause action dispatch when model starts speaking
            if self._audio_idle_event.is_set():
                print("[RealtimeClient] Model audio starting; pausing action dispatch.")
                self._audio_idle_event.clear()
            self._set_first_response()

        try:
            self.audio_manager.queue_audio(audio_data)
            self.last_model_audio_time = time.time()
        except Exception as exc:
            print(f"[RealtimeClient] Error queuing audio: {exc}")

    def _handle_text_response(self, text: str) -> None:
        """Handle text response from Gemini."""
        print(f"Assistant: {text}")
        self._set_first_response()

    async def _handle_tool_call(self, tool_call) -> None:
        """Handle tool/function call from Gemini."""
        print(f"[RealtimeClient] Tool call: {tool_call}")
        # Extract function name and arguments
        function_name = tool_call.name if hasattr(tool_call, 'name') else tool_call.get('name')
        function_args = tool_call.args if hasattr(tool_call, 'args') else tool_call.get('args', {})

        # Execute the function via function_call_manager
        if self.function_call_manager:
            try:
                result = await self.function_call_manager.handle_function_call(function_name, function_args)
                # Send result back to Gemini
                if self.session:
                    await self.session.send_client_content(
                        turns={"role": "function", "parts": [{"function_response": {
                            "name": function_name,
                            "response": result
                        }}]},
                        turn_complete=True
                    )
            except Exception as exc:
                print(f"[RealtimeClient] Error handling tool call: {exc}")

    async def _handle_server_content(self, server_content) -> None:
        """Handle server content which may include function calls."""
        if hasattr(server_content, 'model_turn'):
            model_turn = server_content.model_turn
            if hasattr(model_turn, 'parts'):
                for part in model_turn.parts:
                    # Check for function calls in parts
                    if hasattr(part, 'function_call'):
                        await self._handle_tool_call(part.function_call)
                    # Check for text
                    if hasattr(part, 'text'):
                        self._handle_text_response(part.text)

    # ------------------------------------------------------------------
    # Audio streaming to the model
    # ------------------------------------------------------------------
    async def process_outgoing_audio(self) -> None:
        """Process outgoing audio from the queue and send to Gemini."""
        if not self.audio_manager:
            return
        print("[RealtimeClient] Starting outgoing audio processing...")
        audio_sent_count = 0
        consecutive_errors = 0
        max_consecutive_errors = 5

        while not self.is_shutdown:
            try:
                # Check connection state first
                if not self.session:
                    # Clear queue while disconnected
                    try:
                        while not self.audio_manager.outgoing_data_queue.empty():
                            self.audio_manager.outgoing_data_queue.get_nowait()
                            self.audio_manager.outgoing_data_queue.task_done()
                    except:
                        pass
                    await asyncio.sleep(0.5)
                    continue

                try:
                    resampled_bytes = await asyncio.wait_for(
                        self.audio_manager.outgoing_data_queue.get(),
                        timeout=0.01,
                    )
                except asyncio.TimeoutError:
                    continue

                # Send audio to Gemini
                # Gemini expects PCM16 audio at 16kHz
                await self.session.send_realtime_input(
                    {"mime_type": "audio/pcm;rate=16000", "data": resampled_bytes}
                )
                self.audio_manager.outgoing_data_queue.task_done()
                audio_sent_count += 1
                consecutive_errors = 0
                if audio_sent_count % 100 == 1:
                    print(f"[RealtimeClient] Sent {audio_sent_count} audio chunks to model")
            except Exception as exc:
                consecutive_errors += 1
                error_str = str(exc).lower()
                if "not connected" in error_str or "connection" in error_str:
                    print(f"[RealtimeClient] Connection lost: {exc}")
                    self.session = None
                    await asyncio.sleep(1)
                else:
                    print(f"[RealtimeClient] Error in audio processing: {exc}")
                    if consecutive_errors >= max_consecutive_errors:
                        print(f"[RealtimeClient] Too many errors, draining queue")
                        try:
                            while not self.audio_manager.outgoing_data_queue.empty():
                                self.audio_manager.outgoing_data_queue.get_nowait()
                                self.audio_manager.outgoing_data_queue.task_done()
                        except:
                            pass
                        consecutive_errors = 0
                    await asyncio.sleep(0.1)

    # ------------------------------------------------------------------
    # Interaction pipeline helpers
    # ------------------------------------------------------------------
    async def enqueue_action(self, action_name: str, *, source: str = "perform_action", wait_for_completion: bool = True) -> str:
        """Enqueue an action and optionally wait for it to complete."""
        action = (action_name or "").strip()
        if not action:
            return json.dumps({"status": "ignored", "reason": "empty_action"})

        action_id = f"{action}_{time.time()}_{id(self)}"

        completion_event = None
        if wait_for_completion:
            completion_event = asyncio.Event()
            self._action_completion_events[action_id] = completion_event

        item = _QueuedAction(name=action, enqueued_at=time.time(), source=source, action_id=action_id)
        await self._queued_actions.put(item)
        print(f"[RealtimeClient] Queued action '{action}' from {source}")

        if wait_for_completion and completion_event:
            try:
                await asyncio.wait_for(completion_event.wait(), timeout=30.0)
                print(f"[RealtimeClient] Action '{action}' completed")
                return json.dumps({"status": "completed", "action": action})
            except asyncio.TimeoutError:
                print(f"[RealtimeClient] Action '{action}' timed out")
                return json.dumps({"status": "timeout", "action": action})
            finally:
                if action_id in self._action_completion_events:
                    del self._action_completion_events[action_id]
        else:
            return json.dumps({"status": "queued", "action": action})

    async def _run_action_worker(self) -> None:
        """Background worker that executes queued actions."""
        print("[RealtimeClient] Action worker started.")
        try:
            while not self.is_shutdown:
                try:
                    item = await asyncio.wait_for(self._queued_actions.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break

                if self.is_shutdown:
                    self._queued_actions.task_done()
                    break

                try:
                    await self._audio_idle_event.wait()
                    if self.is_shutdown:
                        break
                    print(f"[RealtimeClient] Executing action '{item.name}'")
                    self._current_action_task = asyncio.create_task(self.action_manager.perform_action(item.name))
                    try:
                        await self._current_action_task
                        if item.action_id and item.action_id in self._action_completion_events:
                            self._action_completion_events[item.action_id].set()
                    except asyncio.CancelledError:
                        if item.action_id and item.action_id in self._action_completion_events:
                            self._action_completion_events[item.action_id].set()
                        raise
                    finally:
                        self._current_action_task = None
                except asyncio.CancelledError:
                    self._queued_actions.task_done()
                    break
                except Exception as exc:
                    print(f"[RealtimeClient] Error running action: {exc}")
                finally:
                    self._queued_actions.task_done()
        finally:
            print("[RealtimeClient] Action worker stopped.")

    async def _cancel_current_action(self, *, reason: str) -> None:
        if self._current_action_task and not self._current_action_task.done():
            print(f"[RealtimeClient] Cancelling current action ({reason})")
            self._current_action_task.cancel()
            try:
                await self._current_action_task
            except asyncio.CancelledError:
                pass
            finally:
                self._current_action_task = None
        if self.action_manager.isTakingAction or self.action_manager.isTalkingMovement:
            await self.action_manager.interrupt_actions(reset_posture=False)

    async def _drain_action_queue(self, *, reason: str) -> int:
        drained = 0
        while not self._queued_actions.empty():
            try:
                self._queued_actions.get_nowait()
                self._queued_actions.task_done()
                drained += 1
            except asyncio.QueueEmpty:
                break
        if drained:
            print(f"[RealtimeClient] Cleared {drained} queued actions ({reason})")
        return drained

    async def _clear_interaction_pipeline(self, *, reason: str, reset_pose: bool) -> None:
        """Clear all pending actions and audio."""
        print(f"[RealtimeClient] Clearing interaction pipeline ({reason})")
        await self._cancel_current_action(reason=reason)
        await self._drain_action_queue(reason=reason)
        try:
            self.audio_manager.interrupt_playback(reason)
        except Exception as exc:
            print(f"[RealtimeClient] Error clearing playback: {exc}")
        self.isReceivingAudio = False
        self._audio_idle_event.set()
        if reset_pose:
            try:
                await self.action_manager.interrupt_actions(reset_posture=True)
            except Exception as exc:
                print(f"[RealtimeClient] Error resetting posture: {exc}")

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def _touch_activity(self) -> None:
        """Update all activity timestamps to current time."""
        now = time.time()
        self.last_model_audio_time = now
        self.last_user_speech_time = now
        self.last_response_created_time = now

    def _set_first_response(self) -> None:
        """Set the first response event if not already set."""
        if not self.first_response_event.is_set():
            self.first_response_event.set()

    def is_quiet_for(self, duration: float) -> bool:
        """Check if there's been no activity for the specified duration."""
        last_activity = max(
            self.last_model_audio_time,
            self.last_user_speech_time,
            self.last_response_created_time,
        )
        if self.isReceivingAudio:
            return False
        return (time.time() - last_activity) >= duration
