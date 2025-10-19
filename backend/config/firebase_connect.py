import os
import json
from datetime import datetime
from typing import Dict, List, Optional
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

load_dotenv()

class FirebaseDB:
    def __init__(self):
        # Initialize Firebase
        if not firebase_admin._apps:
            # Create credentials from environment variables
            cred_dict = {
                "type": "service_account",
                "project_id": os.getenv("FIREBASE_PROJECT_ID"),
                "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
                "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace('\\n', '\n'),
                "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
                "client_id": os.getenv("FIREBASE_CLIENT_ID"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{os.getenv('FIREBASE_CLIENT_EMAIL')}"
            }
            
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        
        self.db = firestore.client()
        
    # Help Requests Methods
    def create_help_request(self, customer_phone: str, question: str, context: Dict = None) -> str:
        """Create a new help request"""
        doc_ref = self.db.collection('help_requests').document()
        doc_ref.set({
            'id': doc_ref.id,
            'customer_phone': customer_phone,
            'question': question,
            'context': context or {},
            'status': 'pending',
            'created_at': datetime.now(),
            'resolved_at': None,
            'supervisor_response': None,
            'assigned_to': None
        })
        print(f"Created help request: {doc_ref.id}")
        return doc_ref.id
    
    def get_pending_requests(self) -> List[Dict]:
        """Get all pending help requests"""
        requests = self.db.collection('help_requests')\
            .where('status', '==', 'pending')\
            .order_by('created_at', direction=firestore.Query.DESCENDING)\
            .stream()
        return [doc.to_dict() for doc in requests]
    
    def resolve_request(self, request_id: str, response: str, supervisor_id: str = "admin") -> bool:
        """Resolve a help request with supervisor's response"""
        try:
            doc_ref = self.db.collection('help_requests').document(request_id)
            doc_ref.update({
                'status': 'resolved',
                'supervisor_response': response,
                'resolved_at': datetime.now(),
                'assigned_to': supervisor_id
            })
            
            # Get the request details to add to knowledge base
            request = doc_ref.get().to_dict()
            
            # Add to knowledge base
            self.add_to_knowledge_base(request['question'], response, request_id)
            
            return True
        except Exception as e:
            print(f"Error resolving request: {e}")
            return False
    
    def timeout_request(self, request_id: str) -> bool:
        """Mark request as timed out"""
        try:
            doc_ref = self.db.collection('help_requests').document(request_id)
            doc_ref.update({
                'status': 'timeout',
                'resolved_at': datetime.now()
            })
            return True
        except Exception as e:
            print(f"Error timing out request: {e}")
            return False
    
    # Knowledge Base Methods
    def add_to_knowledge_base(self, question: str, answer: str, source_request_id: str = None) -> str:
        """Add a Q&A pair to knowledge base"""
        doc_ref = self.db.collection('knowledge_base').document()
        doc_ref.set({
            'id': doc_ref.id,
            'question': question,
            'answer': answer,
            'category': 'general',  # You can enhance this with categorization
            'created_from_request': source_request_id,
            'usage_count': 0,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        })
        print(f"Added to knowledge base: {doc_ref.id}")
        return doc_ref.id
    
    def search_knowledge_base(self, question: str) -> Optional[Dict]:
        """Search knowledge base for similar questions"""
        # Simple exact match for now - you can enhance with similarity matching
        kb_items = self.db.collection('knowledge_base').stream()
        
        for item in kb_items:
            item_data = item.to_dict()
            # Simple case-insensitive contains check
            if question.lower() in item_data['question'].lower() or \
               item_data['question'].lower() in question.lower():
                # Increment usage count
                self.db.collection('knowledge_base').document(item.id).update({
                    'usage_count': firestore.Increment(1)
                })
                return item_data
        
        return None
    
    def get_all_knowledge_base(self) -> List[Dict]:
        """Get all knowledge base entries"""
        kb_items = self.db.collection('knowledge_base')\
            .order_by('created_at', direction=firestore.Query.DESCENDING)\
            .stream()
        return [doc.to_dict() for doc in kb_items]
    
    # Conversation Methods
    def create_conversation(self, customer_phone: str) -> str:
        """Create a new conversation record"""
        doc_ref = self.db.collection('conversations').document()
        doc_ref.set({
            'id': doc_ref.id,
            'customer_phone': customer_phone,
            'transcript': [],
            'escalated': False,
            'resolved': False,
            'created_at': datetime.now()
        })
        return doc_ref.id
    
    def update_conversation(self, conversation_id: str, message: Dict) -> bool:
        """Add message to conversation transcript"""
        try:
            doc_ref = self.db.collection('conversations').document(conversation_id)
            doc_ref.update({
                'transcript': firestore.ArrayUnion([message])
            })
            return True
        except Exception as e:
            print(f"Error updating conversation: {e}")
            return False
    
    def mark_conversation_escalated(self, conversation_id: str) -> bool:
        """Mark conversation as escalated"""
        try:
            doc_ref = self.db.collection('conversations').document(conversation_id)
            doc_ref.update({'escalated': True})
            return True
        except Exception as e:
            print(f"Error marking conversation as escalated: {e}")
            return False
    
    # Analytics Methods
    def get_request_stats(self) -> Dict:
        """Get statistics about help requests"""
        all_requests = self.db.collection('help_requests').stream()
        
        stats = {
            'total': 0,
            'pending': 0,
            'resolved': 0,
            'timeout': 0,
            'avg_resolution_time': 0
        }
        
        resolution_times = []
        
        for req in all_requests:
            req_data = req.to_dict()
            stats['total'] += 1
            stats[req_data['status']] += 1
            
            if req_data['status'] == 'resolved' and req_data.get('resolved_at'):
                time_diff = (req_data['resolved_at'] - req_data['created_at']).total_seconds() / 60
                resolution_times.append(time_diff)
        
        if resolution_times:
            stats['avg_resolution_time'] = sum(resolution_times) / len(resolution_times)
        
        return stats