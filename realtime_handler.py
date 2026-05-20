"""
⚡ Module WebSocket realtime updates
- Update blotter real-time
- Countdown timer
- Quote status changes
"""

import json
import logging
from typing import Dict, Set
from datetime import datetime
from fastapi import WebSocket
from enum import Enum

logger = logging.getLogger(__name__)

class EventType(str, Enum):
    """Loại sự kiện emit qua WebSocket"""
    QUOTE_SENT = "quote_sent"
    QUOTE_ACCEPTED = "quote_accepted"
    QUOTE_REJECTED = "quote_rejected"
    QUOTE_INTERRUPTED = "quote_interrupted"
    TRANSACTION_CREATED = "transaction_created"
    TRANSACTION_UPDATED = "transaction_updated"
    BLOTTER_UPDATE = "blotter_update"
    COUNTDOWN_TICK = "countdown_tick"
    SYSTEM_RATE_UPDATED = "system_rate_updated"
    MESSAGE_SENT = "message_sent"
    DATABASE_CLEARED = "database_cleared"

class RealtimeConnectionManager:
    """Quản lý WebSocket connections"""
    
    def __init__(self):
        # {user_id: Set[WebSocket]}
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        # {department: Set[WebSocket]}
        self.department_connections: Dict[str, Set[WebSocket]] = {}
    
    async def connect(self, user_id: int, websocket: WebSocket, department: str = None):
        """Connect user"""
        await websocket.accept()
        
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        
        self.active_connections[user_id].add(websocket)
        
        # Thêm vào department group
        if department:
            if department not in self.department_connections:
                self.department_connections[department] = set()
            self.department_connections[department].add(websocket)
        
        logger.info(f"✅ User {user_id} connected. Total: {len(self.active_connections)} users")
    
    def disconnect(self, user_id: int, websocket: WebSocket, department: str = None):
        """Disconnect user"""
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        
        # Remove from department
        if department and department in self.department_connections:
            self.department_connections[department].discard(websocket)
            if not self.department_connections[department]:
                del self.department_connections[department]
        
        logger.info(f"✅ User {user_id} disconnected")
    
    async def broadcast_to_user(self, user_id: int, message: dict):
        """Gửi message tới 1 user"""
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"❌ Error sending to user {user_id}: {e}")
    
    async def broadcast_to_department(self, department: str, message: dict):
        """Gửi message tới 1 phòng ban"""
        if department in self.department_connections:
            for connection in self.department_connections[department]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"❌ Error sending to department {department}: {e}")
    
    async def broadcast_to_all(self, message: dict):
        """Gửi message tới tất cả users"""
        for user_connections in self.active_connections.values():
            for connection in user_connections:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"❌ Error broadcasting: {e}")

# Global instance
ws_manager = RealtimeConnectionManager()

