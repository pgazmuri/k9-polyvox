import asyncio
import logging
import multiprocessing
import os
import signal
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from action_manager import ActionManager
from audio_manager import AudioManager
from function_call_manager import FunctionCallManager
from keys import OPENAI_API_KEY
from realtime_client import RealtimeClient
from state_manager import RobotState
from web import EventBus, WebServer
from web.server import get_static_root
from system_prompts import personas as PERSONA_PRESETS

WS_URL = os.environ.get("K9_WS_URL", "wss://api.openai.com/v1/realtime")
MODEL = os.environ.get("K9_MODEL", "gpt-realtime")
DEFAULT_PERSONA = os.environ.get("K9_DEFAULT_PERSONA", "Vektor Pulsecheck")

LOGGER = logging.getLogger("robot_core")

SUPPORTED_VOICES = {
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
}


class RobotCore:
    """Encapsulates the lifecycle of the PiDog control stack."""

    def __init__(
        self,
        *,
        ws_url: str = WS_URL,
        model: str = MODEL,
        persona: str = DEFAULT_PERSONA,
        headers: Optional[dict[str, str]] = None,
        web_host: Optional[str] = None,
        web_port: Optional[int] = None,
        web_api_token: Optional[str] = None,
    ) -> None:
        self.ws_url = ws_url
        self.model = model
        self.persona = persona

        if headers is not None:
            self.headers = headers
        else:
            auth_header = f"Bearer {OPENAI_API_KEY}" if OPENAI_API_KEY else None
            self.headers = {"Authorization": auth_header} if auth_header else {}

        self.web_host = web_host or os.environ.get("K9_WEB_HOST", "0.0.0.0")
        self.web_port = web_port or int(os.environ.get("K9_WEB_PORT", "8080"))
        self.web_api_token = web_api_token or os.environ.get("K9_WEB_API_TOKEN")

        self.state = RobotState()
        self.event_bus = EventBus(max_replay=500)
        self.action_manager: Optional[ActionManager] = None
        self.audio_manager: Optional[AudioManager] = None
        self.client: Optional[RealtimeClient] = None
        self.function_call_manager: Optional[FunctionCallManager] = None
        self.web_server: Optional[WebServer] = None

        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._sensor_task: Optional[asyncio.Task] = None
        self._awareness_task: Optional[asyncio.Task] = None
        self.shutdown_task: Optional[asyncio.Task] = None
        self._state_stream_task: Optional[asyncio.Task] = None

        self._command_tasks: set[asyncio.Task[Any]] = set()

        self._is_running = False
        self._is_shutting_down = False
        self._signal_handlers_installed = False
        self._awareness_enabled = False
        self._sensors_enabled = False

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------
    async def run(self) -> None:
        try:
            await self._start()
            await self._run_loop()
        except asyncio.CancelledError:
            print("[RobotCore] Main task cancelled.")
        except Exception as exc:
            print(f"[RobotCore] Unhandled error: {exc}")
            traceback.print_exc()
        finally:
            LOGGER.info("RobotCore run loop finalizing; ensuring shutdown")
            await self._ensure_shutdown()
            self._remove_signal_handlers()

    # ------------------------------------------------------------------
    # Internal startup helpers
    # ------------------------------------------------------------------
    async def _start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._register_signal_handlers()
        self._is_running = True
        LOGGER.info("RobotCore starting core subsystems")
        await self._initialize_components()

    async def _initialize_components(self) -> None:
        self.action_manager = ActionManager(state=self.state, event_bus=self.event_bus)
        self.audio_manager = AudioManager(action_manager=self.action_manager, loop=self.loop)
        self.audio_manager.event_bus = self.event_bus  # type: ignore[attr-defined]
        self.client = RealtimeClient(
            ws_url=self.ws_url,
            model=self.model,
            headers=self.headers or None,
            function_call_manager=None,
            audio_manager=self.audio_manager,
            action_manager=self.action_manager,
        )
        self.client.event_bus = self.event_bus  # type: ignore[attr-defined]
        self.function_call_manager = FunctionCallManager(
            action_manager=self.action_manager,
            client=self.client,
        )
        self.client.function_call_manager = self.function_call_manager

        try:
            await self.client.connect()
            self.audio_manager.start_streams()

            session_task = asyncio.create_task(self.client.update_session(self.persona))
            await self.action_manager.initialize_posture()
            await session_task

            await self.client.send_awareness()

            try:
                await self.client.wait_for_first_response(timeout=15)
                print("[RobotCore] Initial response detected; starting environment monitoring.")
            except asyncio.TimeoutError:
                print("[RobotCore] Timed out waiting for initial response; continuing startup.")

            await self.set_sensors_enabled(True)
            await self.set_awareness_enabled(True)
        except Exception:
            print("[RobotCore] Error during startup sequence:")
            traceback.print_exc()
            raise

        await self.event_bus.broadcast_state(self.state.snapshot())
        self._state_stream_task = asyncio.create_task(self._state_stream_loop())

        static_root = get_static_root()
        self.web_server = WebServer(
            core=self,
            event_bus=self.event_bus,
            host=self.web_host,
            port=self.web_port,
            api_token=self.web_api_token,
            static_dir=static_root,
        )
        await self.web_server.start()

    async def _run_loop(self) -> None:
        print("[RobotCore] Event loop running. Press Ctrl+C to exit.")
        LOGGER.info("RobotCore run loop entered")
        while self._is_running:
            await asyncio.sleep(0.5)
        LOGGER.info("RobotCore run loop exiting")

    # ------------------------------------------------------------------
    # Signal handling
    # ------------------------------------------------------------------
    def _register_signal_handlers(self) -> None:
        if self._signal_handlers_installed:
            return
        loop = self.loop or asyncio.get_running_loop()
        self.loop = loop

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._schedule_shutdown, sig)
            except NotImplementedError:
                # Signal handlers may not be supported (e.g., on Windows)
                pass
        self._signal_handlers_installed = True

    def _remove_signal_handlers(self) -> None:
        if not self._signal_handlers_installed or not self.loop:
            return
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self.loop.remove_signal_handler(sig)
            except Exception:
                pass
        self._signal_handlers_installed = False

    def _schedule_shutdown(self, sig: Optional[signal.Signals] = None) -> None:
        if self.shutdown_task and not self.shutdown_task.done():
            print("[RobotCore] Shutdown already scheduled.")
            return
        LOGGER.info("Shutdown scheduled%s", f" (signal={sig.name})" if sig else "")
        loop = self.loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
        if loop is None:
            print("[RobotCore] Unable to locate event loop for shutdown request.")
            return
        self.loop = loop
        self.shutdown_task = loop.create_task(self.shutdown(sig))

    # ------------------------------------------------------------------
    # Shutdown sequence
    # ------------------------------------------------------------------
    async def shutdown(self, sig: Optional[signal.Signals] = None) -> None:
        if self._is_shutting_down:
            print("[RobotCore] Shutdown already in progress...")
            return
        self._is_shutting_down = True
        self._is_running = False

        if sig:
            print(f"[RobotCore] Received exit signal {sig.name}.")

        print("[RobotCore] Initiating shutdown sequence...")
        LOGGER.info("Shutdown sequence starting%s", f" (signal={sig.name})" if sig else "")

        try:
            LOGGER.info("Disabling awareness loop")
            await self.set_awareness_enabled(False)
            LOGGER.info("Awareness loop disabled")
        except Exception as exc:
            print(f"[RobotCore] Failed to disable awareness loop during shutdown: {exc}")
            LOGGER.exception("Failed disabling awareness loop during shutdown")
        try:
            LOGGER.info("Disabling sensor loop")
            await self.set_sensors_enabled(False)
            LOGGER.info("Sensor loop disabled")
        except Exception as exc:
            print(f"[RobotCore] Failed to disable sensor loop during shutdown: {exc}")
            LOGGER.exception("Failed disabling sensor loop during shutdown")

        if self._state_stream_task and not self._state_stream_task.done():
            LOGGER.info("Cancelling state stream task")
            self._state_stream_task.cancel()
            try:
                await self._state_stream_task
            except asyncio.CancelledError:
                pass
            LOGGER.info("State stream task cancelled")

        if self._command_tasks:
            LOGGER.info("Cancelling %d active command tasks", len(self._command_tasks))
        for task in list(self._command_tasks):
            task.cancel()

        if self.web_server:
            LOGGER.info("Stopping web server")
            await self.web_server.stop()
            LOGGER.info("Web server stopped")

        if self.client:
            print("[RobotCore] Closing realtime client...")
            LOGGER.info("Closing realtime client")
            await self.client.close()
            LOGGER.info("Realtime client closed")

        if self.audio_manager:
            print("[RobotCore] Closing audio manager...")
            LOGGER.info("Closing audio manager")
            self.audio_manager.close()
            LOGGER.info("Audio manager closed")

        if self.action_manager:
            print("[RobotCore] Closing action manager...")
            LOGGER.info("Closing action manager")
            try:
                await self.action_manager.close()
            except SystemExit as exc:
                print(f"[RobotCore] Ignoring PiDog SystemExit({exc.code}) during shutdown.")
                LOGGER.warning("Ignoring PiDog SystemExit(%s) during shutdown", exc.code)
            LOGGER.info("Action manager closed")

        self._log_threads_and_processes()
        print("[RobotCore] Shutdown sequence complete.")
        LOGGER.info("Shutdown sequence complete")

    async def _ensure_shutdown(self) -> None:
        LOGGER.info("Ensuring shutdown has completed")
        if self._is_shutting_down:
            if self.shutdown_task:
                try:
                    await self.shutdown_task
                except asyncio.CancelledError:
                    pass
            return
        LOGGER.info("Shutdown not yet in progress; invoking now")
        await self.shutdown()

    @staticmethod
    def _log_threads_and_processes() -> None:
        print("[RobotCore] Threads at shutdown:")
        for thread in threading.enumerate():
            print(f" - {thread.name} (daemon={thread.daemon})")

        print("[RobotCore] Active child processes:")
        for process in multiprocessing.active_children():
            print(
                f" - {process.name} (pid={process.pid}, alive={process.is_alive()})"
            )
            try:
                os.kill(process.pid, signal.SIGKILL)
                time.sleep(0.1)
                print(
                    f" - {process.name} (pid={process.pid}, alive={process.is_alive()}) after termination"
                )
            except ProcessLookupError:
                pass

    # ------------------------------------------------------------------
    # Command & loop management
    # ------------------------------------------------------------------
    async def enqueue_action(self, action_name: str, *, origin: str = "external") -> Dict[str, Any]:
        if not self.action_manager:
            raise RuntimeError("Action manager not initialized")

        command_id = uuid4().hex
        await self.event_bus.publish(
            "command.action.queued",
            {"id": command_id, "name": action_name, "origin": origin},
            metadata={"source": "robot_core"},
        )

        async def _run_action() -> None:
            try:
                await self.event_bus.publish(
                    "command.action.started",
                    {
                        "id": command_id,
                        "name": action_name,
                        "origin": origin,
                    },
                    metadata={"source": "robot_core"},
                )
                self.state.meta.current_action = action_name
                await self.event_bus.broadcast_state(self.state.snapshot())
                await self.action_manager.perform_action(action_name)
            except Exception as exc:
                await self.event_bus.publish(
                    "command.action.failed",
                    {
                        "id": command_id,
                        "name": action_name,
                        "origin": origin,
                        "error": str(exc),
                    },
                    metadata={"source": "robot_core"},
                )
                raise
            else:
                await self.event_bus.publish(
                    "command.action.completed",
                    {"id": command_id, "name": action_name, "origin": origin},
                    metadata={"source": "robot_core"},
                )
            finally:
                if self.state.meta.current_action == action_name:
                    self.state.meta.current_action = None
                self.state.meta.last_action = action_name
                await self.event_bus.broadcast_state(self.state.snapshot())

        task = asyncio.create_task(_run_action())
        self._command_tasks.add(task)
        task.add_done_callback(lambda t: self._command_tasks.discard(t))
        return {"commandId": command_id}

    async def send_custom_awareness(self, message: str, *, origin: str = "external") -> None:
        if not self.client:
            raise RuntimeError("Realtime client not initialized")
        await self.event_bus.publish(
            "command.awareness.queued",
            {"message": message, "origin": origin},
            metadata={"source": "robot_core"},
        )
        self.state.pending_stimulus = message
        await self.client.force_response(message)
        await self.event_bus.publish(
            "command.awareness.sent",
            {"message": message, "origin": origin},
            metadata={"source": "robot_core"},
        )

    async def set_awareness_enabled(self, enabled: bool) -> None:
        if enabled == self._awareness_enabled:
            return
        if enabled:
            if not self.action_manager or not self.client:
                raise RuntimeError("Core components not initialized")
            if not self._awareness_task or self._awareness_task.done():
                self._awareness_task = asyncio.create_task(
                    self.action_manager.awareness_heartbeat(self.client)
                )
        else:
            if self._awareness_task and not self._awareness_task.done():
                self._awareness_task.cancel()
                try:
                    await self._awareness_task
                except asyncio.CancelledError:
                    pass
            self._awareness_task = None
        self._awareness_enabled = enabled
        await self.event_bus.publish(
            "loop.status",
            {"loop": "awareness", "enabled": enabled},
            metadata={"source": "robot_core"},
        )

    async def set_sensors_enabled(self, enabled: bool) -> None:
        if enabled == self._sensors_enabled:
            return
        if not self.action_manager:
            raise RuntimeError("Action manager not initialized")
        if enabled and (not self.audio_manager or not self.client):
            raise RuntimeError("Core components not initialized")
        if enabled:
            self.action_manager.face_tracker.set_enabled(True)
            await self.action_manager.face_tracker.start()
            if not self._sensor_task or self._sensor_task.done():
                self._sensor_task = asyncio.create_task(
                    self.action_manager.monitor_sensors(self.audio_manager, self.client)
                )
        else:
            self.action_manager.face_tracker.set_enabled(False)
            await self.action_manager.face_tracker.stop()
            if self._sensor_task and not self._sensor_task.done():
                self._sensor_task.cancel()
                try:
                    await self._sensor_task
                except asyncio.CancelledError:
                    pass
            self._sensor_task = None
        self._sensors_enabled = enabled
        await self.event_bus.publish(
            "loop.status",
            {"loop": "sensors", "enabled": enabled},
            metadata={"source": "robot_core"},
        )

    def loop_status(self) -> Dict[str, Any]:
        return {
            "awareness": self._awareness_enabled,
            "sensors": self._sensors_enabled,
        }

    def action_catalog(self) -> Dict[str, Any]:
        if not self.action_manager:
            return {"actions": []}
        try:
            actions = sorted(self.action_manager.get_available_actions())
        except Exception:
            traceback.print_exc()
            actions = []
        return {"actions": actions}

    def get_camera_web_stream_status(self) -> Dict[str, Any]:
        from t2_vision import get_web_stream_status

        return get_web_stream_status()

    async def set_camera_web_stream(
        self,
        enabled: bool,
        *,
        frame_rate: Optional[int] = None,
        origin: str = "external",
    ) -> Dict[str, Any]:
        from t2_vision import set_web_stream

        status = set_web_stream(enabled, frame_rate)
        if self.event_bus:
            await self.event_bus.publish(
                "camera.web_stream.updated",
                {
                    "enabled": status.get("enabled"),
                    "frame_rate": status.get("frame_rate"),
                    "port": status.get("port"),
                    "path": status.get("path"),
                    "origin": origin,
                },
                metadata={"source": "robot_core"},
            )
        return status

    async def create_persona(self, payload: Dict[str, Any], *, origin: str = "external") -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Invalid persona payload")

        name = payload.get("name")
        if not isinstance(name, str):
            raise ValueError("Persona name must be a string")

        normalized_name = " ".join(name.strip().split())
        if not normalized_name:
            raise ValueError("Persona name cannot be empty")

        if any((p.get("name") or "").lower() == normalized_name.lower() for p in PERSONA_PRESETS):
            raise ValueError(f"Persona '{normalized_name}' already exists")

        def _sanitize_optional(field: str) -> Optional[str]:
            value = payload.get(field)
            if value is None:
                return None
            if not isinstance(value, str):
                raise ValueError(f"{field.replace('_', ' ').capitalize()} must be a string or null")
            stripped = value.strip()
            return stripped or None

        voice_value: Optional[str] = None
        if "voice" in payload:
            raw_voice = payload.get("voice")
            if raw_voice is not None and not isinstance(raw_voice, str):
                raise ValueError("Voice must be a string or null")
            voice_value = raw_voice.strip().lower() if isinstance(raw_voice, str) else None
            if voice_value and voice_value not in SUPPORTED_VOICES:
                raise ValueError(f"Voice '{voice_value}' is not supported")

        prompt_raw = payload.get("prompt")
        if isinstance(prompt_raw, str) and prompt_raw.strip():
            prompt_value = prompt_raw.strip()
        else:
            prompt_value = (
                f"You are {normalized_name}. Define this persona's motivations, voice, and signature quirks."
            )

        entry: Dict[str, Any] = {
            "name": normalized_name,
            "prompt": prompt_value,
        }

        if voice_value:
            entry["voice"] = voice_value

        description_value = _sanitize_optional("description")
        if description_value:
            entry["description"] = description_value

        default_motivation_value = _sanitize_optional("default_motivation")
        if default_motivation_value:
            entry["default_motivation"] = default_motivation_value

        image_prompt_value = _sanitize_optional("image_prompt")
        if image_prompt_value:
            entry["image_prompt"] = image_prompt_value

        PERSONA_PRESETS.append(entry)
        LOGGER.info("Persona '%s' created via %s", normalized_name, origin)

        if self.event_bus:
            await self.event_bus.publish(
                "persona.created",
                {"persona": dict(entry), "origin": origin},
                metadata={"source": "robot_core"},
            )

        return {"persona": dict(entry)}

    def get_persona_catalog(self) -> Dict[str, Any]:
        personas = [dict(persona) for persona in PERSONA_PRESETS]
        current_persona: Optional[Dict[str, Any]] = None
        current_name = None
        if self.client and getattr(self.client, "persona", None):
            current_persona = dict(self.client.persona)  # type: ignore[arg-type]
            current_name = current_persona.get("name")
        else:
            current_name = self.persona
            current_persona = next((dict(p) for p in PERSONA_PRESETS if p.get("name") == current_name), None)

        return {
            "personas": personas,
            "current": current_persona,
            "selected": current_name,
            "goal": self.state.goal,
        }

    async def switch_persona(self, persona_name: str, *, origin: str = "external") -> Dict[str, Any]:
        persona_names = {p["name"] for p in PERSONA_PRESETS}
        if persona_name not in persona_names:
            raise ValueError(f"Unknown persona '{persona_name}'")

        current_name = None
        if self.client and getattr(self.client, "persona", None):
            current_name = self.client.persona.get("name")  # type: ignore[union-attr]
        else:
            current_name = self.persona

        if current_name == persona_name:
            return {"status": "unchanged", "persona": current_name}

        await self.event_bus.publish(
            "persona.switch.requested",
            {"from": current_name, "to": persona_name, "origin": origin},
            metadata={"source": "robot_core"},
        )

        if not self.action_manager or not self.client:
            raise RuntimeError("Persona switch unavailable; components not initialized")

        await self.action_manager.handle_persona_switch_effects(persona_name, self.client)
        self.persona = persona_name
        return {"status": "switching", "persona": persona_name}

    async def set_goal(self, goal: str, *, origin: str = "external") -> Dict[str, Any]:
        normalized = goal.strip()
        if not normalized:
            raise ValueError("Goal cannot be empty")
        self.state.goal = normalized
        if self.client and getattr(self.client, "persona", None):
            self.client.persona["default_motivation"] = normalized  # type: ignore[index]
        await self.event_bus.publish(
            "interaction.goal.updated",
            {"goal": normalized, "origin": origin},
            metadata={"source": "robot_core"},
        )
        await self.event_bus.broadcast_state(self.state.snapshot())
        return {"goal": normalized}

    async def set_prompt(
        self,
        prompt: str,
        *,
        voice: Optional[str] = None,
        default_motivation: Optional[str] = None,
        image_prompt: Optional[str] = None,
        origin: str = "external",
    ) -> Dict[str, Any]:
        normalized_prompt = prompt.strip()
        if not normalized_prompt:
            raise ValueError("Prompt cannot be empty")

        persona_name: Optional[str] = None
        if self.client and getattr(self.client, "persona", None):
            persona_name = self.client.persona.get("name")  # type: ignore[index]
        if not persona_name:
            persona_name = self.persona
        if not persona_name:
            raise RuntimeError("No active persona to update")

        target = next((entry for entry in PERSONA_PRESETS if entry.get("name") == persona_name), None)
        if not target:
            raise ValueError(f"Unknown persona '{persona_name}'")

        target["prompt"] = normalized_prompt
        if self.client and getattr(self.client, "persona", None):
            self.client.persona["prompt"] = normalized_prompt  # type: ignore[index]

        previous_voice = target.get("voice")
        voice_value: Optional[str] = target.get("voice")
        voice_requires_restart = False

        if voice is not None:
            if not isinstance(voice, str):
                raise ValueError("Voice must be a string")
            candidate = voice.strip()
            voice_value = candidate.lower() or None
            if voice_value and voice_value not in SUPPORTED_VOICES:
                raise ValueError(f"Voice '{voice_value}' is not supported")

            if voice_value is not None:
                target["voice"] = voice_value
                if self.client and getattr(self.client, "persona", None):
                    self.client.persona["voice"] = voice_value  # type: ignore[index]
            else:
                target.pop("voice", None)
                if self.client and getattr(self.client, "persona", None):
                    self.client.persona.pop("voice", None)  # type: ignore[union-attr]

            voice_requires_restart = (voice_value or None) != (previous_voice or None)

        motivation_value: Optional[str] = None
        goal_updated = False
        if default_motivation is not None:
            motivation_value = default_motivation.strip() or None
            if motivation_value is not None:
                target["default_motivation"] = motivation_value
                if self.client and getattr(self.client, "persona", None):
                    self.client.persona["default_motivation"] = motivation_value  # type: ignore[index]
                self.state.goal = motivation_value
                goal_updated = True
            else:
                target.pop("default_motivation", None)
                if self.client and getattr(self.client, "persona", None):
                    self.client.persona.pop("default_motivation", None)  # type: ignore[union-attr]

        image_prompt_value: Optional[str] = None
        if image_prompt is not None:
            image_prompt_value = image_prompt.strip() or None
            if image_prompt_value is not None:
                target["image_prompt"] = image_prompt_value
                if self.client and getattr(self.client, "persona", None):
                    self.client.persona["image_prompt"] = image_prompt_value  # type: ignore[index]
            else:
                target.pop("image_prompt", None)
                if self.client and getattr(self.client, "persona", None):
                    self.client.persona.pop("image_prompt", None)  # type: ignore[union-attr]

        payload: Dict[str, Any] = {
            "persona": persona_name,
            "prompt": normalized_prompt,
            "origin": origin,
        }
        if voice is not None:
            payload["voice"] = voice_value
        if default_motivation is not None:
            payload["default_motivation"] = motivation_value
        if image_prompt is not None:
            payload["image_prompt"] = image_prompt_value

        await self.event_bus.publish(
            "persona.prompt.updated",
            payload,
            metadata={"source": "robot_core"},
        )

        if goal_updated:
            await self.event_bus.publish(
                "interaction.goal.updated",
                {"goal": self.state.goal, "origin": origin},
                metadata={"source": "robot_core"},
            )
            await self.event_bus.broadcast_state(self.state.snapshot())

        if self.client:
            try:
                if voice_requires_restart:
                    await self.client.reconnect(persona_name, dict(target))
                else:
                    await self.client.update_session(persona_name)
            except Exception:
                LOGGER.exception("Failed to refresh persona session after prompt update")

        return {
            "persona": persona_name,
            "prompt": normalized_prompt,
            "voice": voice_value,
            "default_motivation": motivation_value,
            "image_prompt": image_prompt_value,
        }

    async def instruct_response(self, instructions: str, *, origin: str = "external") -> Dict[str, Any]:
        normalized = instructions.strip()
        if not normalized:
            raise ValueError("Instructions cannot be empty")
        if not self.client:
            raise RuntimeError("Realtime client not initialized")

        await self.event_bus.publish(
            "command.instruction.queued",
            {"instructions": normalized, "origin": origin},
            metadata={"source": "robot_core"},
        )

        await self.client.create_instruction_response(normalized)

        await self.event_bus.publish(
            "command.instruction.sent",
            {"instructions": normalized, "origin": origin},
            metadata={"source": "robot_core"},
        )

        return {"status": "queued"}

    async def request_shutdown(self, *, origin: str = "external") -> Dict[str, Any]:
        LOGGER.info("Shutdown requested by %s", origin)
        await self.event_bus.publish(
            "system.shutdown.requested",
            {"origin": origin},
            metadata={"source": "robot_core"},
        )
        self._schedule_shutdown()
        return {"status": "shutting_down"}

    async def _state_stream_loop(self) -> None:
        previous: Optional[Dict[str, Any]] = None
        interval = float(os.environ.get("K9_STATE_STREAM_INTERVAL", "1.0"))
        try:
            while self._is_running:
                snapshot = self.state.snapshot()
                if snapshot != previous:
                    await self.event_bus.broadcast_state(snapshot)
                    previous = snapshot
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass


__all__ = ["RobotCore", "RobotState", "WS_URL", "MODEL", "DEFAULT_PERSONA"]
