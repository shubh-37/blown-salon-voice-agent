import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './App.css';

const API_URL = 'http://localhost:8000';
const WS_URL = 'ws://localhost:8000/ws';

function App() {
  const [activeTab, setActiveTab] = useState('pending');
  const [pendingRequests, setPendingRequests] = useState([]);
  const [knowledgeBase, setKnowledgeBase] = useState([]);
  const [stats, setStats] = useState({});
  const [selectedRequest, setSelectedRequest] = useState(null);
  const [response, setResponse] = useState('');
  const [loading, setLoading] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState('disconnected');

  const ws = useRef(null);
  const reconnectTimeout = useRef(null);

  const connectWebSocket = () => {
    try {
      setConnectionStatus('connecting');

      ws.current = new WebSocket(WS_URL);

      ws.current.onopen = () => {
        setConnectionStatus('connected');
        if (reconnectTimeout.current) {
          clearTimeout(reconnectTimeout.current);
          reconnectTimeout.current = null;
        }
      };

      ws.current.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          handleWebSocketMessage(message);
        } catch (error) {
          console.error('Error parsing WebSocket message:', error);
        }
      };

      ws.current.onerror = (error) => {
        setConnectionStatus('error');
      };

      ws.current.onclose = () => {
        setConnectionStatus('disconnected');

        reconnectTimeout.current = setTimeout(() => {
          connectWebSocket();
        }, 3000);
      };
    } catch (error) {
      console.error('Failed to create WebSocket:', error);
      setConnectionStatus('error');
    }
  };

  const handleWebSocketMessage = (message) => {
    switch (message.type) {
      case 'connected':
        break;

      case 'new_request':
        setPendingRequests((prev) => [message.data, ...prev]);
        showNotification(`New request: ${message.data.question}`);
        playNotificationSound();
        break;

      case 'request_resolved':
        setPendingRequests((prev) => prev.filter((req) => req.id !== message.data.request_id));
        showNotification('Request resolved and added to knowledge base!');
        break;

      case 'request_timeout':
        setPendingRequests((prev) => prev.filter((req) => req.id !== message.data.request_id));
        break;

      case 'stats_update':
        setStats(message.data);
        break;

      case 'pending_requests':
        setPendingRequests(message.data);
        break;

      case 'knowledge_base_updated':
        fetchKnowledgeBase();
        showNotification('Knowledge base updated! Agent can now answer this question.');
        break;

      case 'ping':
        if (ws.current?.readyState === WebSocket.OPEN) {
          ws.current.send('pong');
        }
        break;

      default:
    }
  };
  const showNotification = (message) => {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification('Blown Salons Admin Dashboard', {
        body: message,
        icon: '/blown.ico'
      });
    } else {
      alert(message);
    }
  };

  const playNotificationSound = () => {
    try {
      const audio = new Audio('/notification.mp3');
      audio.play().catch((err) => alert('Could not play sound:', err));
    } catch (error) {
      alert('Sound file not found');
    }
  };

  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  }, []);

  const fetchKnowledgeBase = async () => {
    try {
      const res = await axios.get(`${API_URL}/api/knowledge-base`);
      setKnowledgeBase(res.data.entries);
    } catch (error) {
      console.error('Error fetching knowledge base:', error);
    }
  };

  const submitResponse = async (requestId) => {
    if (!response.trim()) {
      alert('Please enter a response');
      return;
    }

    setLoading(true);
    try {
      await axios.post(`${API_URL}/api/help-requests/resolve`, {
        request_id: requestId,
        response: response,
        supervisor_id: 'admin'
      });

      alert('Response submitted! Agent can now answer this question.');
      setResponse('');
      setSelectedRequest(null);
    } catch (error) {
      console.error('Error submitting response:', error);
      alert('Failed to submit response');
    }
    setLoading(false);
  };

  const formatDate = (dateString) => {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleString();
  };

  useEffect(() => {
    connectWebSocket();
    fetchKnowledgeBase();

    return () => {
      if (ws.current) {
        ws.current.close();
      }
      if (reconnectTimeout.current) {
        clearTimeout(reconnectTimeout.current);
      }
    };
  }, []);

  return (
    <div className="App">
      <header className="App-header">
        <div className="header-content">
          <div>
            <h1>Blown Salons Admin Dashboard</h1>
          </div>
        </div>

        <div className="stats-bar">
          <div className="stat">
            <span className="stat-label">Total Requests:</span>
            <span className="stat-value">{stats.total || 0}</span>
          </div>
          <div className="stat">
            <span className="stat-label">Pending:</span>
            <span className="stat-value pending">{stats.pending || 0}</span>
          </div>
          <div className="stat">
            <span className="stat-label">Resolved:</span>
            <span className="stat-value resolved">{stats.resolved || 0}</span>
          </div>
          <div className="stat">
            <span className="stat-label">Avg Resolution:</span>
            <span className="stat-value">{Math.round(stats.avg_resolution_time || 0)} min</span>
          </div>
        </div>
      </header>

      <div className="tab-navigation">
        <button className={activeTab === 'pending' ? 'active' : ''} onClick={() => setActiveTab('pending')}>
          Pending Requests ({pendingRequests.length})
        </button>
        <button className={activeTab === 'knowledge' ? 'active' : ''} onClick={() => setActiveTab('knowledge')}>
          Knowledge Base ({knowledgeBase.length})
        </button>
      </div>

      <div className="content">
        {activeTab === 'pending' && (
          <div className="pending-section">
            <h2 className="section-title">Pending Help Requests</h2>

            {pendingRequests.length === 0 ? (
              <div className="no-data">
                <p>No pending requests at the moment!</p>
                <p className="subtext">New requests will appear here instantly.</p>
              </div>
            ) : (
              <div className="requests-grid">
                {pendingRequests.map((request) => (
                  <div key={request.id} className="request-card">
                    <div className="request-header">
                      <span className="request-id">#{request.id?.slice(-6)}</span>
                      <span className="request-time">{formatDate(request.created_at)}</span>
                    </div>

                    <div className="request-body">
                      <div className="request-field">
                        <strong>Customer:</strong> {request.customer_phone}
                      </div>
                      <div className="request-field">
                        <strong>Question:</strong>
                        <p className="question-text">{request.question}</p>
                      </div>
                    </div>

                    {selectedRequest === request.id ? (
                      <div className="response-form">
                        <textarea
                          placeholder="Type your response here... This will be added to the knowledge base automatically."
                          value={response}
                          onChange={(e) => setResponse(e.target.value)}
                          rows="4"
                        />
                        <div className="form-actions">
                          <button onClick={() => submitResponse(request.id)} disabled={loading} className="submit-btn">
                            {loading ? 'Sending...' : 'Send Response'}
                          </button>
                          <button
                            onClick={() => {
                              setSelectedRequest(null);
                              setResponse('');
                            }}
                            className="cancel-btn"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <button onClick={() => setSelectedRequest(request.id)} className="respond-btn">
                        Respond
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'knowledge' && (
          <div className="knowledge-section">
            <h2 className="section-title">Knowledge Base</h2>
            <p className="section-subtitle">Answers learned from admin responses. Agent uses this in real-time.</p>

            {knowledgeBase.length === 0 ? (
              <div className="no-data">
                <p>Knowledge base is empty.</p>
                <p className="subtext">It will populate automatically as you resolve requests!</p>
              </div>
            ) : (
              <div className="knowledge-grid">
                {knowledgeBase.map((entry) => (
                  <div key={entry.id} className="knowledge-card">
                    <div className="kb-header">
                      <span className="kb-category">{entry.category}</span>
                      <span className="kb-usage">Used {entry.usage_count || 0} times</span>
                    </div>
                    <div className="kb-question">
                      <strong>Q:</strong> {entry.question}
                    </div>
                    <div className="kb-answer">
                      <strong>A:</strong> {entry.answer}
                    </div>
                    <div className="kb-footer">Added: {formatDate(entry.created_at)}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