class RealtimeEventEmitter:
    """Emit realtime events"""
    
    @staticmethod
    async def quote_sent(user_id: int, transaction_data: dict):
        """Emit khi chào giá được gửi"""
        message = {
            "event": EventType.QUOTE_SENT.value,
            "data": transaction_data,
            "timestamp": datetime.utcnow().isoformat()
        }
        await ws_manager.broadcast_to_user(user_id, message)
    
    @staticmethod
    async def quote_accepted(quote_id: int, transaction_data: dict, user_id: int):
        """Emit khi chào giá được chấp nhận"""
        message = {
            "event": EventType.QUOTE_ACCEPTED.value,
            "quote_id": quote_id,
            "data": transaction_data,
            "timestamp": datetime.utcnow().isoformat()
        }
        await ws_manager.broadcast_to_user(user_id, message)
    
    @staticmethod
    async def quote_rejected(quote_id: int, transaction_id: int, reason: str = None):
        """Emit khi chào giá bị từ chối"""
        message = {
            "event": EventType.QUOTE_REJECTED.value,
            "quote_id": quote_id,
            "transaction_id": transaction_id,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat()
        }
        # Broadcast tới tất cả (PQL cần biết)
        await ws_manager.broadcast_to_all(message)
    
    @staticmethod
    async def quote_interrupted(quote_id: int, transaction_id: int, interrupted_by: int, interrupted_by_name: str):
        """Emit khi chào giá bị giành lại"""
        message = {
            "event": EventType.QUOTE_INTERRUPTED.value,
            "quote_id": quote_id,
            "transaction_id": transaction_id,
            "interrupted_by": interrupted_by,
            "interrupted_by_name": interrupted_by_name,
            "timestamp": datetime.utcnow().isoformat()
        }
        await ws_manager.broadcast_to_all(message)
    
    @staticmethod
    async def transaction_updated(transaction_id: int, transaction_data: dict, user_id: int = None):
        """Emit khi giao dịch update"""
        message = {
            "event": EventType.TRANSACTION_UPDATED.value,
            "transaction_id": transaction_id,
            "data": transaction_data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if user_id:
            await ws_manager.broadcast_to_user(user_id, message)
        else:
            await ws_manager.broadcast_to_all(message)
    
    @staticmethod
    async def blotter_update(department: str, blotter_data: dict):
        """Emit khi blotter update"""
        message = {
            "event": EventType.BLOTTER_UPDATE.value,
            "department": department,
            "data": blotter_data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if department:
            await ws_manager.broadcast_to_department(department, message)
        else:
            await ws_manager.broadcast_to_all(message)
    
    @staticmethod
    async def countdown_tick(quote_id: int, seconds_left: int, user_id: int):
        """Emit countdown mỗi giây"""
        message = {
            "event": EventType.COUNTDOWN_TICK.value,
            "quote_id": quote_id,
            "seconds_left": seconds_left,
            "timestamp": datetime.utcnow().isoformat()
        }
        await ws_manager.broadcast_to_user(user_id, message)
    
    @staticmethod
    async def system_rate_updated(currency: str, buy_rate: float, sell_rate: float):
        """Emit khi tỷ giá hệ thống update"""
        message = {
            "event": EventType.SYSTEM_RATE_UPDATED.value,
            "currency": currency,
            "buy_rate": buy_rate,
            "sell_rate": sell_rate,
            "timestamp": datetime.utcnow().isoformat()
        }
        await ws_manager.broadcast_to_all(message)
    
    @staticmethod
    async def message_sent(sender_id: int, recipient_id: int, message_data: dict):
        """Emit khi tin nhắn gửi"""
        event_data = {
            "event": EventType.MESSAGE_SENT.value,
            "sender_id": sender_id,
            "data": message_data,
            "timestamp": datetime.utcnow().isoformat()
        }
        await ws_manager.broadcast_to_user(recipient_id, event_data)
    
    @staticmethod
    async def database_cleared(cleared_by: str):
        """Emit khi database bị xóa"""
        message = {
            "event": EventType.DATABASE_CLEARED.value,
            "cleared_by": cleared_by,
            "timestamp": datetime.utcnow().isoformat()
        }
        await ws_manager.broadcast_to_all(message)


class CountdownTimer:
    """Countdown timer cho quote validity"""
    
    def __init__(self, quote_id: int, validity_seconds: int, user_id: int):
        self.quote_id = quote_id
        self.validity_seconds = validity_seconds
        self.remaining_seconds = validity_seconds
        self.user_id = user_id
        self.is_running = False
    
    async def start(self):
        """Start countdown"""
        import asyncio
        
        self.is_running = True
        
        while self.remaining_seconds > 0 and self.is_running:
            await RealtimeEventEmitter.countdown_tick(
                self.quote_id,
                self.remaining_seconds,
                self.user_id
            )
            
            self.remaining_seconds -= 1
            await asyncio.sleep(1)
        
        if self.remaining_seconds == 0:
            # Emit expired event
            await RealtimeEventEmitter.quote_rejected(
                quote_id=self.quote_id,
                transaction_id=None,
                reason="Quote expired"
            )
    
    def pause(self):
        """Pause countdown"""
        self.is_running = False
    
    def resume(self):
        """Resume countdown"""
        self.is_running = True
    
    def stop(self):
        """Stop countdown"""
        self.is_running = False
        self.remaining_seconds = 0


# Global timer tracking
active_timers: Dict[int, CountdownTimer] = {}

def register_timer(quote_id: int, timer: CountdownTimer):
    """Register countdown timer"""
    active_timers[quote_id] = timer

def unregister_timer(quote_id: int):
    """Unregister countdown timer"""
    if quote_id in active_timers:
        del active_timers[quote_id]

def get_timer(quote_id: int) -> CountdownTimer:
    """Get countdown timer"""
    return active_timers.get(quote_id)

def pause_timer(quote_id: int):
    """Pause timer"""
    timer = get_timer(quote_id)
    if timer:
        timer.pause()

def resume_timer(quote_id: int):
    """Resume timer"""
    timer = get_timer(quote_id)
    if timer:
        timer.resume()
