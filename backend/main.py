from fastapi import (
    FastAPI,
    HTTPException,
    BackgroundTasks,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Set, Any
import os
import asyncio
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
import logging

from config.firebase_connect import FirebaseDB

load_dotenv()

app = FastAPI(title="AI Supervisor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = FirebaseDB()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ConnectionManager:

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(
            f"Dashboard client connected. Total: {len(self.active_connections)}"
        )

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(
            f"Dashboard client disconnected. Total: {len(self.active_connections)}"
        )

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return

        logger.info(
            f"Broadcasting to {len(self.active_connections)} dashboards: {message.get('type')}"
        )

        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to dashboard: {e}")
                disconnected.add(connection)

        for connection in disconnected:
            self.disconnect(connection)


class AgentConnectionManager:
    def __init__(self):
        self.active_agents: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_agents.add(websocket)
        logger.info(f"Agent connected. Total agents: {len(self.active_agents)}")

    def disconnect(self, websocket: WebSocket):
        self.active_agents.discard(websocket)
        logger.info(f"Agent disconnected. Total agents: {len(self.active_agents)}")

    async def broadcast_to_agents(self, message: dict):
        if not self.active_agents:
            logger.debug("No agents connected to broadcast to")
            return

        logger.info(
            f"Broadcasting to {len(self.active_agents)} agents: {message.get('type')}"
        )

        disconnected = set()
        for agent in self.active_agents:
            try:
                await agent.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to agent: {e}")
                disconnected.add(agent)

        for agent in disconnected:
            self.disconnect(agent)


dashboard_manager = ConnectionManager()
agent_manager = AgentConnectionManager()


def make_json_serializable(data: Any) -> Any:
    if isinstance(data, dict):
        return {key: make_json_serializable(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [make_json_serializable(item) for item in data]
    elif isinstance(data, datetime):
        return data.isoformat()
    elif hasattr(data, "isoformat"):  # Firebase DatetimeWithNanoseconds
        return data.isoformat()
    else:
        return data


class HelpRequestCreate(BaseModel):
    customer_phone: str
    question: str
    context: Optional[Dict] = {}


class SupervisorResponse(BaseModel):
    request_id: str
    response: str
    supervisor_id: Optional[str] = "admin"


class KnowledgeBaseEntry(BaseModel):
    question: str
    answer: str
    category: Optional[str] = "general"


# WebSocket Endpoints


@app.websocket("/ws")
async def websocket_dashboard(websocket: WebSocket):
    await dashboard_manager.connect(websocket)

    try:
        await websocket.send_json(
            {"type": "connected", "message": "Connected to admin dashboard"}
        )

        stats = db.get_request_stats()
        await websocket.send_json(
            {"type": "stats_update", "data": make_json_serializable(stats)}
        )

        pending = db.get_pending_requests()
        await websocket.send_json(
            {"type": "pending_requests", "data": make_json_serializable(pending)}
        )

        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})

    except WebSocketDisconnect:
        dashboard_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Dashboard WebSocket error: {e}")
        dashboard_manager.disconnect(websocket)


@app.websocket("/ws/agent")
async def websocket_agent(websocket: WebSocket):
    await agent_manager.connect(websocket)

    try:
        await websocket.send_json(
            {"type": "connected", "message": "Agent WebSocket connected"}
        )

        kb_entries = db.get_all_knowledge_base()
        await websocket.send_json(
            {
                "type": "knowledge_base_full",
                "data": make_json_serializable(kb_entries),
                "count": len(kb_entries),
            }
        )
        logger.info(f"Sent {len(kb_entries)} KB entries to agent")

        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)

                if data == "ping":
                    await websocket.send_text("pong")
                elif data == "refresh_kb":
                    kb_entries = db.get_all_knowledge_base()
                    await websocket.send_json(
                        {
                            "type": "knowledge_base_full",
                            "data": make_json_serializable(kb_entries),
                            "count": len(kb_entries),
                        }
                    )

            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})

    except WebSocketDisconnect:
        agent_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Agent WebSocket error: {e}")
        agent_manager.disconnect(websocket)


@app.get("/")
async def root():
    return {
        "status": "running",
        "service": "AI Supervisor",
        "dashboard_clients": len(dashboard_manager.active_connections),
        "connected_agents": len(agent_manager.active_agents),
    }


@app.get("/api/stats")
async def get_stats():
    stats = db.get_request_stats()
    return {"success": True, "stats": stats}


# Help Request Endpoints


