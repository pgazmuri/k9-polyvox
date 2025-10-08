"""Web interface package for PiDog control."""

from .event_bus import Event, EventBus
from .server import WebServer

__all__ = ["Event", "EventBus", "WebServer"]
