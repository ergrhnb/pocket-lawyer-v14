# ============================================================
# POCKET LAWYER v14.0 - FIXED VERSION
# ============================================================
import os
import json
import logging
import asyncio
import threading
import time
import re
import io
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import httpx
import uvicorn

# ============================================================
# PDF GENERATION
# ============================================================
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# ============================================================
# LOGGING
# ============================================================
os.makedirs('logs', exist_ok=True)
os.makedirs('data', exist_ok=True)
os.makedirs('documents', exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/pocket_lawyer.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("pocket_lawyer")

VERSION = "14.0.0"
APP_NAME = "Pocket Lawyer"

# ============================================================
# CONFIGURATION - FIXED SYNTAX
# ============================================================
class ConfigStore:
    _config = {
        "brand_name": "Pocket Lawyer",
        "brand_color": "#1a56db",
        "currency": "NGN",
        "firm_name": "Pocket Law Firm",
        "firm_address": "Lagos, Nigeria",
        "firm_phone": "+234 800 000 0000",
        "firm_email": "info@pocketlawyer.ai",
        "system_prompt": "You are Pocket Lawyer, an expert AI legal assistant for Nigerian Law.",
        "ai_providers": [
            {"name": "Groq", "enabled": True, "priority": 1,
             "api_key": os.getenv("GROQ_API_KEY", ""),
             "model": "llama-3.3-70b-versatile",
             "base_url": "https://api.groq.com/openai/v1"},
            {"name": "SambaNova", "enabled": True, "priority": 2,
             "api_key": os.getenv("SAMBANOVA_API_KEY", ""),
             "model": "Meta-Llama-3.3-70B-Instruct",
             "base_url": "https://api.sambanova.ai/v1"},
            {"name": "Mistral", "enabled": True, "priority": 3,
             "api_key": os.getenv("MISTRAL_API_KEY", ""),
             "model": "mistral-large-latest",
             "base_url": "https://api.mistral.ai/v1"},
            {"name": "OpenRouter", "enabled": True, "priority": 4,
             "api_key": os.getenv("OPENROUTER_API_KEY", ""),
             "model": "mistralai/mistral-large",
             "base_url": "https://openrouter.ai/api/v1"}
        ],
        "openrouter_models": ["mistralai/mistral-large", "mistralai/mistral-small",
                             "deepseek/deepseek-chat", "meta-llama/llama-3.3-70b-instruct"],
        "telegram": {"enabled": True,
                     "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
                     "bot_username": "Mypocket_lawyerbot",
                     "last_offset": 0},
        "whatsapp": {"enabled": False, "phone_number_id": "", "access_token": "",
                     "verify_token": "pocket_lawyer_2024"},
        "plans": [
            {"name": "Free", "slug": "free", "price_monthly": 0,
             "features": ["AI Chat"], "limits": {"requests": 100}},
            {"name": "Pro", "slug": "pro", "price_monthly": 5000,
             "features": ["AI Chat", "PDF Export"], "limits": {"requests": 1000}},
            {"name": "Enterprise", "slug": "enterprise", "price_monthly": 15000,
             "features": ["AI Chat", "PDF Export", "Team"], "limits": {"requests": 10000}}
        ]
    }

    @classmethod
    def get_all(cls):
        return cls._config

    @classmethod
    def get(cls, key, default=None):
        return cls._config.get(key, default)

    @classmethod
    def set(cls, key, value):
        cls._config[key] = value
        return True

    @classmethod
    def get_ai_providers(cls):
        return cls._config.get("ai_providers", [])

    @classmethod
    def get_plans(cls):
        return cls._config.get("plans", [])

    @classmethod
    def get_telegram(cls):
        return cls._config.get("telegram", {})

    @classmethod
    def get_whatsapp(cls):
        return cls._config.get("whatsapp", {})

    @classmethod
    def get_openrouter_models(cls):
        return cls._config.get("openrouter_models", [])

# ============================================================
# PROVIDER ROTATOR
# ============================================================
class ProviderRotator:
    _provider_stats = {}
    _model_index = 0
    _lock = threading.Lock()

    @classmethod
    def get_ordered_providers(cls, providers):
        with cls._lock:
            enabled = [p for p in providers if p.get("enabled", True)]
            for p in enabled:
                name = p.get("name")
                stats = cls._provider_stats.get(name, {})
                success_rate = stats.get("success", 0) / max(1, stats.get("total", 0))
                avg_time = stats.get("avg_time", 1)
                p["_performance"] = (1 - p.get("priority", 999) / 100) * 0.5 + success_rate * 0.3 + max(0, (1 - avg_time / 5)) * 0.2
            return sorted(enabled, key=lambda x: x.get("_performance", 0), reverse=True)

    @classmethod
    def get_next_openrouter_model(cls):
        with cls._lock:
            models = ConfigStore.get_openrouter_models()
            if not models:
                return "mistralai/mistral-large"
            model = models[cls._model_index % len(models)]
            cls._model_index += 1
            return model

    @classmethod
    def record_success(cls, name, response_time):
        with cls._lock:
            if name not in cls._provider_stats:
                cls._provider_stats[name] = {"success": 0, "errors": 0, "total": 0, "avg_time": 0}
            stats = cls._provider_stats[name]
            stats["success"] += 1
            stats["total"] += 1
            stats["avg_time"] = stats["avg_time"] * 0.7 + response_time * 0.3

    @classmethod
    def record_error(cls, name):
        with cls._lock:
            if name not in cls._provider_stats:
                cls._provider_stats[name] = {"success": 0, "errors": 0, "total": 0, "avg_time": 0}
            stats = cls._provider_stats[name]
            stats["errors"] += 1
            stats["total"] += 1

    @classmethod
    def get_stats(cls):
        with cls._lock:
            return cls._provider_stats.copy()

app = FastAPI(title=APP_NAME, version=VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True)

# ============================================================
# MODELS
# ============================================================
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)

