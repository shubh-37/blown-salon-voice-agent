from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
import os
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
import logging

from config.firebase_connect import FirebaseDB

load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="Frontdesk AI Supervisor API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Firebase
db = FirebaseDB()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Pydantic models for request/response
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


# API Endpoints


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "running", "service": "Frontdesk AI Supervisor"}


@app.get("/api/stats")
async def get_stats():
    """Get system statistics"""
    stats = db.get_request_stats()
    return {"success": True, "stats": stats}


# Help Request Endpoints


@app.post("/api/help-requests")
async def create_help_request(request: HelpRequestCreate):
    """Create a new help request (called by AI agent)"""
    try:
        request_id = db.create_help_request(
            customer_phone=request.customer_phone,
            question=request.question,
            context=request.context,
        )

        # Simulate SMS notification to supervisor
        logger.info(f"📱 SMS to Supervisor: New help request #{request_id}")
        logger.info(f"Question: {request.question}")

        return {
            "success": True,
            "request_id": request_id,
            "message": "Help request created and supervisor notified",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/help-requests/pending")
async def get_pending_requests():
    """Get all pending help requests (for supervisor dashboard)"""
    try:
        requests = db.get_pending_requests()
        return {"success": True, "requests": requests}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/help-requests/resolve")
async def resolve_request(
    response: SupervisorResponse, background_tasks: BackgroundTasks
):
    """Supervisor submits response to resolve a request"""
    try:
        success = db.resolve_request(
            request_id=response.request_id,
            response=response.response,
            supervisor_id=response.supervisor_id,
        )

        if success:
            # Simulate sending SMS to customer with the answer
            background_tasks.add_task(
                notify_customer, response.request_id, response.response
            )

            return {
                "success": True,
                "message": "Request resolved and customer notified",
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to resolve request")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/help-requests/history")
async def get_request_history():
    """Get all help requests (resolved, pending, timeout)"""
    try:
        # Get all requests from all status categories
        all_requests = []

        # This is simplified - you might want to create a single query in Firebase
        pending = db.get_pending_requests()
        all_requests.extend(pending)

        # You would add methods to get resolved and timeout requests
        # For now, returning what we have

        return {"success": True, "requests": all_requests}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Knowledge Base Endpoints


@app.get("/api/knowledge-base")
async def get_knowledge_base():
    """Get all knowledge base entries"""
    try:
        entries = db.get_all_knowledge_base()
        return {"success": True, "entries": entries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/knowledge-base")
async def add_knowledge_base_entry(entry: KnowledgeBaseEntry):
    """Manually add an entry to knowledge base"""
    try:
        entry_id = db.add_to_knowledge_base(
            question=entry.question, answer=entry.answer
        )
        return {
            "success": True,
            "entry_id": entry_id,
            "message": "Knowledge base entry added",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/knowledge-base/search")
async def search_knowledge(question: str):
    """Search knowledge base for an answer"""
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
    """Simulate sending SMS to customer with the answer"""
    # In production, this would integrate with Twilio or similar
    logger.info(f"📱 SMS to Customer: Your question has been answered!")
    logger.info(f"Response: {response}")
    logger.info(f"Reference: Request #{request_id}")


async def check_timeout_requests():
    """Background task to check for timed out requests"""
    while True:
        try:
            # Get pending requests and check if any have timed out
            pending_requests = db.get_pending_requests()
            timeout_hours = int(os.getenv("SUPERVISOR_TIMEOUT_HOURS", "24"))

            for request in pending_requests:
                created_at = request.get("created_at")
                if created_at:
                    # Check if request is older than timeout period
                    if datetime.now() - created_at > timedelta(hours=timeout_hours):
                        db.timeout_request(request["id"])
                        logger.info(f"Request {request['id']} marked as timeout")

                        # Notify customer about timeout
                        logger.info(
                            f"📱 SMS to Customer: We're still working on your question. Our team will contact you soon."
                        )

            # Check every hour
            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"Error checking timeouts: {e}")
            await asyncio.sleep(3600)


@app.on_event("startup")
async def startup_event():
    """Start background tasks on server startup"""
    asyncio.create_task(check_timeout_requests())
    logger.info("Frontdesk AI Supervisor API started")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
