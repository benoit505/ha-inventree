"""WebSocket client for InvenTree real-time events."""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Optional

import aiohttp
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


class ActivityState(Enum):
    """Activity states for smart polling."""
    ACTIVE = "active"      # Recent activity, poll frequently
    IDLE = "idle"          # Some activity, poll moderately  
    SLEEP = "sleep"        # No activity, poll slowly


class InvenTreeWebSocketClient:
    """WebSocket client for InvenTree events."""

    def __init__(
        self,
        websocket_url: str,
        on_event: Optional[Callable] = None,
        on_state_change: Optional[Callable] = None
    ):
        """Initialize the WebSocket client.
        
        Args:
            websocket_url: WebSocket URL (e.g., ws://host:9020)
            on_event: Callback for received events
            on_state_change: Callback when activity state changes
        """
        self.websocket_url = websocket_url
        self.on_event = on_event
        self.on_state_change = on_state_change
        
        self._ws = None
        self._session = None
        self._reconnect_task = None
        self._ping_task = None
        self._running = False
        self._connected = False
        
        # Activity tracking
        self.last_event_time = None
        self.activity_state = ActivityState.SLEEP
        
        # Reconnection settings
        self.reconnect_delay = 5  # seconds
        self.max_reconnect_delay = 300  # 5 minutes
        self.current_reconnect_delay = self.reconnect_delay
        
        # Event statistics
        self.event_count = 0
        self.connection_count = 0

    @property
    def is_connected(self) -> bool:
        """Return True if connected to WebSocket."""
        return self._connected

    @property
    def poll_interval(self) -> timedelta:
        """Get the current poll interval based on activity state."""
        intervals = {
            ActivityState.ACTIVE: timedelta(seconds=60),
            ActivityState.IDLE: timedelta(minutes=5),
            ActivityState.SLEEP: timedelta(minutes=15),
        }
        return intervals[self.activity_state]

    async def connect(self):
        """Connect to the WebSocket server."""
        if not self._session:
            self._session = aiohttp.ClientSession()
        
        try:
            _LOGGER.info("Connecting to InvenTree WebSocket at %s", self.websocket_url)
            self._ws = await self._session.ws_connect(
                self.websocket_url,
                heartbeat=30,
                timeout=10
            )
            self._connected = True
            self.connection_count += 1
            self.current_reconnect_delay = self.reconnect_delay
            
            _LOGGER.info("Connected to InvenTree WebSocket (connection #%d)", self.connection_count)
            
            # Start ping task
            if self._ping_task:
                self._ping_task.cancel()
            self._ping_task = asyncio.create_task(self._ping_loop())
            
        except Exception as err:
            _LOGGER.error("Failed to connect to WebSocket: %s", err)
            self._connected = False
            raise

    async def disconnect(self):
        """Disconnect from the WebSocket server."""
        self._running = False
        self._connected = False
        
        if self._ping_task:
            self._ping_task.cancel()
            self._ping_task = None
        
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None
        
        if self._ws and not self._ws.closed:
            await self._ws.close()
        
        if self._session and not self._session.closed:
            await self._session.close()
        
        _LOGGER.info("Disconnected from InvenTree WebSocket")

    async def _ping_loop(self):
        """Send periodic pings to keep connection alive."""
        try:
            while self._running and self._connected:
                await asyncio.sleep(30)
                if self._ws and not self._ws.closed:
                    await self._ws.send_json({"type": "ping"})
                    _LOGGER.debug("Sent WebSocket ping")
        except asyncio.CancelledError:
            pass
        except Exception as err:
            _LOGGER.error("Error in ping loop: %s", err)

    async def _handle_message(self, message: dict):
        """Handle incoming WebSocket message."""
        msg_type = message.get("type")
        
        if msg_type == "welcome":
            _LOGGER.info("Received welcome from InvenTree WebSocket server")
            _LOGGER.debug("Server info: %s", message)
            
        elif msg_type == "pong":
            _LOGGER.debug("Received pong from server")
            
        elif msg_type == "event":
            # This is what we care about!
            await self._handle_event(message)
            
        else:
            _LOGGER.debug("Received unknown message type: %s", msg_type)

    async def _handle_event(self, message: dict):
        """Handle an InvenTree event."""
        event_type = message.get("event", "")
        timestamp = message.get("timestamp")
        data = message.get("data", {})
        
        _LOGGER.debug("Received event: %s", event_type)
        _LOGGER.debug("Event data: %s", data)
        
        # Update activity tracking
        self.last_event_time = dt_util.now()
        self.event_count += 1
        
        # Update activity state
        await self._update_activity_state()
        
        # Call the event callback if provided
        if self.on_event:
            try:
                await self.on_event(event_type, data, timestamp)
            except Exception as err:
                _LOGGER.error("Error in event callback: %s", err)

    async def _update_activity_state(self):
        """Update the activity state based on last event time."""
        if not self.last_event_time:
            return
        
        now = dt_util.now()
        time_since_event = now - self.last_event_time
        
        old_state = self.activity_state
        
        # Determine new state
        if time_since_event < timedelta(minutes=5):
            new_state = ActivityState.ACTIVE
        elif time_since_event < timedelta(minutes=30):
            new_state = ActivityState.IDLE
        else:
            new_state = ActivityState.SLEEP
        
        # Update state if changed
        if new_state != old_state:
            _LOGGER.info(
                "Activity state changed: %s → %s (last event: %s ago)",
                old_state.value,
                new_state.value,
                time_since_event
            )
            self.activity_state = new_state
            
            # Call state change callback
            if self.on_state_change:
                try:
                    await self.on_state_change(new_state)
                except Exception as err:
                    _LOGGER.error("Error in state change callback: %s", err)

    async def listen(self):
        """Listen for WebSocket messages with auto-reconnect."""
        self._running = True
        
        while self._running:
            try:
                if not self._connected:
                    await self.connect()
                
                # Listen for messages
                async for msg in self._ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = json.loads(msg.data)
                            await self._handle_message(data)
                        except json.JSONDecodeError as err:
                            _LOGGER.error("Failed to decode WebSocket message: %s", err)
                    
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        _LOGGER.error("WebSocket error: %s", self._ws.exception())
                        break
                    
                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        _LOGGER.warning("WebSocket connection closed")
                        break
                
                # Connection closed, try to reconnect
                if self._running:
                    self._connected = False
                    _LOGGER.warning(
                        "WebSocket disconnected, reconnecting in %ds...",
                        self.current_reconnect_delay
                    )
                    await asyncio.sleep(self.current_reconnect_delay)
                    
                    # Exponential backoff
                    self.current_reconnect_delay = min(
                        self.current_reconnect_delay * 2,
                        self.max_reconnect_delay
                    )
            
            except asyncio.CancelledError:
                break
            
            except Exception as err:
                _LOGGER.error("Error in WebSocket listener: %s", err)
                self._connected = False
                
                if self._running:
                    _LOGGER.info(
                        "Reconnecting in %ds...",
                        self.current_reconnect_delay
                    )
                    await asyncio.sleep(self.current_reconnect_delay)
                    
                    # Exponential backoff
                    self.current_reconnect_delay = min(
                        self.current_reconnect_delay * 2,
                        self.max_reconnect_delay
                    )

    def get_stats(self) -> dict:
        """Get WebSocket statistics."""
        return {
            "connected": self._connected,
            "activity_state": self.activity_state.value,
            "poll_interval_seconds": self.poll_interval.total_seconds(),
            "event_count": self.event_count,
            "connection_count": self.connection_count,
            "last_event_time": self.last_event_time.isoformat() if self.last_event_time else None,
        }