class ConfigUpdateRequest(BaseModel):
    configs: Dict[str, Any]

# ============================================================
# GREETINGS
# ============================================================
GREETINGS = {"hi", "hello", "hey", "greetings", "good morning", "good afternoon",
             "good evening", "sup", "hiya", "howdy", "yo", "how are you"}

def is_greeting(text):
    if not text or len(text) > 50:
        return False
    cleaned = re.sub(r'[^\w\s]', '', text).strip().lower()
    return cleaned in GREETINGS

def get_greeting_response(brand):
    return f"""Welcome to {brand} - Your Nigerian Law AI Assistant

I can help with:
• Generate PDF documents
• Create contracts and agreements
• Answer legal questions

Try asking:
• "Generate a tenancy agreement PDF"
• "Create an NDA contract"

Disclaimer: I provide general guidance only. For specific legal advice, please consult a qualified lawyer."""

# ============================================================
# AI FUNCTIONS
# ============================================================
async def call_provider(base_url, api_key, model, messages):
    try:
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        system_prompt = ConfigStore.get("system_prompt", "You are Pocket Lawyer.")
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        payload = {"model": model, "messages": full_messages, "temperature": 0.2, "max_tokens": 1500}
        async with httpx.AsyncClient(timeout=30.0) as client:
            start = time.time()
            resp = await client.post(url, json=payload, headers=headers)
            elapsed = time.time() - start
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                if content:
                    return content, elapsed
            return None, None
    except Exception as e:
        logger.error(f"Provider error: {e}")
        return None, None

async def get_ai_response(message):
    messages = [{"role": "user", "content": message}]
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")
    providers = ProviderRotator.get_ordered_providers(ConfigStore.get_ai_providers())
    for provider in providers:
        name = provider.get("name")
        base_url = provider.get("base_url")
        api_key = provider.get("api_key")
        model = provider.get("model")
        if not base_url or not api_key or not model:
            continue
        try:
            reply, elapsed = await call_provider(base_url, api_key, model, messages)
            if reply:
                ProviderRotator.record_success(name, elapsed)
                return {"reply": reply, "provider": name}
            ProviderRotator.record_error(name)
        except Exception as e:
            logger.error(f"{name} error: {e}")
            ProviderRotator.record_error(name)
        await asyncio.sleep(0.05)
    return {"reply": "I'm having trouble connecting. Please try again later.", "provider": "offline"}

