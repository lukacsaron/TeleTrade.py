# models/signal_models.py
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class SignalModel(BaseModel):
    signal_id: str
    type: str = "Signal"
    instrument: str
    action: str
    entry_price_range: Optional[dict] = None
    stop_loss: Optional[float] = None
    take_profits: List[float]
    notes: Optional[List[str]] = []
    orders_placed: bool
    entry_fulfilled: bool
    tp_fulfilled: List[bool]
    sl_fulfilled: bool
    trade_closed: bool
    execution_details: dict
    timestamp: datetime
    message_id: int
    chat_id: int
