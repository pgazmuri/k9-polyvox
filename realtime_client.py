import asyncio
import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from agents.realtime.agent import RealtimeAgent  # type: ignore[import-not-found]
from agents.realtime.config import RealtimeRunConfig, RealtimeSessionModelSettings  # type: ignore[import-not-found]
from agents.realtime.events import (  # type: ignore[import-not-found]
    RealtimeAgentStartEvent,
    RealtimeAudio,
    RealtimeAudioEnd,
    RealtimeAudioInterrupted,
    RealtimeError,
    RealtimeHistoryAdded,
    RealtimeHistoryUpdated,
    RealtimeSessionEvent,
)
from agents.realtime.model import RealtimeModelConfig  # type: ignore[import-not-found]
from agents.realtime.runner import RealtimeRunner  # type: ignore[import-not-found]
from agents.realtime.session import RealtimeSession  # type: ignore[import-not-found]
from agents.tool import FunctionTool  # type: ignore[import-not-found]

from function_call_manager import admin_tools, get_base_tools
from system_prompts import personas
from prompt_builder import build_persona_instructions
from tool_builder import build_function_tools, extract_api_key


@dataclass
class _QueuedAction:
    name: str
    enqueued_at: float
    source: str = "perform_action"
    action_id: str = ""


class RealtimeClient:
    """Realtime client powered by the OpenAI Agents SDK."""

    def __init__(
        self,
        ws_url: str,
        model: str,
        headers: Optional[Dict[str, str]],
        function_call_manager,
        audio_manager,
        action_manager,
    ) -> None:
        self.ws_url = ws_url
        self.model = model
        self.headers = headers or {}

        self.function_call_manager = function_call_manager
        self.audio_manager = audio_manager
        self.action_manager = action_manager

        self.is_shutdown = False
        self.runner: Optional[RealtimeRunner] = None
        self.session: Optional[RealtimeSession] = None
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

        self.event_bus = None
        
        # Response state tracking to prevent race conditions
        self._response_active = False
        self._pending_awareness_request = None
        self._last_awareness_time = 0
        self._awareness_debounce = 1.5  # seconds - increased to prevent race conditions

        # SDK configuration
        self._api_key = extract_api_key(self.headers)
        self._bootstrap_agent = RealtimeAgent(
            name="bootstrap",
            instructions="",  # Empty to prevent automatic responses
            tools=[],
        )
        # Common audio settings used in both run config and session updates
        self._audio_settings = {
            "input_audio_noise_reduction": {"type": "far_field"},
            # "turn_detection": {
            #     "type": "semantic_vad",
            #     "eagerness": "high",
            #     "interrupt_response": True
            # }
            "turn_detection": {
                "type": "server_vad"
            }
        }
        
        # Use the audio_manager's model_rate to ensure sample rate consistency
        # OpenAI Realtime API supports both 16kHz and 24kHz
        model_rate = self.audio_manager.model_rate
        print(f"[RealtimeClient] Configuring audio format for {model_rate} Hz sample rate")
        
        self._run_config: RealtimeRunConfig = {
            "model_settings": {
                "model_name": self.model,
                "modalities": ["audio"],
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "tool_choice": "auto",
                **self._audio_settings
            }
        }

                # No longer need session_handlers dictionary - handle events directly

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

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
            await self.session.close()
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
        tools = build_function_tools(
            self.function_call_manager,
            self.persona["name"],
            available_actions,
            personas,
            get_base_tools,
            admin_tools
        )

        session_settings: RealtimeSessionModelSettings = {
            "voice": self.persona["voice"],
            "tool_choice": "auto",
            **self._audio_settings
        }

        # Update model settings FIRST to avoid triggering automatic response
        self.session._base_model_settings = session_settings
        
        agent = RealtimeAgent(
            name=self.persona["name"],
            instructions=instructions,
            tools=tools
        )
        await self.session.update_agent(agent)

        print(f"[RealtimeClient] Session updated for persona '{persona}' with voice '{self.persona['voice']}'.")

        event_bus = getattr(self, "event_bus", None)
        if event_bus is not None:
            try:
                await event_bus.publish(
                    "persona.switch.completed",
                    {
                        "name": self.persona.get("name"),
                        "voice": self.persona.get("voice"),
                        "description": self.persona.get("description"),
                        "default_motivation": self.persona.get("default_motivation"),
                    },
                    metadata={"source": "realtime_client"},
                )
            except Exception as exc:
                print(f"[RealtimeClient] Failed to publish persona update: {exc}")

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
        except Exception as exc:
            print(f"[RealtimeClient] ERROR in reconnect: {exc}")
            import traceback
            traceback.print_exc()
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

    async def create_instruction_response(self, instructions: str) -> None:
        """Push instructions as a fresh user message so the agent responds immediately."""
        if not instructions:
            return
        cleaned = f"Internal Command: {instructions.strip()}"
        if not cleaned:
            return
        print(f"[RealtimeClient] Creating instruction response: {cleaned}")
        await self.send_text_message(cleaned, role="user")

    async def send_text_message(self, text: str, *, role: str = "user") -> None:
        """Send a text message to the session."""
        if not self.session:
            raise RuntimeError("Cannot send message: session not connected")
        
        try:
            print(f"[RealtimeClient] Sending {role} message: {text}")
            await self.session.send_message({
                "type": "message",
                "role": role,
                "content": [{"type": "input_text", "text": text or ""}],
            })
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
                b64_image = base64.b64encode(f.read()).decode("utf-8")
            await self.session.send_message({
                "type": "message",
                "role": "user",
                "content": [{"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64_image}"}],
            })
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
        print("[RealtimeClient] Connecting via OpenAI Agents SDK...")

        self.runner = RealtimeRunner(
            starting_agent=self._bootstrap_agent,
            config=self._run_config,
        )

        model_config: RealtimeModelConfig = {}
        if self._api_key:
            model_config["api_key"] = self._api_key
        if self.headers:
            model_config["headers"] = self.headers
        if self.ws_url:
            model_config["url"] = f"{self.ws_url}?model={self.model}"

        self.session = await self.runner.run(model_config=model_config)
        await self.session.__aenter__()
        print("[RealtimeClient] Connected to realtime session.")

        self._event_task = asyncio.create_task(self._dispatch_session_events())
        self._outgoing_audio_task = asyncio.create_task(self.process_outgoing_audio())
        self._audio_idle_event.set()
        self._action_worker_task = asyncio.create_task(self._run_action_worker())

    async def _dispatch_session_events(self) -> None:
        if not self.session:
            return
        print("[RealtimeClient] Listening for session events...")
        try:
            async for event in self.session:
                try:
                    await self._handle_session_event(event)
                except Exception as event_exc:
                    error_msg = str(event_exc)
                    print(f"[RealtimeClient] Error handling event {getattr(event, 'type', 'unknown')}: {event_exc}")
                    
                    # Handle tool-not-found errors gracefully (shouldn't happen with fallback tools, but defensive)
                    if "not found" in error_msg.lower() and "tool" in error_msg.lower():
                        print("[RealtimeClient] Tool not found - this shouldn't happen with fallback tools installed")
                        # Send a corrective message to the model
                        try:
                            await self.send_text_message(
                                "Error: You tried to call an action directly as a tool. All robotic actions must use the perform_action tool. "
                                "For example: perform_action(action_name='turn_head_forward') instead of calling turn_head_forward() directly.",
                                role="user"
                            )
                        except Exception:
                            pass  # Don't cascade errors
                    # Don't let individual event errors stop the event loop
        except asyncio.CancelledError:
            print("[RealtimeClient] Event loop cancelled.")
            raise  # Re-raise cancellation
        except Exception as exc:
            print(f"[RealtimeClient] SDK error in event loop: {exc}")
            # Mark session as disconnected but don't stop processing
            if "not connected" in str(exc).lower() or "connection" in str(exc).lower():
                print("[RealtimeClient] Connection lost, marking session as disconnected.")
                self.session = None

    async def _handle_session_event(self, event: RealtimeSessionEvent) -> None:
        """Dispatch session events to appropriate handlers."""
        event_type = getattr(event, "type", None)
        if not event_type:
            return

        #print(f"[ETLOG] Event Type: {event_type}")

        #log event details for debug purposes
        #print(f"[EDLOG] Event Details: {event}")

        # Direct event handling - no dictionary lookup needed
        if event_type == "audio":
            await self._handle_audio_event(event)
        elif event_type == "audio_end":
            await self._handle_audio_end(event)
        elif event_type == "audio_interrupted":
            await self._handle_audio_interrupted(event)
        elif event_type == "agent_start":
            self._handle_agent_start(event)
        elif event_type == "history_added":
            self._handle_history_added(event)
        elif event_type == "history_updated":
            self._handle_history_updated(event)
        elif event_type == "error":
                print(f"[RealtimeClient] Error from session: {getattr(event, 'error', None)}")

        if event_type == "raw_model_event":
            payload = getattr(event, "data", None)
            sub_type = getattr(payload, "type", None)
            inner_type = None
            inner_payload = getattr(payload, "data", None)
            if isinstance(inner_payload, dict):
                inner_type = inner_payload.get("type")
            elif hasattr(inner_payload, "type"):
                inner_type = getattr(inner_payload, "type", None)

            effective_type = inner_type or sub_type

            #print(f"[RealtimeClient] Raw model event -> sub_type={sub_type}, inner_type={inner_type}")

            if effective_type == "input_audio_buffer.speech_started":
                self.isDetectingUserSpeech = True
                self.last_user_speech_time = time.time()
                print("[RealtimeClient] 🎤 User speech started - known from input buffer event")
            elif effective_type == "input_audio_buffer.speech_stopped":
                self.isDetectingUserSpeech = False
                self.last_user_speech_time = time.time()
                print("[RealtimeClient] 🎤 User speech stopped - known from buffer event")
            elif effective_type == "input_audio_timeout_triggered":
                self.isDetectingUserSpeech = False
                self.last_user_speech_time = time.time()
                print("[RealtimeClient] 🎤 User speech ended - known from timeout trigger")
            elif sub_type == "error":
                print(f"[RealtimeClient] Error from session: {getattr(event, 'error', None)}")
        # Note: Removed raw_model_event handling - use high-level session events instead

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _handle_audio_event(self, event: RealtimeAudio) -> None:
        """Handle incoming audio from the model."""
        if not self.isReceivingAudio:
            self.isReceivingAudio = True
            self.last_model_audio_time = time.time()
            # Pause action dispatch when model starts speaking
            if self._audio_idle_event.is_set():
                print("[RealtimeClient] Model audio starting; pausing action dispatch.")
                self._audio_idle_event.clear()
            if hasattr(self.audio_manager, "last_user_audio_chunk_time"):
                gap_ms = (time.time() - self.audio_manager.last_user_audio_chunk_time) * 1000
                print(f"[LAT] user->first_model_audio: {gap_ms:.1f} ms")
            self._set_first_response()

        try:
            self.audio_manager.queue_audio(event.audio.data)
            self.last_model_audio_time = time.time()
        except Exception as exc:
            print(f"[RealtimeClient] Error queuing audio: {exc}")

    async def _handle_audio_end(self, event: RealtimeAudioEnd) -> None:
        """Handle audio end event - SDK manages response lifecycle."""
        if self.action_manager.isTalkingMovement:
            asyncio.create_task(self.action_manager.stop_talking())
        self.isReceivingAudio = False
        self.last_model_audio_time = time.time()
        if hasattr(self.audio_manager, "wait_for_playback_idle"):
            try:
                await self.audio_manager.wait_for_playback_idle(timeout=3.0)
            except asyncio.TimeoutError:
                print("[RealtimeClient] Timeout waiting for playback to drain after audio_end.")
        self._audio_idle_event.set()
        self._response_active = False
        print("[RealtimeClient] Audio response completed.")
        
        # Process pending awareness request if queued
        if self._pending_awareness_request:
            print("[RealtimeClient] Processing queued awareness request")
            self._pending_awareness_request = None
            await self._do_send_awareness()

    async def _handle_audio_interrupted(self, event: RealtimeAudioInterrupted) -> None:
        """User started speaking - interrupt everything immediately."""
        print("[RealtimeClient] 🎤 User speaking detected - interrupting robot!")
        self.isDetectingUserSpeech = True
        self.last_user_speech_time = time.time()
        
        # Clear all queued actions and audio immediately
        await self._clear_interaction_pipeline(reason="user_speech_detected", reset_pose=False)
        
        # Stop current audio playback
        if self.audio_manager:
            try:
                self.audio_manager.interrupt_playback("user_speech")
            except Exception as exc:
                print(f"[RealtimeClient] Error interrupting playback: {exc}")
        
        # Stop any talking movement
        if self.action_manager and self.action_manager.isTalkingMovement:
            try:
                await self.action_manager.stop_talking()
            except Exception as exc:
                print(f"[RealtimeClient] Error stopping talking: {exc}")
        
        self.isReceivingAudio = False
        self._response_active = False
        print("[RealtimeClient] Interruption complete - ready for user speech")

    def _handle_agent_start(self, event: RealtimeAgentStartEvent) -> None:
        """Handle agent start event - SDK manages response lifecycle."""
        self._response_active = True
        self.last_response_created_time = time.time()
        self._set_first_response()

    def _handle_history_added(self, event: RealtimeHistoryAdded) -> None:
        """Handle history added event."""
        if (item := getattr(event, "item", None)) and getattr(item, "role", None) == "assistant":
            for content in getattr(item, "content", []):
                if getattr(content, "type", None) == "text" and (text := getattr(content, "text", "")):
                    self._set_first_response()
                    print(f"Assistant: {text}")

    def _handle_history_updated(self, event: RealtimeHistoryUpdated) -> None:
        """Handle history updated event."""
        if event.history and (item := event.history[-1]) and getattr(item, "role", None) == "assistant":
            for content in getattr(item, "content", []):
                if getattr(content, "type", None) == "text" and (text := getattr(content, "text", "")):
                    print(f"Assistant (update): {text}")

    # Note: Removed _handle_raw_model_event - SDK provides high-level events (audio, audio_end, etc.)
    # Speech detection, interruptions, and transcripts are handled by session events

    # ------------------------------------------------------------------
    # Audio streaming to the model
    # ------------------------------------------------------------------
    async def process_outgoing_audio(self) -> None:
        """Process outgoing audio from the queue and send to the model."""
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
                    # Clear queue while disconnected to prevent unbounded growth
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

                await self.session.send_audio(resampled_bytes)
                self.audio_manager.outgoing_data_queue.task_done()
                audio_sent_count += 1
                consecutive_errors = 0  # Reset error counter on success
                if audio_sent_count % 100 == 1:  # Log every 100th send
                    print(f"[RealtimeClient] Sent {audio_sent_count} audio chunks to model, queue size: {self.audio_manager.outgoing_data_queue.qsize()}")
            except Exception as exc:
                consecutive_errors += 1
                error_str = str(exc).lower()
                if "not connected" in error_str or "connection" in error_str:
                    print(f"[RealtimeClient] Connection lost in audio processing: {exc}")
                    self.session = None
                    # Drain queue to prevent unbounded growth
                    drained = 0
                    try:
                        while not self.audio_manager.outgoing_data_queue.empty():
                            self.audio_manager.outgoing_data_queue.get_nowait()
                            self.audio_manager.outgoing_data_queue.task_done()
                            drained += 1
                    except:
                        pass
                    if drained > 0:
                        print(f"[RealtimeClient] Drained {drained} queued audio chunks after connection loss")
                    await asyncio.sleep(1)
                else:
                    print(f"[RealtimeClient] Error in process_outgoing_audio: {exc}")
                    # If too many consecutive errors, drain queue to prevent memory issues
                    if consecutive_errors >= max_consecutive_errors:
                        print(f"[RealtimeClient] Too many consecutive errors ({consecutive_errors}), draining audio queue")
                        drained = 0
                        try:
                            while not self.audio_manager.outgoing_data_queue.empty():
                                self.audio_manager.outgoing_data_queue.get_nowait()
                                self.audio_manager.outgoing_data_queue.task_done()
                                drained += 1
                        except:
                            pass
                        if drained > 0:
                            print(f"[RealtimeClient] Drained {drained} queued audio chunks due to persistent errors")
                        consecutive_errors = 0
                    await asyncio.sleep(0.1)

    # ------------------------------------------------------------------
    # Interaction pipeline helpers
    # ------------------------------------------------------------------
    async def enqueue_action(self, action_name: str, *, source: str = "perform_action", wait_for_completion: bool = True) -> str:
        """Enqueue an action and optionally wait for it to complete.
        
        Args:
            action_name: The action(s) to perform
            source: Source of the action request
            wait_for_completion: If True, waits until action completes before returning
            
        Returns:
            JSON string with status
        """
        action = (action_name or "").strip()
        if not action:
            return json.dumps({"status": "ignored", "reason": "empty_action"})

        # Create unique action ID
        action_id = f"{action}_{time.time()}_{id(self)}"
        
        # Create completion event if waiting
        completion_event = None
        if wait_for_completion:
            completion_event = asyncio.Event()
            self._action_completion_events[action_id] = completion_event
        
        item = _QueuedAction(name=action, enqueued_at=time.time(), source=source, action_id=action_id)
        await self._queued_actions.put(item)
        print(f"[RealtimeClient] Queued action '{action}' from {source} (id={action_id[:20]}...)")
        
        if wait_for_completion and completion_event:
            print(f"[RealtimeClient] Waiting for action '{action}' to complete...")
            try:
                # Wait up to 30 seconds for action to complete
                await asyncio.wait_for(completion_event.wait(), timeout=30.0)
                print(f"[RealtimeClient] Action '{action}' completed")
                return json.dumps({"status": "completed", "action": action})
            except asyncio.TimeoutError:
                print(f"[RealtimeClient] Action '{action}' timed out after 30s")
                return json.dumps({"status": "timeout", "action": action})
            finally:
                # Clean up completion event
                if action_id in self._action_completion_events:
                    del self._action_completion_events[action_id]
        else:
            return json.dumps({"status": "queued", "action": action, "action_id": action_id})

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
                    print(f"[RealtimeClient] Executing queued action '{item.name}' (source={item.source}, id={item.action_id[:20] if item.action_id else 'none'}...).")
                    self._current_action_task = asyncio.create_task(self.action_manager.perform_action(item.name))
                    try:
                        await self._current_action_task
                        print(f"[RealtimeClient] Action '{item.name}' finished successfully")
                        # Signal completion if someone is waiting
                        if item.action_id and item.action_id in self._action_completion_events:
                            self._action_completion_events[item.action_id].set()
                    except asyncio.CancelledError:
                        print(f"[RealtimeClient] Action '{item.name}' cancelled.")
                        # Still signal completion (with cancellation)
                        if item.action_id and item.action_id in self._action_completion_events:
                            self._action_completion_events[item.action_id].set()
                        raise
                    finally:
                        self._current_action_task = None
                except asyncio.CancelledError:
                    self._queued_actions.task_done()
                    break
                except Exception as exc:
                    print(f"[RealtimeClient] Error running action '{item.name}': {exc}")
                finally:
                    self._queued_actions.task_done()
        finally:
            print("[RealtimeClient] Action worker stopped.")

    async def _cancel_current_action(self, *, reason: str) -> None:
        if self._current_action_task and not self._current_action_task.done():
            print(f"[RealtimeClient] Cancelling current action due to {reason}...")
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
            print(f"[RealtimeClient] Cleared {drained} queued actions due to {reason}.")
        return drained

    async def _clear_interaction_pipeline(self, *, reason: str, reset_pose: bool) -> None:
        """Clear all pending actions and audio. SDK manages response lifecycle."""
        print(f"[RealtimeClient] Clearing interaction pipeline ({reason}).")
        await self._cancel_current_action(reason=reason)
        await self._drain_action_queue(reason=reason)
        try:
            self.audio_manager.interrupt_playback(reason)
        except Exception as exc:
            print(f"[RealtimeClient] Error clearing playback during {reason}: {exc}")
        self.isReceivingAudio = False
        self._audio_idle_event.set()
        # SDK manages response state - we just handle interruption via session.interrupt()
        if self.session:
            try:
                await self.session.interrupt()
            except Exception as exc:
                print(f"[RealtimeClient] Error sending interrupt to session: {exc}")
        if reset_pose:
            try:
                await self.action_manager.interrupt_actions(reset_posture=True)
            except Exception as exc:
                print(f"[RealtimeClient] Error resetting posture during {reason}: {exc}")

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