# ============================================================
# PDF GENERATOR
# ============================================================
class PDFGenerator:
    @staticmethod
    def generate_document(title, content, author="Pocket Lawyer"):
        if not PDF_AVAILABLE:
            raise Exception("PDF generation not available")

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=72, rightMargin=72,
                                topMargin=72, bottomMargin=72, title=title, author=author)

        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(
            name='CustomTitle', parent=styles['Heading1'], alignment=TA_CENTER,
            fontSize=20, textColor=colors.HexColor('#1a56db'), spaceAfter=30
        ))
        styles.add(ParagraphStyle(
            name='CustomBody', parent=styles['Normal'], fontSize=11,
            alignment=TA_JUSTIFY, spaceAfter=10, leading=16
        ))

        story = []
        story.append(Paragraph(f"{ConfigStore.get('brand_name', 'Pocket Lawyer')}", styles['CustomTitle']))
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph(title, styles['CustomTitle']))
        story.append(Spacer(1, 0.1 * inch))
        story.append(Paragraph(f"Date: {datetime.now().strftime('%B %d, %Y')}", styles['CustomBody']))
        story.append(Spacer(1, 0.2 * inch))

        for line in content.split('\n'):
            line = line.strip()
            if not line:
                story.append(Spacer(1, 0.05 * inch))
            else:
                story.append(Paragraph(line, styles['CustomBody']))

        story.append(PageBreak())
        story.append(Paragraph("DISCLAIMER", styles['CustomTitle']))
        story.append(Paragraph(
            "This document is generated by Pocket Lawyer AI. Information is for general purposes only.",
            styles['CustomBody']
        ))

        doc.build(story)
        buffer.seek(0)
        return buffer

# ============================================================
# DOCUMENT STORAGE
# ============================================================
documents = {}

async def generate_document_from_chat(message):
    if not PDF_AVAILABLE:
        return {"status": "error", "message": "PDF generation not available"}

    title = "Legal Document"
    content = f"""# LEGAL DOCUMENT

Generated based on: {message}

## INTRODUCTION

This document is created based on the request provided.

## TERMS AND CONDITIONS

1. Term 1
2. Term 2
3. Term 3

## GOVERNING LAW

Federal Republic of Nigeria.

## SIGNATURES

_________________________  Date: _________

---
Disclaimer: This is a template. Review by a qualified lawyer is recommended."""

    if "tenancy" in message.lower() or "rent" in message.lower():
        title = "Tenancy Agreement"
        content = """# TENANCY AGREEMENT

## PARTIES
**Landlord:** _________________________
**Tenant:** _________________________
**Property Address:** _________________________

## TERMS

### 1. TERM
This agreement shall commence on ___ and continue for ___ months.

### 2. RENT
The tenant shall pay ________ per month.

### 3. GOVERNING LAW
Federal Republic of Nigeria.

## SIGNATURES
**Landlord:** ___________________  Date: _________
**Tenant:** ___________________  Date: _________

---
Disclaimer: This is a template. Review by a qualified lawyer is recommended."""

    doc_id = f"doc_{int(time.time())}_{hashlib.md5(title.encode()).hexdigest()[:6]}"

    try:
        pdf_buffer = PDFGenerator.generate_document(title, content)
        documents[doc_id] = {
            "title": title,
            "content": content,
            "pdf": pdf_buffer,
            "created_at": datetime.utcnow().isoformat()
        }

        return {
            "status": "success",
            "title": title,
            "content": content,
            "document_id": doc_id,
            "pdf_url": f"/api/documents/{doc_id}/download"
        }
    except Exception as e:
        logger.error(f"PDF generation error: {e}")
        return {"status": "error", "message": str(e)}

# ============================================================
# API ENDPOINTS
# ============================================================
@app.get("/api/config")
async def get_config():
    return ConfigStore.get_all()

