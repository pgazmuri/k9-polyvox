from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .event_bus import EventBus

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from robot_core import RobotCore

LOGGER = logging.getLogger("web.server")

DEFAULT_STATIC_DIR = Path(__file__).resolve().parent / "static"


class WebServer:
    """FastAPI web layer for PiDog remote control."""

    def __init__(
        self,
        *,
        core: "RobotCore",
        event_bus: EventBus,
        host: str = "0.0.0.0",
        port: int = 80,
        api_token: Optional[str] = None,
        static_dir: Optional[Path] = None,
        cors_origins: Optional[list[str]] = None,
    ) -> None:
        self.core = core
        self.event_bus = event_bus
        self.host = host
        self.port = port
        self.api_token = api_token
        self.static_dir = static_dir or DEFAULT_STATIC_DIR
        self.cors_origins = cors_origins or ["*"]  # Allow LAN access by default

        self.app = FastAPI(title="PiDog Control", version="0.1.0")
        self._server: Optional[uvicorn.Server] = None
        self._serve_task: Optional[asyncio.Task[None]] = None

        self._configure_middleware()
        self._register_routes()
        self._mount_static()

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        if self._server is not None:
            return
        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info",
            loop="asyncio",
            timeout_keep_alive=25,
        )
        self._server = uvicorn.Server(config)
        self._serve_task = asyncio.create_task(self._server.serve())
        LOGGER.info("Web server starting on http://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        if not self._server:
            return
        LOGGER.info("Requesting web server shutdown")
        self._server.should_exit = True
        if self._serve_task:
            try:
                LOGGER.debug("Awaiting web server serve task to finish")
                await asyncio.wait_for(self._serve_task, timeout=5)
            except asyncio.TimeoutError:
                LOGGER.warning("Web server shutdown timed out; forcing exit.")
                self._server.force_exit = True
                await self._serve_task
            except Exception:
                LOGGER.exception("Unexpected error while stopping web server")
                raise
        self._server = None
        self._serve_task = None
        LOGGER.info("Web server stopped")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _configure_middleware(self) -> None:
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=self.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _register_routes(self) -> None:
        @self.app.get("/api/state")
        async def get_state(_: None = Depends(self._require_token)) -> Dict[str, Any]:
            return self.core.state.snapshot()

        @self.app.get("/api/actions/history")
        async def get_action_history(_: None = Depends(self._require_token)) -> Dict[str, Any]:
            events = self.event_bus.get_replay()
            filtered = [event for event in events if event["type"].startswith("action.")]
            return {"events": filtered}

        @self.app.get("/api/actions/catalog")
        async def get_action_catalog(_: None = Depends(self._require_token)) -> Dict[str, Any]:
            return self.core.action_catalog()

        @self.app.post("/api/actions/trigger")
        async def trigger_action(request: Request, _: None = Depends(self._require_token)) -> JSONResponse:
            data = await request.json()
            action = data.get("name")
            origin = data.get("origin", "web-ui")
            if not action:
                raise HTTPException(status_code=400, detail="Missing action name")
            result = await self.core.enqueue_action(action, origin=origin)
            return JSONResponse({"status": "accepted", "details": result})

        @self.app.post("/api/awareness/custom")
        async def custom_awareness(request: Request, _: None = Depends(self._require_token)) -> Dict[str, Any]:
            data = await request.json()
            message = data.get("message")
            if not message:
                raise HTTPException(status_code=400, detail="Missing message")
            origin = data.get("origin", "web-ui")
            await self.core.send_custom_awareness(message, origin=origin)
            return {"status": "queued"}

        @self.app.post("/api/loops")
        async def update_loops(request: Request, _: None = Depends(self._require_token)) -> Dict[str, Any]:
            data = await request.json()
            loops = {}
            if "awareness" in data:
                enabled = bool(data["awareness"])
                await self.core.set_awareness_enabled(enabled)
                loops["awareness"] = enabled
            if "sensors" in data:
                enabled = bool(data["sensors"])
                await self.core.set_sensors_enabled(enabled)
                loops["sensors"] = enabled
            return {"loops": loops or self.core.loop_status()}

        @self.app.get("/api/loops")
        async def get_loops(_: None = Depends(self._require_token)) -> Dict[str, Any]:
            return self.core.loop_status()

        @self.app.get("/api/camera/web-stream")
        async def get_camera_stream_status(
            request: Request, _: None = Depends(self._require_token)
        ) -> Dict[str, Any]:
            status = self.core.get_camera_web_stream_status()
            return self._format_stream_response(request, status)

        @self.app.post("/api/camera/web-stream")
        async def update_camera_stream(
            request: Request, _: None = Depends(self._require_token)
        ) -> Dict[str, Any]:
            payload = await request.json()
            if "enabled" not in payload:
                raise HTTPException(status_code=400, detail="Missing 'enabled' flag")

            enabled_value = payload["enabled"]
            if isinstance(enabled_value, bool):
                enabled = enabled_value
            elif isinstance(enabled_value, (int, float)):
                enabled = bool(enabled_value)
            elif isinstance(enabled_value, str):
                lowered = enabled_value.strip().lower()
                if lowered in {"true", "1", "yes", "on"}:
                    enabled = True
                elif lowered in {"false", "0", "no", "off"}:
                    enabled = False
                else:
                    raise HTTPException(status_code=400, detail="Invalid value for 'enabled'")
            else:
                raise HTTPException(status_code=400, detail="Invalid value for 'enabled'")

            frame_rate_value = payload.get("frameRate", payload.get("frame_rate"))
            frame_rate: Optional[int] = None
            if frame_rate_value is not None:
                try:
                    frame_rate = int(frame_rate_value)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail="frameRate must be an integer")

            origin = payload.get("origin", "web-ui")

            try:
                status = await self.core.set_camera_web_stream(
                    enabled,
                    frame_rate=frame_rate,
                    origin=origin,
                )
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

            return self._format_stream_response(request, status)

        @self.app.get("/api/personas")
        async def get_personas(_: None = Depends(self._require_token)) -> Dict[str, Any]:
            return self.core.get_persona_catalog()

        @self.app.post("/api/personas")
        async def create_persona(request: Request, _: None = Depends(self._require_token)) -> Dict[str, Any]:
            payload = await request.json()
            origin = payload.get("origin", "web-ui")
            persona_payload = {
                "name": payload.get("name"),
                "voice": payload.get("voice"),
                "prompt": payload.get("prompt"),
                "default_motivation": payload.get("default_motivation"),
                "image_prompt": payload.get("image_prompt"),
                "description": payload.get("description"),
            }
            try:
                return await self.core.create_persona(persona_payload, origin=origin)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc))

        @self.app.post("/api/personas/switch")
        async def switch_persona(request: Request, _: None = Depends(self._require_token)) -> Dict[str, Any]:
            payload = await request.json()
            name = payload.get("name") or payload.get("persona")
            if not name or not isinstance(name, str):
                raise HTTPException(status_code=400, detail="Missing persona name")

            origin = payload.get("origin", "web-ui")
            try:
                result = await self.core.switch_persona(name, origin=origin)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc))

            return result

        @self.app.post("/api/interaction/goal")
        async def update_goal(request: Request, _: None = Depends(self._require_token)) -> Dict[str, Any]:
            payload = await request.json()
            goal = payload.get("goal")
            if not isinstance(goal, str):
                raise HTTPException(status_code=400, detail="Goal must be a string")
            origin = payload.get("origin", "web-ui")
            try:
                return await self.core.set_goal(goal, origin=origin)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))

        @self.app.post("/api/interaction/prompt")
        async def update_prompt(request: Request, _: None = Depends(self._require_token)) -> Dict[str, Any]:
            payload = await request.json()
            prompt = payload.get("prompt")
            if not isinstance(prompt, str):
                raise HTTPException(status_code=400, detail="Prompt must be a string")

            voice = payload.get("voice")
            if voice is not None and not isinstance(voice, str):
                raise HTTPException(status_code=400, detail="Voice must be a string or null")

            motivation = payload.get("default_motivation")
            if motivation is not None and not isinstance(motivation, str):
                raise HTTPException(status_code=400, detail="Default motivation must be a string or null")

            image_prompt = payload.get("image_prompt")
            if image_prompt is not None and not isinstance(image_prompt, str):
                raise HTTPException(status_code=400, detail="Image prompt must be a string or null")

            origin = payload.get("origin", "web-ui")
            try:
                return await self.core.set_prompt(
                    prompt,
                    voice=voice,
                    default_motivation=motivation,
                    image_prompt=image_prompt,
                    origin=origin,
                )
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(status_code=400, detail=str(exc))

        @self.app.post("/api/system/shutdown")
        async def shutdown_system(request: Request, _: None = Depends(self._require_token)) -> Dict[str, Any]:
            payload = await request.json() if request.headers.get("content-length") not in ("0", None) else {}
            origin = payload.get("origin", "web-ui")
            return await self.core.request_shutdown(origin=origin)

        @self.app.post("/api/interaction/instruct")
        async def instruct_response(request: Request, _: None = Depends(self._require_token)) -> Dict[str, Any]:
            payload = await request.json()
            instructions = payload.get("instructions")
            if not isinstance(instructions, str):
                raise HTTPException(status_code=400, detail="Instructions must be a string")
            origin = payload.get("origin", "web-ui")
            try:
                return await self.core.instruct_response(instructions, origin=origin)
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(status_code=400, detail=str(exc))

        @self.app.websocket("/ws/events")
        async def events_socket(websocket: WebSocket) -> None:
            token = websocket.headers.get("x-api-key") or websocket.query_params.get("token")
            if not self._is_authorized(token):
                await websocket.close(code=4401)
                return
            await websocket.accept()
            try:
                replay = self.event_bus.get_replay()
                for event in replay:
                    try:
                        await websocket.send_json(event)
                    except WebSocketDisconnect:
                        LOGGER.debug("Websocket closed during replay streaming")
                        return

                async with self.event_bus.subscribe() as queue:
                    while True:
                        event = await queue.get()
                        try:
                            await websocket.send_json(event.to_dict())
                        except WebSocketDisconnect:
                            LOGGER.debug("Websocket disconnected")
                            break
            except WebSocketDisconnect:
                LOGGER.debug("Websocket disconnected before streaming began")

        @self.app.get("/")
        async def root() -> HTMLResponse:
            index = self._resolve_index_file()
            if index:
                return HTMLResponse(index.read_text(encoding="utf-8"))
            return HTMLResponse("<h1>PiDog Control</h1><p>Frontend build not found.</p>")

    def _mount_static(self) -> None:
        if not self.static_dir.exists():
            LOGGER.warning("Static directory %s does not exist; UI assets unavailable.", self.static_dir)
            return
        self.app.mount(
            "/static",
            StaticFiles(directory=str(self.static_dir), html=True),
            name="static",
        )

    def _format_stream_response(self, request: Request, status: Dict[str, Any]) -> Dict[str, Any]:
        response = {
            "enabled": bool(status.get("enabled", False)),
            "frameRate": status.get("frame_rate"),
            "port": status.get("port"),
            "path": status.get("path"),
        }
        response["streamUrl"] = self._build_stream_url(request, status)
        return response

    def _build_stream_url(self, request: Request, status: Dict[str, Any]) -> Optional[str]:
        if not status.get("enabled"):
            return None

        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = request.url.hostname or (request.client.host if request.client else None)
        if not host:
            return None

        port = status.get("port")
        try:
            port_int = int(port) if port is not None else None
        except (TypeError, ValueError):
            port_int = None

        path = status.get("path") or "/"
        if not str(path).startswith("/"):
            path = f"/{path}"

        if port_int and port_int not in (80, 443):
            netloc = f"{host}:{port_int}"
        else:
            netloc = host

        return f"{scheme}://{netloc}{path}"

    def _resolve_index_file(self) -> Optional[Path]:
        candidates = [
            self.static_dir / "index.html",
            self.static_dir / "dist" / "index.html",
        ]
        for path in candidates:
            if path.exists():
                return path
        return None

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------
    async def _require_token(self, request: Request) -> None:
        token = request.headers.get("x-api-key")
        if not self._is_authorized(token):
            raise HTTPException(status_code=401, detail="Unauthorized")

    def _is_authorized(self, token: Optional[str]) -> bool:
        if not self.api_token:
            return True
        return token == self.api_token

    def loop_status(self) -> Dict[str, Any]:
        return self.core.loop_status()


@lru_cache(maxsize=1)
def get_static_root() -> Path:
    env_path = os.environ.get("K9_UI_STATIC_DIR")
    if env_path:
        return Path(env_path)
    return DEFAULT_STATIC_DIR


__all__ = ["WebServer", "get_static_root"]
