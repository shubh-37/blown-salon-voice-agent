from pydantic import BaseModel, Field
from typing import Optional, Dict, List
from datetime import datetime
from enum import Enum


class RequestStatus(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    TIMEOUT = "timeout"


class HelpRequest(BaseModel):
    id: Optional[str] = None
    customer_phone: str = Field(..., description="Customer's phone number")
    question: str = Field(..., description="Question that needs supervisor help")
    context: Dict = Field(default_factory=dict, description="Additional context")
    status: RequestStatus = Field(default=RequestStatus.PENDING)
    created_at: datetime = Field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None
    supervisor_response: Optional[str] = None
    assigned_to: Optional[str] = None

    class Config:
        use_enum_values = True
        json_encoders = {datetime: lambda v: v.isoformat()}

    def to_dict(self) -> Dict:
        data = self.dict()
        if data.get("created_at"):
            data["created_at"] = self.created_at
        if data.get("resolved_at"):
            data["resolved_at"] = self.resolved_at
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> "HelpRequest":
        return cls(**data)


class KnowledgeBaseEntry(BaseModel):
    id: Optional[str] = None
    question: str = Field(..., description="Question")
    answer: str = Field(..., description="Answer from supervisor")
    category: str = Field(default="general", description="Category for organization")
    created_from_request: Optional[str] = Field(
        None, description="Source help request ID"
    )
    usage_count: int = Field(default=0, description="How many times this has been used")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

    def to_dict(self) -> Dict:
        data = self.dict()
        if data.get("created_at"):
            data["created_at"] = self.created_at
        if data.get("updated_at"):
            data["updated_at"] = self.updated_at
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> "KnowledgeBaseEntry":
        return cls(**data)


class ConversationMessage(BaseModel):
    role: str = Field(..., description="'user' or 'agent'")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(default_factory=datetime.now)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

    def to_dict(self) -> Dict:
        data = self.dict()
        if data.get("timestamp"):
            data["timestamp"] = self.timestamp
        return data


class Conversation(BaseModel):
    id: Optional[str] = None
    customer_phone: str = Field(..., description="Customer's phone number")
    transcript: List[ConversationMessage] = Field(default_factory=list)
    escalated: bool = Field(default=False)
    resolved: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.now)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

    def to_dict(self) -> Dict:
        data = self.dict()
        if data.get("created_at"):
            data["created_at"] = self.created_at
        if data.get("transcript"):
            data["transcript"] = [msg.to_dict() for msg in self.transcript]
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> "Conversation":
        if "transcript" in data and isinstance(data["transcript"], list):
            data["transcript"] = [
                ConversationMessage(**msg) if isinstance(msg, dict) else msg
                for msg in data["transcript"]
            ]
        return cls(**data)


class RequestStats(BaseModel):
    total: int = 0
    pending: int = 0
    resolved: int = 0
    timeout: int = 0
    avg_resolution_time: float = 0.0

    class Config:
        json_encoders = {float: lambda v: round(v, 2)}


class Collections:
    HELP_REQUESTS = "help_requests"
    KNOWLEDGE_BASE = "knowledge_base"
    CONVERSATIONS = "conversations"
