from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Deque, Dict, Optional
from uuid import uuid4


@dataclass(slots=True)
class Event:
    """Represents a structured event emitted by the robot runtime."""

    type: str
    payload: Dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str = field(default_factory=lambda: uuid4().hex)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "id": self.id,
            "type": self.type,
            "timestamp": self.timestamp.isoformat(),
            "payload": self.payload,
        }
        if self.metadata:
            data["meta"] = self.metadata
        return data


class EventBus:
    """Simple asyncio-based publish/subscribe event bus with replay buffer."""

    def __init__(
        self,
        *,
        max_replay: int = 500,
        subscriber_queue_size: int = 200,
    ) -> None:
        self._replay: Deque[Event] = deque(maxlen=max_replay)
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._subscriber_queue_size = subscriber_queue_size
        self._lock = asyncio.Lock()

    async def publish(
        self,
        event_type: str,
        payload: Dict[str, Any],
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Event:
        event = Event(type=event_type, payload=payload, metadata=metadata or {})
        async with self._lock:
            self._replay.append(event)
            subscribers = list(self._subscribers)
        to_remove: list[asyncio.Queue[Event]] = []
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest item to make room, then reinsert
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    to_remove.append(queue)
            except RuntimeError:
                to_remove.append(queue)

        if to_remove:
            async with self._lock:
                for queue in to_remove:
                    self._subscribers.discard(queue)

        return event

    async def publish_event(self, event: Event) -> None:
        await self.publish(event.type, event.payload, metadata=event.metadata)

    async def broadcast_state(self, state: Dict[str, Any]) -> Event:
        return await self.publish(
            "state.diff",
            {"state": state},
            metadata={"source": "robot_core"},
        )

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._subscriber_queue_size)
        async with self._lock:
            self._subscribers.add(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                self._subscribers.discard(queue)

    def get_replay(self, *, limit: Optional[int] = None) -> list[Dict[str, Any]]:
        if limit is None:
            events = list(self._replay)
        else:
            events = list(self._replay)[-limit:]
        return [event.to_dict() for event in events]

    def clear(self) -> None:
        self._replay.clear()


__all__ = ["Event", "EventBus"]
