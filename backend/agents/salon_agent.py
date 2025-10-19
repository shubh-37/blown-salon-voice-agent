import os
import asyncio
import logging
from typing import Annotated
from livekit import agents, rtc
from livekit.agents import JobContext, WorkerOptions, cli, llm
from livekit.agents.voice_assistant import VoiceAssistant
from livekit.plugins import openai, silero
from dotenv import load_dotenv
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.firebase_config import FirebaseDB

load_dotenv()
logger = logging.getLogger("salon-agent")

# Initialize Firebase
db = FirebaseDB()

# Salon Information and Context
SALON_CONTEXT = """
You are an AI receptionist for Bella's Beauty Salon. Here's your information:

BUSINESS DETAILS:
- Name: Bella's Beauty Salon
- Address: 123 Main Street, Downtown
- Phone: (555) 123-4567

SERVICES & PRICING:
- Haircut: $50
- Hair Coloring: $120  
- Highlights: $150
- Manicure: $35
- Pedicure: $45
- Facial: $80
- Full Makeover: $200

HOURS:
- Tuesday to Saturday: 9:00 AM - 7:00 PM
- Sunday & Monday: CLOSED

POLICIES:
- Appointments recommended
- Walk-ins accepted if availability
- 24-hour cancellation policy
- 10% discount for first-time customers

STAFF:
- Bella (Owner & Senior Stylist)
- Maria (Hair Specialist)
- Lisa (Nail Technician)
- Sarah (Makeup Artist)

INSTRUCTIONS:
- Be friendly and professional
- If you can answer from the above information, provide the answer
- If asked something you don't know, say: "Let me check with my supervisor and get back to you."
- You can book appointments for services within business hours
- Always confirm customer's phone number for follow-ups
"""

class AssistantFunction(llm.FunctionContext):
    """Custom functions the assistant can call"""
    
    @llm.ai_callable(
        description="Check if the assistant knows the answer to a question"
    )
    async def check_knowledge_base(
        self,
        question: Annotated[str, llm.TypeInfo(description="The question to check")]
    ):
        """Check if we have an answer in our knowledge base"""
        logger.info(f"Checking knowledge base for: {question}")
        answer = db.search_knowledge_base(question)
        
        if answer:
            return f"Found answer: {answer['answer']}"
        else:
            return "No answer found in knowledge base"
    
    @llm.ai_callable(
        description="Escalate a question to human supervisor when the answer is unknown"
    )
    async def escalate_to_supervisor(
        self,
        customer_phone: Annotated[str, llm.TypeInfo(description="Customer's phone number")],
        question: Annotated[str, llm.TypeInfo(description="The question to escalate")]
    ):
        """Escalate to human supervisor"""
        logger.info(f"Escalating question from {customer_phone}: {question}")
        
        # Create help request in database
        request_id = db.create_help_request(
            customer_phone=customer_phone,
            question=question,
            context={"source": "voice_call", "agent": "salon_ai"}
        )
        
        # Log notification (simulating text to supervisor)
        logger.info(f"📱 SMS to Supervisor: 'New help request #{request_id}: {question}'")
        
        return f"I've notified my supervisor about your question. Request ID: {request_id}. They will get back to you shortly."

async def entrypoint(ctx: JobContext):
    """Main entry point for the LiveKit agent"""
    
    # Initialize the AI model
    initial_ctx = llm.ChatContext().append(
        role="system",
        text=SALON_CONTEXT
    )
    
    logger.info("Connecting to LiveKit room...")
    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)
    
    # Wait for the first participant
    participant = await ctx.wait_for_participant()
    logger.info(f"Participant joined: {participant.identity}")
    
    # Create conversation record
    conversation_id = db.create_conversation(participant.identity)
    
    # Set up the voice assistant
    assistant = VoiceAssistant(
        vad=silero.VAD.load(),
        stt=openai.STT(),
        llm=openai.LLM(),
        tts=openai.TTS(),
        fnc_ctx=AssistantFunction(),
        initial_ctx=initial_ctx,
    )
    
    # Start the assistant for this participant
    assistant.start(ctx.room, participant)
    
    # Log conversation updates
    @assistant.on("user_speech_committed")
    def on_user_speech(text: str):
        logger.info(f"User: {text}")
        db.update_conversation(conversation_id, {
            "role": "user",
            "text": text,
            "timestamp": str(datetime.now())
        })
    
    @assistant.on("agent_speech_committed")
    def on_agent_speech(text: str):
        logger.info(f"Agent: {text}")
        db.update_conversation(conversation_id, {
            "role": "agent", 
            "text": text,
            "timestamp": str(datetime.now())
        })
    
    # Keep the agent running
    await asyncio.sleep(3600)  # Run for 1 hour max per session

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            api_key=os.getenv("LIVEKIT_API_KEY"),
            api_secret=os.getenv("LIVEKIT_API_SECRET"),
            ws_url=os.getenv("LIVEKIT_URL"),
        )
    )