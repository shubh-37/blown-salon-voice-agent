import os
from typing import List, Optional
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

from models.firebase_models import (
    HelpRequest,
    KnowledgeBaseEntry,
    Conversation,
    ConversationMessage,
    RequestStats,
    RequestStatus,
    Collections,
)

load_dotenv()


class FirebaseDB:
    def __init__(self):
        if not firebase_admin._apps:
            cred_dict = {
                "type": "service_account",
                "project_id": os.getenv("FIREBASE_PROJECT_ID"),
                "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
                "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
                "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
                "client_id": os.getenv("FIREBASE_CLIENT_ID"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{os.getenv('FIREBASE_CLIENT_EMAIL')}",
            }
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)

        self.db = firestore.client()

    def create_help_request(
        self, customer_phone: str, question: str, context: dict = None
    ) -> str:
        help_request = HelpRequest(
            customer_phone=customer_phone, question=question, context=context or {}
        )

        doc_ref = self.db.collection(Collections.HELP_REQUESTS).document()
        help_request.id = doc_ref.id

        doc_ref.set(help_request.to_dict())
        print(f"Created help request: {doc_ref.id}")

        return doc_ref.id

    def get_pending_requests(self) -> List[dict]:
        requests = (
            self.db.collection(Collections.HELP_REQUESTS)
            .where("status", "==", RequestStatus.PENDING.value)
            .stream()
        )
        request_list = []
        for doc in requests:
            data = doc.to_dict()
            try:
                help_request = HelpRequest.from_dict(data)
                request_list.append(help_request.dict())
            except Exception as e:
                print(f"Error parsing request {doc.id}: {e}")
                request_list.append(data)
        request_list.sort(key=lambda x: x.get("created_at", datetime.min), reverse=True)

        return request_list

    def resolve_request(
        self, request_id: str, response: str, supervisor_id: str = "admin"
    ) -> bool:
        try:
            doc_ref = self.db.collection(Collections.HELP_REQUESTS).document(request_id)

            doc = doc_ref.get()
            if not doc.exists:
                print(f"Request {request_id} not found")
                return False

            update_data = {
                "status": RequestStatus.RESOLVED.value,
                "supervisor_response": response,
                "resolved_at": datetime.now(),
                "assigned_to": supervisor_id,
            }
            doc_ref.update(update_data)

            request_data = doc.to_dict()
            question = request_data.get("question")

            if question:
                self.add_to_knowledge_base(question, response, request_id)

            print(f"Resolved request: {request_id}")
            return True

        except Exception as e:
            print(f"Error resolving request: {e}")
            return False

    def timeout_request(self, request_id: str) -> bool:
        try:
            doc_ref = self.db.collection(Collections.HELP_REQUESTS).document(request_id)

            update_data = {
                "status": RequestStatus.TIMEOUT.value,
                "resolved_at": datetime.now(),
            }
            doc_ref.update(update_data)

            print(f"Marked request as timeout: {request_id}")
            return True

        except Exception as e:
            print(f"Error timing out request: {e}")
            return False

    def get_all_requests(self) -> List[dict]:
        requests = self.db.collection(Collections.HELP_REQUESTS).stream()

        request_list = []
        for doc in requests:
            data = doc.to_dict()
            try:
                help_request = HelpRequest.from_dict(data)
                request_list.append(help_request.dict())
            except Exception as e:
                print(f"Error parsing request {doc.id}: {e}")
                request_list.append(data)

        request_list.sort(key=lambda x: x.get("created_at", datetime.min), reverse=True)

        return request_list

    def get_request_stats(self) -> dict:
        all_requests = self.db.collection(Collections.HELP_REQUESTS).stream()

        stats = RequestStats()
        resolution_times = []

        for doc in all_requests:
            data = doc.to_dict()
            try:
                request = HelpRequest.from_dict(data)

                stats.total += 1

                if request.status == RequestStatus.PENDING:
                    stats.pending += 1
                elif request.status == RequestStatus.RESOLVED:
                    stats.resolved += 1
                elif request.status == RequestStatus.TIMEOUT:
                    stats.timeout += 1

                if request.status == RequestStatus.RESOLVED and request.resolved_at:
                    time_diff = (
                        request.resolved_at - request.created_at
                    ).total_seconds() / 60
                    resolution_times.append(time_diff)

            except Exception as e:
                print(f"Error processing request for stats: {e}")

        if resolution_times:
            stats.avg_resolution_time = sum(resolution_times) / len(resolution_times)

        return stats.dict()

    def add_to_knowledge_base(
        self, question: str, answer: str, source_request_id: str = None
    ) -> str:
        kb_entry = KnowledgeBaseEntry(
            question=question, answer=answer, created_from_request=source_request_id
        )

        doc_ref = self.db.collection(Collections.KNOWLEDGE_BASE).document()
        kb_entry.id = doc_ref.id

        doc_ref.set(kb_entry.to_dict())
        print(f"Added to knowledge base: {doc_ref.id}")

        return doc_ref.id

    def search_knowledge_base(self, question: str) -> Optional[dict]:
        kb_items = self.db.collection(Collections.KNOWLEDGE_BASE).stream()

        for doc in kb_items:
            data = doc.to_dict()
            try:
                kb_entry = KnowledgeBaseEntry.from_dict(data)

                if (
                    question.lower() in kb_entry.question.lower()
                    or kb_entry.question.lower() in question.lower()
                ):
                    self.db.collection(Collections.KNOWLEDGE_BASE).document(
                        doc.id
                    ).update({"usage_count": firestore.Increment(1)})

                    return kb_entry.dict()

            except Exception as e:
                print(f"Error parsing KB entry {doc.id}: {e}")

        return None

    def get_all_knowledge_base(self) -> List[dict]:
        kb_items = self.db.collection(Collections.KNOWLEDGE_BASE).stream()

        kb_list = []
        for doc in kb_items:
            data = doc.to_dict()
            try:
                kb_entry = KnowledgeBaseEntry.from_dict(data)
                kb_list.append(kb_entry.dict())
            except Exception as e:
                print(f"Error parsing KB entry {doc.id}: {e}")
                kb_list.append(data)

        kb_list.sort(key=lambda x: x.get("created_at", datetime.min), reverse=True)

        return kb_list

    def create_conversation(self, customer_phone: str) -> str:
        conversation = Conversation(customer_phone=customer_phone)

        doc_ref = self.db.collection(Collections.CONVERSATIONS).document()
        conversation.id = doc_ref.id

        doc_ref.set(conversation.to_dict())
        print(f"Created conversation: {doc_ref.id}")

        return doc_ref.id

    def update_conversation(self, conversation_id: str, message: dict) -> bool:
        try:
            msg = ConversationMessage(**message)

            doc_ref = self.db.collection(Collections.CONVERSATIONS).document(
                conversation_id
            )
            doc_ref.update({"transcript": firestore.ArrayUnion([msg.to_dict()])})

            return True

        except Exception as e:
            print(f"Error updating conversation: {e}")
            return False

    def mark_conversation_escalated(self, conversation_id: str) -> bool:
        try:
            doc_ref = self.db.collection(Collections.CONVERSATIONS).document(
                conversation_id
            )
            doc_ref.update({"escalated": True})

            print(f"Marked conversation as escalated: {conversation_id}")
            return True

        except Exception as e:
            print(f"Error marking conversation as escalated: {e}")
            return False