@app.post("/api/help-requests")
async def create_help_request(request: HelpRequestCreate):
    try:
        request_id = db.create_help_request(
            customer_phone=request.customer_phone,
            question=request.question,
            context=request.context,
        )

        logger.info(f"New help request #{request_id}")
        logger.info(f"Question: {request.question}")

        await dashboard_manager.broadcast(
            {
                "type": "new_request",
                "data": make_json_serializable(
                    {
                        "id": request_id,
                        "customer_phone": request.customer_phone,
                        "question": request.question,
                        "status": "pending",
                        "created_at": datetime.now(),
                    }
                ),
            }
        )

        stats = db.get_request_stats()
        await dashboard_manager.broadcast(
            {"type": "stats_update", "data": make_json_serializable(stats)}
        )

        return {
            "success": True,
            "request_id": request_id,
            "message": "Help request created and supervisor notified",
        }
    except Exception as e:
        logger.error(f"Error creating help request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/help-requests/pending")
async def get_pending_requests():
    try:
        requests = db.get_pending_requests()
        return {"success": True, "requests": requests}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/help-requests/resolve")
async def resolve_request(
    response: SupervisorResponse, background_tasks: BackgroundTasks
):
    try:
        success = db.resolve_request(
            request_id=response.request_id,
            response=response.response,
            supervisor_id=response.supervisor_id,
        )

        if success:
            logger.info(f"Request {response.request_id} resolved")
            logger.info(f"Response: {response.response[:100]}...")

            background_tasks.add_task(
                notify_customer, response.request_id, response.response
            )

            await dashboard_manager.broadcast(
                {
                    "type": "request_resolved",
                    "data": make_json_serializable(
                        {
                            "request_id": response.request_id,
                            "response": response.response,
                        }
                    ),
                }
            )

            stats = db.get_request_stats()
            await dashboard_manager.broadcast(
                {"type": "stats_update", "data": make_json_serializable(stats)}
            )

            await agent_manager.broadcast_to_agents(
                {
                    "type": "knowledge_base_updated",
                    "message": "New knowledge base entry added",
                    "timestamp": datetime.now().isoformat(),
                }
            )

            logger.info("Notified agents of KB update")

            await dashboard_manager.broadcast(
                {
                    "type": "knowledge_base_updated",
                    "message": "Knowledge base has been updated",
                }
            )

            return {
                "success": True,
                "message": "Request resolved, customer notified, and agents updated",
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to resolve request")
    except Exception as e:
        logger.error(f"Error resolving request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/help-requests/history")
async def get_request_history():
    try:
        all_requests = db.get_all_requests()
        return {"success": True, "requests": all_requests}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Knowledge Base Endpoints


@app.get("/api/knowledge-base")
async def get_knowledge_base():
    try:
        entries = db.get_all_knowledge_base()
        return {"success": True, "entries": entries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/knowledge-base")
async def add_knowledge_base_entry(entry: KnowledgeBaseEntry):
    try:
        entry_id = db.add_to_knowledge_base(
            question=entry.question, answer=entry.answer
        )

        logger.info(f"New KB entry added manually: {entry_id}")

        await agent_manager.broadcast_to_agents(
            {
                "type": "knowledge_base_updated",
                "message": "Knowledge base entry added",
                "timestamp": datetime.now().isoformat(),
            }
        )

        await dashboard_manager.broadcast(
            {
                "type": "knowledge_base_updated",
                "message": "New entry added to knowledge base",
            }
        )

        return {
            "success": True,
            "entry_id": entry_id,
            "message": "Knowledge base entry added and agents notified",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/knowledge-base/search")
async def search_knowledge(question: str):
    try:
        result = db.search_knowledge_base(question)
        if result:
            return {"success": True, "found": True, "answer": result}
        else:
            return {"success": True, "found": False, "answer": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Background Tasks


async def notify_customer(request_id: str, response: str):
    logger.info(f"Sending SMS to Customer: Your question has been answered!")
    logger.info(f"Response: {response[:100]}...")
    logger.info(f"Reference: Request #{request_id}")


async def check_timeout_requests():
    while True:
        try:
            pending_requests = db.get_pending_requests()
            timeout_hours = int(os.getenv("SUPERVISOR_TIMEOUT_HOURS", "24"))

            for request in pending_requests:
                created_at = request.get("created_at")
                if created_at:
                    if datetime.now() - created_at > timedelta(hours=timeout_hours):
                        db.timeout_request(request["id"])
                        logger.info(f"Request {request['id']} marked as timeout")

                        await dashboard_manager.broadcast(
                            {
                                "type": "request_timeout",
                                "data": {"request_id": request["id"]},
                            }
                        )

                        stats = db.get_request_stats()
                        await dashboard_manager.broadcast(
                            {"type": "stats_update", "data": stats}
                        )

            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"Error checking timeouts: {e}")
            await asyncio.sleep(3600)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(check_timeout_requests())
    logger.info("AI Supervisor API Started")
    logger.info("Dashboard WebSocket: ws://localhost:8000/ws")
    logger.info("Agent WebSocket: ws://localhost:8000/ws/agent")
    logger.info("HTTP API: http://localhost:8000")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")), log_level="info"
    )