@app.post("/api/config/batch")
async def update_config(data: ConfigUpdateRequest):
    for key, value in data.configs.items():
        ConfigStore.set(key, value)
    return {"status": "success"}

@app.post("/api/chat")
async def chat(request: Request, chat_req: ChatRequest):
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")

    if is_greeting(chat_req.message):
        return {"reply": get_greeting_response(brand), "provider": brand}

    pdf_keywords = ["generate pdf", "create pdf", "make pdf", "tenancy agreement", "nda"]
    if any(word in chat_req.message.lower() for word in pdf_keywords):
        result = await generate_document_from_chat(chat_req.message)
        if result.get("status") == "success":
            return {
                "reply": f"Document generated: {result.get('title')}",
                "provider": brand,
                "pdf_url": result.get("pdf_url"),
                "document_id": result.get("document_id")
            }

    result = await get_ai_response(chat_req.message)
    return {"reply": result["reply"], "provider": result.get("provider", brand)}

@app.get("/api/documents/{doc_id}/download")
async def download_document(doc_id: str):
    doc = documents.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    pdf_buffer = doc.get("pdf")
    if not pdf_buffer:
        raise HTTPException(status_code=404, detail="PDF not found")
    pdf_buffer.seek(0)
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={doc['title']}.pdf"}
    )

@app.get("/api/documents")
async def list_documents():
    return {
        "status": "success",
        "documents": [
            {"id": doc_id, "title": doc["title"], "created_at": doc["created_at"]}
            for doc_id, doc in documents.items()
        ]
    }

@app.get("/api/provider/stats")
async def get_provider_stats():
    return ProviderRotator.get_stats()

@app.get("/api/plans")
async def get_plans():
    return {"plans": ConfigStore.get_plans()}

@app.get("/api/health")
async def health():
    return {
        "status": "healthy",
        "version": VERSION,
        "pdf_available": PDF_AVAILABLE,
        "documents": len(documents)
    }

# ============================================================
# UI PAGES
# ============================================================
@app.get("/", response_class=HTMLResponse)
async def home():
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")
    return f"""
<!DOCTYPE html>
<html>
<head><title>{brand}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; background: #0f172a; color: #e2e8f0; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
h1 {{ color: #60a5fa; font-size: 3.5rem; }}
.btn {{ background: #3b82f6; color: white; padding: 14px 36px; border-radius: 12px; text-decoration: none; font-weight: 600; margin: 8px; display: inline-block; transition: all 0.3s; }}
.btn:hover {{ background: #2563eb; transform: translateY(-2px); }}
.btn-secondary {{ background: #1e293b; }}
.btn-secondary:hover {{ background: #334155; }}
.version {{ color: #64748b; font-size: 0.8rem; margin-top: 2rem; }}
</style>
</head>
<body>
<h1> {brand}</h1>
<p style="color: #94a3b8; font-size: 1.2rem;">AI Legal Assistant for Nigerian Law</p>
<div style="margin-top: 2rem;">
<a href="/chat" class="btn">Chat</a>
<a href="/admin" class="btn btn-secondary">Admin</a>
</div>
<div class="version">v{VERSION} • PDF Generation Available</div>
</body>
</html>
"""

