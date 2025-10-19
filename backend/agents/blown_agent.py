import os
import asyncio
import logging
import httpx
import websockets
import json
from datetime import datetime
from livekit import agents
from livekit.agents import Agent, AgentSession, RunContext
from livekit.agents.llm import function_tool
from livekit.plugins import openai, silero
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("salon-agent")
logger.setLevel(logging.INFO)

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
WS_URL = API_BASE_URL.replace("http://", "ws://").replace("https://", "wss://")


class SalonAssistant(Agent):
    BASE_INSTRUCTIONS = """You are an AI receptionist for Blown Salons.

BUSINESS DETAILS:
- Name: Blown Salons
- Address: MG Road, Bangalore
- Phone: 9382929399

SERVICES & PRICING:
- Haircut: 1000
- Hair Coloring: 1500  
- Highlights: 2000
- Manicure: 500
- Pedicure: 600
- Facial: 1000
- Full Makeover: 2500

HOURS:
- Tuesday to Sunday: 10:00 AM - 7:00 PM
- Monday: CLOSED

POLICIES:
- Appointments recommended, walk-ins accepted if available
- 24-hour cancellation policy
- 10% discount for first-time customers

STAFF:
- Shivani (Owner & Senior Stylist)
- Shweta (Hair Specialist)
- Priya (Nail Technician)
- Geeta (Makeup Artist)
"""

    def __init__(self):
        self.customer_phone = None
        self.http_client = None
        self.ws_client = None
        self.knowledge_base = []
        self.ws_task = None

        super().__init__(instructions=self.BASE_INSTRUCTIONS)

        logger.info("SalonAssistant initialized")

    @property
    def instructions(self) -> str:
        return self._build_full_instructions()

    def _build_full_instructions(self) -> str:
        instructions = self.BASE_INSTRUCTIONS

        if self.knowledge_base:
            instructions += "\n\n" + "=" * 70
            instructions += "\nLEARNED KNOWLEDGE FROM SUPERVISOR:\n"
            instructions += "=" * 70 + "\n"
            instructions += "Use this information to answer customer questions:\n\n"

            for i, entry in enumerate(self.knowledge_base, 1):
                instructions += f"{i}. Q: {entry['question']}\n"
                instructions += f"   A: {entry['answer']}\n\n"

        instructions += "\n" + "=" * 70
        instructions += "\nIMPORTANT INSTRUCTIONS:"
        instructions += "\n" + "=" * 70
        instructions += """
- Be friendly, warm, and professional
- Answer using the base information OR the learned knowledge above
- If you cannot find the answer in either, use escalate_to_supervisor function
- NEVER make up information not provided above
- Keep responses natural and conversational
- The knowledge base above is always current and up-to-date
"""

        return instructions

    async def load_knowledge_base(self):
        logger.info("Loading knowledge base from backend...")

        try:
            if not self.http_client:
                self.http_client = httpx.AsyncClient()

            response = await self.http_client.get(
                f"{API_BASE_URL}/api/knowledge-base", timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                self.knowledge_base = data.get("entries", [])
                logger.info(f"Loaded {len(self.knowledge_base)} entries into memory")
                return True
            else:
                logger.error(f"Failed to load KB: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error loading knowledge base: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    async def listen_for_kb_updates(self):
        ws_url = f"{WS_URL}/ws/agent"

        while True:
            try:
                logger.info(f"Connecting to agent WebSocket: {ws_url}")

                async with websockets.connect(ws_url) as websocket:
                    logger.info("Agent WebSocket connected")

                    while True:
                        try:
                            message = await websocket.recv()
                            data = json.loads(message)

                            await self._handle_ws_message(data)

                        except websockets.ConnectionClosed:
                            logger.warning("WebSocket connection closed")
                            break
                        except json.JSONDecodeError as e:
                            logger.error(f"Invalid JSON received: {e}")
                        except Exception as e:
                            logger.error(f"Error processing message: {e}")

            except Exception as e:
                logger.error(f"WebSocket connection error: {e}")
                logger.info("Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

    async def _handle_ws_message(self, data: dict):
        msg_type = data.get("type")

        if msg_type == "knowledge_base_updated":
            logger.info("Received KB update notification")
            await self.load_knowledge_base()
            logger.info("Agent knowledge refreshed in real-time!")
            logger.info(f"Now have {len(self.knowledge_base)} entries in memory")

        elif msg_type == "knowledge_base_entry":
            entry = data.get("data")
            if entry:
                logger.info(f"Received new KB entry: {entry['question']}")

                existing_index = next(
                    (
                        i
                        for i, e in enumerate(self.knowledge_base)
                        if e.get("id") == entry.get("id")
                    ),
                    None,
                )

                if existing_index is not None:
                    self.knowledge_base[existing_index] = entry
                    logger.info("Updated existing KB entry")
                else:
                    self.knowledge_base.append(entry)
                    logger.info("Added new KB entry")

                logger.info(f"Now have {len(self.knowledge_base)} entries in memory")

        elif msg_type == "ping":
            pass

    @function_tool
    async def escalate_to_supervisor(
        self, context: RunContext, customer_question: str, customer_phone: str
    ) -> str:
        logger.info(f"Escalating to supervisor")
        logger.info(f"Question: {customer_question}")

        try:
            if not self.http_client:
                self.http_client = httpx.AsyncClient()

            payload = {
                "customer_phone": customer_phone,
                "question": customer_question,
                "context": {
                    "escalated_at": datetime.now().isoformat(),
                    "agent": "salon-voice-agent",
                    "reason": "not_in_knowledge",
                },
            }

            response = await self.http_client.post(
                f"{API_BASE_URL}/api/help-requests", json=payload, timeout=10.0
            )

            logger.info(f"Response: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                request_id = result.get("request_id")
                logger.info(f"Help request created: {request_id}")

                return (
                    f"I've forwarded your question to my supervisor. "
                    f"They'll call you at {customer_phone} soon with the answer. "
                    f"Your reference number is {request_id}. "
                    f"Is there anything else I can help you with?"
                )
            else:
                logger.error(f"API error: {response.text}")
                return (
                    "I've noted your question and my supervisor will contact you soon. "
                    "Is there anything else I can help you with?"
                )

        except Exception as e:
            logger.error(f"Error escalating: {e}")
            return (
                "I've noted your question and my supervisor will reach out soon. "
                "What else can I help you with?"
            )


async def entrypoint(ctx: agents.JobContext):
    logger.info("Starting Salon Voice Agent with In-Memory Knowledge Base")

    logger.info("\nTesting backend connectivity...")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE_URL}/", timeout=5.0)
            logger.info(f"Backend is reachable: {response.json()}")
    except Exception as e:
        logger.error(f"Error testing backend connectivity: {e}")

    assistant = SalonAssistant()

    await assistant.load_knowledge_base()

    assistant.ws_task = asyncio.create_task(assistant.listen_for_kb_updates())
    logger.info("WebSocket listener started for real-time KB updates")

    session = AgentSession(
        stt=openai.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=openai.TTS(voice="alloy"),
        vad=silero.VAD.load(),
    )

    logger.info("\nStarting agent session...")

    await session.start(room=ctx.room, agent=assistant)

    logger.info("Agent session started")
    logger.info(f"Agent has {len(assistant.knowledge_base)} entries in memory")
    logger.info("Agent is listening for real-time KB updates")

    await session.generate_reply(
        instructions=(
            "Greet the customer warmly, welcome them to Blown Salons, "
            "and ask for their phone number so you can assist them better. "
            "Be friendly and conversational."
        )
    )

    logger.info("Agent is ready! KB is in memory and updates in real-time!")


if __name__ == "__main__":
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
        )
    )