@app.get("/chat", response_class=HTMLResponse)
async def chat_ui():
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")
    return f"""
<!DOCTYPE html>
<html>
<head><title>{brand} - Chat</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; background: #0f172a; color: #e2e8f0; height: 100vh; overflow: hidden; }}
.header {{ display: flex; justify-content: space-between; align-items: center; padding: 12px 24px; background: #1e293b; border-bottom: 1px solid #334155; }}
.header h2 {{ color: #60a5fa; }}
.btn {{ background: #1e293b; color: #e2e8f0; padding: 6px 16px; border-radius: 8px; text-decoration: none; border: 1px solid #334155; }}
.btn:hover {{ background: #334155; }}
.chat-container {{ max-width: 900px; margin: 0 auto; padding: 20px; height: calc(100vh - 80px); display: flex; flex-direction: column; }}
.chat-box {{ flex:1; overflow-y:auto; padding:20px; background:#0f172a; border:1px solid #1e293b; border-radius:12px; margin-bottom:16px; }}
.message {{ padding: 12px 18px; margin: 8px 0; border-radius: 12px; max-width: 85%; word-wrap: break-word; line-height: 1.6; }}
.user {{ background: #3b82f6; margin-left: auto; }}
.ai {{ background: #1e293b; border: 1px solid #334155; }}
.ai .pdf-link {{ display: inline-block; background: #10b981; color: white; padding: 8px 16px; border-radius: 8px; text-decoration: none; margin-top: 8px; }}
.input-area {{ display: flex; gap: 12px; padding: 16px 0; }}
.input-area input {{ flex:1; padding:12px 18px; border-radius:12px; border:1px solid #334155; background:#1e293b; color:#e2e8f0; font-size:1rem; outline:none; }}
.input-area input:focus {{ border-color:#3b82f6; }}
.input-area button {{ padding:12px 28px; border-radius:12px; border:none; background:#3b82f6; color:white; font-weight:600; cursor:pointer; }}
.input-area button:hover {{ background:#2563eb; }}
.disclaimer {{ font-size:0.7rem; color:#64748b; text-align:center; padding:8px; }}
</style>
</head>
<body>
<div class="header"><h2> {brand}</h2><div><a href="/admin" class="btn">Admin</a><a href="/" class="btn">Home</a></div></div>
<div class="chat-container">
<div id="chatBox" class="chat-box">
<div class="message ai"><strong> {brand}</strong><br>Hello! I am your AI legal assistant for Nigerian Law.<br>Try asking: <strong>"Generate a tenancy agreement PDF"</strong></div>
</div>
<div class="input-area">
<input type="text" id="userInput" placeholder="Type your legal question..." onkeypress="if(event.key===13) sendMessage()">
<button onclick="sendMessage()">Send</button>
</div>
<div class="disclaimer">General guidance only. Consult a lawyer for legal advice.</div>
</div>
<script>
const chatBox=document.getElementById('chatBox');
function addMessage(sender, text, isHTML = false) {{
    const div=document.createElement('div');
    div.className='message '+sender;
    if (isHTML) {{
        div.innerHTML = text;
    }} else {{
        div.textContent = text;
    }}
    chatBox.appendChild(div);
    chatBox.scrollTop=chatBox.scrollHeight;
}}
function addTyping() {{
    const div=document.createElement('div');
    div.className='typing';
    div.id='typing';
    div.textContent='Thinking...';
    chatBox.appendChild(div);
    chatBox.scrollTop=chatBox.scrollHeight;
}}
function removeTyping() {{
    const typing=document.getElementById('typing');
    if(typing) typing.remove();
}}
async function sendMessage() {{
    const input=document.getElementById('userInput');
    const message=input.value.trim();
    if(!message) return;
    input.value='';
    addMessage('user', message);
    addTyping();
    try {{
        const res=await fetch('/api/chat', {{
            method:'POST',
            headers:{{'Content-Type':'application/json'}},
            body:JSON.stringify({{message:message}})
        }});
        const data=await res.json();
        removeTyping();
        if (data.pdf_url) {{
            const pdfLink = `<a href="${{data.pdf_url}}" target="_blank" class="pdf-link">Download PDF</a>`;
            addMessage('ai', data.reply + '<br>' + pdfLink, true);
        }} else {{
            addMessage('ai', data.reply);
        }}
    }} catch(e) {{
        removeTyping();
        addMessage('ai','Error connecting to server.');
    }}
}}
</script>
</body>
</html>
"""

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard():
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")
    providers = ConfigStore.get_ai_providers()
    plans = ConfigStore.get_plans()
    tg = ConfigStore.get_telegram()
    wa = ConfigStore.get_whatsapp()
    stats = ProviderRotator.get_stats()

    return f"""
<!DOCTYPE html>
<html>
<head><title>{brand} - Admin</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; background: #0f172a; color: #e2e8f0; display: flex; min-height: 100vh; }}
.sidebar {{ width: 220px; background: #0f172a; border-right: 1px solid #1e293b; padding: 24px 16px; position: fixed; top:0; left:0; bottom:0; overflow-y:auto; }}
.sidebar h2 {{ color: #60a5fa; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #1e293b; }}
.sidebar a {{ display: block; padding: 10px 14px; color: #94a3b8; text-decoration: none; border-radius: 8px; margin-bottom: 2px; }}
.sidebar a:hover {{ background: #1e293b; color: #e2e8f0; }}
.sidebar a.active {{ background: #1e293b; color: #60a5fa; }}
.main {{ margin-left: 220px; padding: 32px 40px; flex:1; }}
.main h1 {{ font-size: 2rem; margin-bottom: 24px; }}
.stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; margin-bottom: 30px; }}
.stat-card {{ background: #1e293b; padding: 20px; border-radius: 12px; border: 1px solid #334155; text-align: center; }}
.stat-value {{ font-size: 2.2rem; font-weight: bold; color: #60a5fa; }}
.stat-label {{ color: #94a3b8; font-size: 0.85rem; }}
.card {{ background: #1e293b; padding: 24px; border-radius: 12px; border: 1px solid #334155; margin-bottom: 20px; }}
.btn {{ background: #3b82f6; color: white; padding: 8px 20px; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; text-decoration: none; display: inline-block; }}
.btn:hover {{ background: #2563eb; }}
.badge {{ display: inline-block; background: #10b98120; color: #10b981; padding: 4px 12px; border-radius: 20px; font-size: 0.7rem; }}
</style>
</head>
<body>
<div class="sidebar">
<h2> {brand}</h2>
<a href="/admin" class="active">Dashboard</a>
<a href="/admin/ai">AI Providers</a>
<a href="/admin/telegram">Telegram</a>
<a href="/admin/whatsapp">WhatsApp</a>
<a href="/admin/plans">Plans</a>
<a href="/admin/config">Config</a>
<a href="/chat">Chat</a>
<a href="/">Home</a>
</div>
<div class="main">
<h1>Dashboard</h1>
<div class="stats-grid">
<div class="stat-card"><div class="stat-value">{len([p for p in providers if p.get("enabled")])}/{len(providers)}</div><div class="stat-label">Active Providers</div></div>
<div class="stat-card"><div class="stat-value">{len(plans)}</div><div class="stat-label">Plans</div></div>
<div class="stat-card"><div class="stat-value">{"OK" if tg.get("enabled") else "OFF"}</div><div class="stat-label">Telegram</div></div>
<div class="stat-card"><div class="stat-value">{"OK" if wa.get("enabled") else "OFF"}</div><div class="stat-label">WhatsApp</div></div>
<div class="stat-card"><div class="stat-value">{"OK" if PDF_AVAILABLE else "NO"}</div><div class="stat-label">PDF Generation</div></div>
<div class="stat-card"><div class="stat-value">v{VERSION}</div><div class="stat-label">Version</div></div>
</div>
<div class="card"><h3>PDF Generation</h3>
<p>Status: <span class="badge">{"Available" if PDF_AVAILABLE else "Not Available"}</span></p>
</div>
<div class="card"><h3>Quick Actions</h3>
<div style="display:flex;gap:8px;flex-wrap:wrap;">
<a href="/admin/ai" class="btn">Manage AI</a>
<a href="/admin/telegram" class="btn">Telegram</a>
<a href="/admin/config" class="btn">Config</a>
<a href="/chat" class="btn">Chat</a>
</div>
</div>
</div>
</body>
</html>
"""

@app.get("/admin/ai", response_class=HTMLResponse)
async def admin_ai():
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")
    providers = ConfigStore.get_ai_providers()
    html = ""
    for idx, p in enumerate(providers):
        html += f"""
        <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #1e293b;">
            <span><strong>{p.get("name")}</strong> <span style="padding:2px 12px;border-radius:12px;font-size:0.7rem;background:{'#10b98120' if p.get('enabled') else '#ef444420'};color:{'#10b981' if p.get('enabled') else '#ef4444'};border:1px solid {'#10b98140' if p.get('enabled') else '#ef444440'};">{"ON" if p.get("enabled") else "OFF"}</span></span>
            <div><button class="btn btn-primary" onclick="toggleProvider({idx})">Toggle</button> <button class="btn btn-secondary" onclick="testProvider({idx})">Test</button> <span id="test_result_{idx}"></span></div>
        </div>
        """
    return f"""
<!DOCTYPE html>
<html>
<head><title>{brand} - AI Providers</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; background: #0f172a; color: #e2e8f0; display: flex; min-height: 100vh; }}
.sidebar {{ width:220px; background:#0f172a; border-right:1px solid #1e293b; padding:24px 16px; position:fixed; top:0; left:0; bottom:0; overflow-y:auto; }}
.sidebar h2 {{ color:#60a5fa; margin-bottom:24px; padding-bottom:16px; border-bottom:1px solid #1e293b; }}
.sidebar a {{ display:block; padding:10px 14px; color:#94a3b8; text-decoration:none; border-radius:8px; margin-bottom:2px; }}
.sidebar a:hover {{ background:#1e293b; color:#e2e8f0; }}
.sidebar a.active {{ background:#1e293b; color:#60a5fa; }}
.main {{ margin-left:220px; padding:32px 40px; flex:1; }}
.main h1 {{ font-size:2rem; margin-bottom:24px; }}
.card {{ background:#1e293b; padding:24px; border-radius:12px; border:1px solid #334155; margin-bottom:20px; }}
.btn {{ padding:8px 16px; border:none; border-radius:6px; font-weight:600; cursor:pointer; }}
.btn-primary {{ background:#3b82f6; color:white; }}
.btn-primary:hover {{ background:#2563eb; }}
.btn-secondary {{ background:#334155; color:#e2e8f0; }}
.btn-secondary:hover {{ background:#475569; }}
</style>
</head>
<body>
<div class="sidebar">
<h2> {brand}</h2>
<a href="/admin">Dashboard</a>
<a href="/admin/ai" class="active">AI</a>
<a href="/admin/telegram">Telegram</a>
<a href="/admin/whatsapp">WhatsApp</a>
<a href="/admin/plans">Plans</a>
<a href="/admin/config">Config</a>
</div>
<div class="main">
<h1>AI Providers</h1>
<div class="card">{html}</div>
<div id="message" style="margin-top:12px;padding:12px;border-radius:8px;display:none;"></div>
</div>
<script>
const providers = {json.dumps(providers)};
async function toggleProvider(idx) {{
    providers[idx].enabled = !providers[idx].enabled;
    try {{
        const res = await fetch('/api/config/batch', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{configs: {{ai_providers: providers}}}})
        }});
        if (res.ok) {{
            showMessage('Updated!', 'success');
            setTimeout(() => location.reload(), 1000);
        }}
    }} catch(e) {{
        showMessage('Error: ' + e.message, 'error');
    }}
}}
async function testProvider(idx) {{
    const resultSpan = document.getElementById('test_result_' + idx);
    resultSpan.textContent = 'Testing...';
    resultSpan.style.color = '#fbbf24';
    try {{
        const res = await fetch('/api/admin/ai/test', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{ provider_index: idx, message: "What is Nigerian contract law?" }})
        }});
        const data = await res.json();
        if (data.status === 'success') {{
            resultSpan.textContent = 'OK ' + data.response;
            resultSpan.style.color = '#10b981';
        }} else {{
            resultSpan.textContent = 'FAIL ' + data.response;
            resultSpan.style.color = '#ef4444';
        }}
    }} catch(e) {{
        resultSpan.textContent = 'Error';
        resultSpan.style.color = '#ef4444';
    }}
}}
function showMessage(msg, type) {{
    const el = document.getElementById('message');
    el.textContent = msg;
    el.style.display = 'block';
    el.style.background = type === 'success' ? '#10b98120' : '#ef444420';
    el.style.color = type === 'success' ? '#10b981' : '#ef4444';
    setTimeout(() => {{ el.style.display = 'none'; }}, 5000);
}}
</script>
</body>
</html>
"""

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
