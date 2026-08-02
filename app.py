# ============================================================
# POCKET LAWYER v14.0 - COMPLETE FULL VERSION
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
from fastapi import FastAPI, HTTPException, Request, File, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import httpx
import uvicorn

# ============================================================
# PDF GENERATION & READING
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

try:
    import fitz
    PDF_READER_AVAILABLE = True
except ImportError:
    PDF_READER_AVAILABLE = False

# ============================================================
# LOGGING
# ============================================================
os.makedirs('logs', exist_ok=True)
os.makedirs('data', exist_ok=True)
os.makedirs('documents', exist_ok=True)
os.makedirs('uploads', exist_ok=True)

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
# CONFIGURATION
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
             "features": ["AI Chat", "PDF Analysis"], "limits": {"requests": 100}},
            {"name": "Pro", "slug": "pro", "price_monthly": 5000,
             "features": ["AI Chat", "PDF Analysis", "PDF Generation", "Telegram"], "limits": {"requests": 1000}},
            {"name": "Enterprise", "slug": "enterprise", "price_monthly": 15000,
             "features": ["AI Chat", "PDF Analysis", "PDF Generation", "Telegram", "WhatsApp", "Team"], "limits": {"requests": 10000}}
        ],
        "quick_issues": [
            {"id": "tenancy", "title": "🏠 Tenancy & Landlord", "icon": "🏠"},
            {"id": "employment", "title": "💼 Employment Law", "icon": "💼"},
            {"id": "contract", "title": "📝 Contracts", "icon": "📝"},
            {"id": "family", "title": "👨‍👩‍👧‍👦 Family Law", "icon": "👨‍👩‍👧‍👦"},
            {"id": "debt", "title": "💰 Debt Recovery", "icon": "💰"},
            {"id": "criminal", "title": "⚖️ Criminal Law", "icon": "⚖️"},
            {"id": "corporate", "title": "🏢 Corporate Law", "icon": "🏢"},
            {"id": "property", "title": "🏡 Property Law", "icon": "🏡"}
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

    @classmethod
    def get_quick_issues(cls):
        return cls._config.get("quick_issues", [])

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

class AnalyzeRequest(BaseModel):
    document_id: str

class TelegramTestRequest(BaseModel):
    chat_id: str
    message: str = "Test message"

class WhatsAppTestRequest(BaseModel):
    to: str
    message: str = "Test message"

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
• 📄 Generate PDF documents
• 📑 Analyze uploaded PDF documents
• ⚖️ Answer legal questions
• 📝 Create contracts and agreements
• 📤 Upload PDFs for AI analysis

Try asking:
• "Generate a tenancy agreement PDF"
• "Analyze this contract"
• "What are tenant rights in Lagos?"

📤 You can upload PDF documents for AI analysis!

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
        payload = {"model": model, "messages": full_messages, "temperature": 0.2, "max_tokens": 2000}
        async with httpx.AsyncClient(timeout=45.0) as client:
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

async def get_ai_response(messages):
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
# PDF READER & ANALYZER
# ============================================================
class PDFAnalyzer:
    @staticmethod
    def extract_text_from_pdf(file_content):
        if not PDF_READER_AVAILABLE:
            raise Exception("PyMuPDF not installed. Install with: pip install PyMuPDF")
        
        try:
            doc = fitz.open(stream=file_content, filetype="pdf")
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text
        except Exception as e:
            raise Exception(f"PDF reading error: {str(e)}")

    @staticmethod
    def analyze_pdf_content(text, analysis_type="summary"):
        if len(text) > 10000:
            text = text[:10000] + "... [content truncated]"
        
        prompts = {
            "summary": f"Please provide a clear summary of this document:\n\n{text}",
            "key_points": f"Extract the key points from this document:\n\n{text}",
            "legal_issues": f"Identify potential legal issues in this document:\n\n{text}",
            "contract_review": f"Review this contract and identify key terms, risks, and missing clauses:\n\n{text}"
        }
        return prompts.get(analysis_type, prompts["summary"])

# ============================================================
# DOCUMENT STORAGE
# ============================================================
documents = {}
uploaded_docs = {}

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
# API ENDPOINTS - DOCUMENTS
# ============================================================
@app.post("/api/documents/upload")
async def upload_pdf(file: UploadFile = File(...)):
    try:
        content = await file.read()
        filename = file.filename
        
        if not filename.lower().endswith('.pdf'):
            return {"status": "error", "message": "Only PDF files are supported"}
        
        if not PDF_READER_AVAILABLE:
            return {"status": "error", "message": "PDF reader not available"}
        
        extracted_text = PDFAnalyzer.extract_text_from_pdf(content)
        
        doc_id = f"upload_{int(time.time())}_{hashlib.md5(filename.encode()).hexdigest()[:6]}"
        uploaded_docs[doc_id] = {
            "filename": filename,
            "content": extracted_text,
            "size": len(content),
            "created_at": datetime.utcnow().isoformat(),
            "analysis": None
        }
        
        file_path = os.path.join("uploads", f"{doc_id}_{filename}")
        with open(file_path, 'wb') as f:
            f.write(content)
        
        return {
            "status": "success",
            "document_id": doc_id,
            "filename": filename,
            "characters": len(extracted_text),
            "words": len(extracted_text.split()),
            "message": "PDF uploaded and processed successfully!"
        }
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/documents/analyze")
async def analyze_pdf(request: AnalyzeRequest):
    doc = uploaded_docs.get(request.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    try:
        content = doc["content"]
        if len(content) > 8000:
            content = content[:8000] + "... [truncated]"
        
        prompt = f"""Please analyze this legal document and provide:
1. A clear summary of what this document is about
2. Key parties involved (if any)
3. Main terms and conditions
4. Potential legal issues or risks
5. Missing clauses or recommendations

Document content:
{content}"""
        
        messages = [{"role": "user", "content": prompt}]
        result = await get_ai_response(messages)
        
        if result["reply"]:
            doc["analysis"] = result["reply"]
            return {
                "status": "success",
                "analysis": result["reply"],
                "provider": result["provider"]
            }
        
        return {"status": "error", "message": "Analysis failed"}
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/documents/uploaded")
async def list_uploaded_documents():
    return {
        "status": "success",
        "documents": [
            {
                "id": doc_id,
                "filename": doc["filename"],
                "created_at": doc["created_at"],
                "has_analysis": doc.get("analysis") is not None,
                "characters": len(doc["content"])
            }
            for doc_id, doc in uploaded_docs.items()
        ]
    }

@app.get("/api/documents/uploaded/{doc_id}")
async def get_uploaded_document(doc_id: str):
    doc = uploaded_docs.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "success", "document": doc}

@app.delete("/api/documents/uploaded/{doc_id}")
async def delete_uploaded_document(doc_id: str):
    if doc_id in uploaded_docs:
        del uploaded_docs[doc_id]
        return {"status": "success", "message": "Document deleted"}
    raise HTTPException(status_code=404, detail="Document not found")

# ============================================================
# API ENDPOINTS - CHAT & CONFIG
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

    result = await get_ai_response([{"role": "user", "content": chat_req.message}])
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

@app.get("/api/quick-issues")
async def get_quick_issues():
    return {"issues": ConfigStore.get_quick_issues()}

@app.get("/api/health")
async def health():
    return {
        "status": "healthy",
        "version": VERSION,
        "pdf_available": PDF_AVAILABLE,
        "pdf_reader": PDF_READER_AVAILABLE,
        "documents": len(documents),
        "uploaded_documents": len(uploaded_docs)
    }

# ============================================================
# ADMIN TEST ENDPOINTS
# ============================================================
@app.post("/api/admin/ai/test")
async def test_provider(request: Request):
    data = await request.json()
    idx = data.get("provider_index")
    msg = data.get("message", "What is Nigerian contract law?")
    providers = ConfigStore.get_ai_providers()
    if idx is None or idx < 0 or idx >= len(providers):
        return {"status": "error", "response": "Invalid provider"}
    p = providers[idx]
    messages = [{"role": "user", "content": msg}]
    try:
        if p.get("name") == "OpenRouter":
            reply, _ = await call_provider(p.get("base_url"), p.get("api_key"), p.get("model"), messages)
        else:
            reply, _ = await call_provider(p.get("base_url"), p.get("api_key"), p.get("model"), messages)
        if reply:
            return {"status": "success", "response": reply[:200]}
        return {"status": "error", "response": "No response"}
    except Exception as e:
        return {"status": "error", "response": str(e)}

# ============================================================
# TELEGRAM - WITH PDF PROCESSING
# ============================================================
telegram_running = False
telegram_thread = None
telegram_lock = threading.Lock()

def start_telegram_polling():
    global telegram_running, telegram_thread
    with telegram_lock:
        if telegram_running: return
        telegram_running = True
        telegram_thread = threading.Thread(target=run_telegram_polling, daemon=True)
        telegram_thread.start()
        logger.info("Telegram polling started")

def stop_telegram_polling():
    global telegram_running
    with telegram_lock:
        telegram_running = False
        logger.info("Telegram polling stopped")

def run_telegram_polling():
    global telegram_running
    logger.info("Telegram polling loop started")
    offset = 0
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")
    while telegram_running:
        try:
            tg = ConfigStore.get_telegram()
            if not tg.get("enabled") or not tg.get("bot_token"):
                time.sleep(5); continue
            if offset == 0: offset = tg.get("last_offset", 0)
            url = f"https://api.telegram.org/bot{tg['bot_token']}/getUpdates"
            response = httpx.get(url, params={"offset": offset, "timeout": 5}, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    for update in data.get("result", []):
                        offset = update.get("update_id", 0) + 1
                        ConfigStore.set("telegram", {**tg, "last_offset": offset})
                        if "message" in update:
                            msg = update["message"]
                            chat_id = str(msg.get("chat", {}).get("id", ""))
                            text = msg.get("text", "")
                            if chat_id and text and not text.startswith("/"):
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                reply = loop.run_until_complete(process_telegram_message(text, brand))
                                loop.close()
                                full_reply = f"{reply}\n\n- {brand}"
                                send_url = f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage"
                                httpx.post(send_url, json={"chat_id": chat_id, "text": full_reply[:4000]})
            elif response.status_code == 409:
                time.sleep(10)
        except Exception as e:
            logger.error(f"Telegram error: {e}")
        time.sleep(2)

async def process_telegram_message(text, brand):
    """Process Telegram message with PDF support"""
    if is_greeting(text):
        return get_greeting_response(brand)
    
    # Check for PDF generation
    pdf_keywords = ["generate pdf", "create pdf", "make pdf", "tenancy agreement", "nda"]
    if any(word in text.lower() for word in pdf_keywords):
        result = await generate_document_from_chat(text)
        if result.get("status") == "success":
            return f"📄 Document generated: {result.get('title')}\n\nTo download: https://pocket-lawyer-v14.onrender.com/api/documents/{result.get('document_id')}/download"
        else:
            return f"❌ Failed to generate PDF: {result.get('message', 'Unknown error')}"
    
    # Regular AI response
    result = await get_ai_response([{"role": "user", "content": text}])
    return result["reply"]

@app.post("/api/telegram/test")
async def test_telegram(request: TelegramTestRequest):
    chat_id = request.chat_id
    message = request.message
    tg = ConfigStore.get_telegram()
    bot_token = tg.get("bot_token")
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")
    
    if not bot_token:
        return {"status": "error", "message": "Bot token not configured"}
    
    if not tg.get("enabled"):
        return {"status": "error", "message": "Telegram is disabled"}
    
    try:
        # Process message
        if is_greeting(message):
            reply = get_greeting_response(brand)
        elif "generate" in message.lower() or "pdf" in message.lower():
            result = await generate_document_from_chat(message)
            if result.get("status") == "success":
                reply = f"📄 Document generated: {result.get('title')}\n\nTo download: https://pocket-lawyer-v14.onrender.com/api/documents/{result.get('document_id')}/download"
            else:
                reply = f"❌ Failed to generate PDF: {result.get('message', 'Unknown error')}"
        else:
            result = await get_ai_response([{"role": "user", "content": message}])
            reply = result["reply"]
        
        full_reply = f"{reply}\n\n- {brand}"
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json={"chat_id": chat_id, "text": full_reply[:4000]})
            return {"status": "success" if resp.status_code == 200 else "error", "message": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ============================================================
# WHATSAPP - WITH PDF PROCESSING
# ============================================================
@app.post("/api/whatsapp/test")
async def test_whatsapp(request: WhatsAppTestRequest):
    to = request.to
    message = request.message
    wa = ConfigStore.get_whatsapp()
    phone_id = wa.get("phone_number_id")
    token = wa.get("access_token")
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")
    
    if not phone_id or not token:
        return {"status": "error", "message": "WhatsApp not configured"}
    
    if not wa.get("enabled"):
        return {"status": "error", "message": "WhatsApp is disabled"}
    
    try:
        if is_greeting(message):
            reply = get_greeting_response(brand)
        elif "generate" in message.lower() or "pdf" in message.lower():
            result = await generate_document_from_chat(message)
            if result.get("status") == "success":
                reply = f"📄 Document generated: {result.get('title')}\n\nTo download: https://pocket-lawyer-v14.onrender.com/api/documents/{result.get('document_id')}/download"
            else:
                reply = f"❌ Failed to generate PDF: {result.get('message', 'Unknown error')}"
        else:
            result = await get_ai_response([{"role": "user", "content": message}])
            reply = result["reply"]
        
        full_reply = f"{reply}\n\n- {brand}"
        url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": full_reply[:4000]}}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            return {"status": "success" if resp.status_code in [200, 201, 202] else "error", "message": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ============================================================
# WHATSAPP WEBHOOKS
# ============================================================
@app.post("/api/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    try:
        data = await request.json()
        wa = ConfigStore.get_whatsapp()
        if not wa.get("enabled"):
            return {"status": "disabled"}
        
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        
        if not messages:
            return {"status": "ignored"}
        
        msg = messages[0]
        from_number = msg.get("from")
        text = msg.get("text", {}).get("body")
        
        if not from_number or not text:
            return {"status": "ignored"}
        
        brand = ConfigStore.get("brand_name", "Pocket Lawyer")
        
        # Process message
        if is_greeting(text):
            reply = get_greeting_response(brand)
        elif "generate" in text.lower() or "pdf" in text.lower():
            result = await generate_document_from_chat(text)
            if result.get("status") == "success":
                reply = f"📄 Document generated: {result.get('title')}\n\nTo download: https://pocket-lawyer-v14.onrender.com/api/documents/{result.get('document_id')}/download"
            else:
                reply = f"❌ Failed to generate PDF: {result.get('message', 'Unknown error')}"
        else:
            result = await get_ai_response([{"role": "user", "content": text}])
            reply = result["reply"]
        
        full_reply = f"{reply}\n\n- {brand}"
        phone_id = wa.get("phone_number_id")
        token = wa.get("access_token")
        
        if phone_id and token:
            url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            payload = {"messaging_product": "whatsapp", "to": from_number, "type": "text", "text": {"body": full_reply[:4000]}}
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.post(url, json=payload, headers=headers)
        
        return {"status": "success"}
    except Exception as e:
        logger.error(f"WhatsApp webhook error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/webhook/whatsapp")
async def verify_whatsapp(hub_mode=None, hub_token=None, hub_challenge=None):
    wa = ConfigStore.get_whatsapp()
    verify_token = wa.get("verify_token", "pocket_lawyer_2024")
    if hub_mode == "subscribe" and hub_token == verify_token:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(403, "Verification failed")

# ============================================================
# TELEGRAM WEBHOOK
# ============================================================
@app.post("/api/webhook/telegram")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        if "message" not in data:
            return {"status": "ignored"}
        
        msg = data["message"]
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "")
        
        if not chat_id or not text or text.startswith("/"):
            return {"status": "ignored"}
        
        brand = ConfigStore.get("brand_name", "Pocket Lawyer")
        tg = ConfigStore.get_telegram()
        
        # Process message
        if is_greeting(text):
            reply = get_greeting_response(brand)
        elif "generate" in text.lower() or "pdf" in text.lower():
            result = await generate_document_from_chat(text)
            if result.get("status") == "success":
                reply = f"📄 Document generated: {result.get('title')}\n\nTo download: https://pocket-lawyer-v14.onrender.com/api/documents/{result.get('document_id')}/download"
            else:
                reply = f"❌ Failed to generate PDF: {result.get('message', 'Unknown error')}"
        else:
            result = await get_ai_response([{"role": "user", "content": text}])
            reply = result["reply"]
        
        bot_token = tg.get("bot_token")
        full_reply = f"{reply}\n\n- {brand}"
        
        if bot_token:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.post(url, json={"chat_id": chat_id, "text": full_reply[:4000]})
        
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Telegram webhook error: {e}")
        return {"status": "error", "message": str(e)}

# ============================================================
# LIFECYCLE
# ============================================================
@app.on_event("startup")
async def startup():
    logger.info(f"Starting {APP_NAME} v{VERSION}")
    logger.info(f"PDF Generation: {'✅' if PDF_AVAILABLE else '❌'}")
    logger.info(f"PDF Reader: {'✅' if PDF_READER_AVAILABLE else '❌'}")
    start_telegram_polling()

@app.on_event("shutdown")
async def shutdown():
    stop_telegram_polling()
    logger.info("Shutting down")

# ============================================================
# UI PAGES (Simplified - Home, Chat, Admin)
# ============================================================
@app.get("/")
async def home():
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")
    return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <title>{brand}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }}
        .header {{ background: #1e293b; padding: 20px 40px; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }}
        .header h1 {{ color: #60a5fa; font-size: 1.8rem; }}
        .btn {{ padding: 10px 24px; border: none; border-radius: 8px; font-weight: 600; cursor: pointer; text-decoration: none; display: inline-block; transition: all 0.3s; }}
        .btn-primary {{ background: #3b82f6; color: white; }}
        .btn-primary:hover {{ background: #2563eb; transform: translateY(-2px); }}
        .btn-secondary {{ background: #334155; color: #e2e8f0; }}
        .btn-secondary:hover {{ background: #475569; transform: translateY(-2px); }}
        .btn-success {{ background: #10b981; color: white; }}
        .btn-success:hover {{ background: #059669; transform: translateY(-2px); }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
        .hero {{ text-align: center; padding: 40px 0; background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border-radius: 16px; border: 1px solid #334155; margin-bottom: 32px; }}
        .hero h1 {{ font-size: 3rem; color: #60a5fa; }}
        .hero p {{ font-size: 1.2rem; color: #94a3b8; margin: 12px 0; }}
        .badge {{ display: inline-block; background: #10b98120; color: #10b981; padding: 4px 16px; border-radius: 20px; font-size: 0.8rem; border: 1px solid #10b98140; margin: 4px; }}
        .features {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin: 32px 0; }}
        .feature {{ background: #1e293b; padding: 24px; border-radius: 12px; border: 1px solid #334155; text-align: center; }}
        .feature .icon {{ font-size: 2.5rem; }}
        .feature h3 {{ color: #60a5fa; margin: 8px 0; }}
        .feature p {{ color: #94a3b8; font-size: 0.9rem; }}
        .upload-zone {{ border: 2px dashed #334155; border-radius: 16px; padding: 40px; text-align: center; background: #1e293b; cursor: pointer; transition: all 0.3s; margin: 24px 0; }}
        .upload-zone:hover {{ border-color: #3b82f6; background: #253450; }}
        .upload-zone .icon {{ font-size: 3rem; }}
        .upload-zone input {{ display: none; }}
        .issues-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 12px; margin: 16px 0; }}
        .issue-card {{ background: #1e293b; padding: 16px 20px; border-radius: 10px; border: 1px solid #334155; display: flex; align-items: center; gap: 12px; cursor: pointer; transition: all 0.3s; }}
        .issue-card:hover {{ border-color: #60a5fa; transform: translateX(4px); background: #253450; }}
        .footer {{ text-align: center; color: #64748b; font-size: 0.8rem; margin-top: 32px; padding-top: 16px; border-top: 1px solid #1e293b; }}
        @media (max-width: 768px) {{ .header {{ flex-direction: column; text-align: center; }} .hero h1 {{ font-size: 2rem; }} }}
    </style>
</head>
<body>
<div class="header">
    <div><h1>⚖️ {brand}</h1><div style="color:#94a3b8;font-size:0.9rem;">AI Legal Assistant for Nigerian Law</div></div>
    <div><a href="/chat" class="btn btn-primary">💬 Chat</a><a href="/admin" class="btn btn-secondary">⚙️ Admin</a></div>
</div>
<div class="container">
    <div class="hero">
        <h1>🇳🇬 Nigerian Law, Powered by AI</h1>
        <p>Get instant legal guidance, generate documents, and analyze contracts</p>
        <div><span class="badge">📄 PDF Generation</span><span class="badge">🔍 Document Analysis</span><span class="badge">⚖️ Nigerian Law</span></div>
        <div style="margin-top:20px;"><a href="/chat" class="btn btn-primary">💬 Start Chat</a><a href="#upload" class="btn btn-success">📤 Upload PDF</a></div>
    </div>
    <div class="features">
        <div class="feature"><div class="icon">📄</div><h3>Generate PDFs</h3><p>Create legal documents and contracts</p></div>
        <div class="feature"><div class="icon">🔍</div><h3>Analyze Documents</h3><p>Upload PDFs for AI analysis</p></div>
        <div class="feature"><div class="icon">💬</div><h3>AI Chat</h3><p>Get instant legal answers</p></div>
        <div class="feature"><div class="icon">🤖</div><h3>Telegram & WhatsApp</h3><p>Chat on your favorite platforms</p></div>
    </div>
    <div class="upload-zone" onclick="document.getElementById('fileInput').click()">
        <div class="icon">📤</div>
        <h3>Upload PDF Document</h3>
        <p>Upload a PDF for AI analysis and review</p>
        <input type="file" id="fileInput" accept=".pdf" onchange="uploadPDF(this)">
        <div id="uploadStatus" style="margin-top:12px;color:#94a3b8;"></div>
    </div>
    <div id="issuesContainer" style="margin:24px 0;">
        <h2>📌 Quick Legal Issues</h2>
        <div class="issues-grid" id="issuesGrid"></div>
    </div>
    <div class="footer"><p>⚖️ {brand} v{VERSION} • General guidance only</p></div>
</div>
<script>
const issues = {json.dumps(ConfigStore.get_quick_issues())};
const issuesGrid = document.getElementById('issuesGrid');
issues.forEach(issue => {{
    const card = document.createElement('div');
    card.className = 'issue-card';
    card.innerHTML = `<div class="issue-icon">${{issue.icon}}</div><div class="issue-title">${{issue.title}}</div>`;
    card.onclick = () => window.location.href = `/chat?q=${encodeURIComponent(issue.title)}`;
    issuesGrid.appendChild(card);
}});
async function uploadPDF(input) {{
    if (!input.files || input.files.length === 0) return;
    const file = input.files[0];
    const formData = new FormData();
    formData.append('file', file);
    const status = document.getElementById('uploadStatus');
    status.textContent = '⏳ Uploading...';
    status.style.color = '#fbbf24';
    try {{
        const res = await fetch('/api/documents/upload', {{ method: 'POST', body: formData }});
        const data = await res.json();
        if (data.status === 'success') {{
            status.textContent = `✅ Uploaded: ${{data.filename}} (${{data.words}} words)`;
            status.style.color = '#10b981';
            const analyze = confirm('Document uploaded! Analyze it now?');
            if (analyze) {{
                const res2 = await fetch('/api/documents/analyze', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{ document_id: data.document_id }})
                }});
                const data2 = await res2.json();
                if (data2.status === 'success') {{
                    alert('📄 Analysis:\\n\\n' + data2.analysis);
                }}
            }}
        }} else {{
            status.textContent = `❌ ${{data.message}}`;
            status.style.color = '#ef4444';
        }}
    }} catch(e) {{
        status.textContent = `❌ Error: ${{e.message}}`;
        status.style.color = '#ef4444';
    }}
    input.value = '';
}}
</script>
</body>
</html>
""")

# ============================================================
# ADMIN PAGES (DASHBOARD, AI, TELEGRAM, WHATSAPP, PLANS, CONFIG)
# ============================================================
@app.get("/admin")
async def admin_dashboard():
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")
    providers = ConfigStore.get_ai_providers()
    plans = ConfigStore.get_plans()
    tg = ConfigStore.get_telegram()
    wa = ConfigStore.get_whatsapp()
    stats = ProviderRotator.get_stats()

    return HTMLResponse(f"""
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
<div class="sidebar"><h2>{brand}</h2>
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
<div class="stat-card"><div class="stat-value">{"✅" if tg.get("enabled") else "❌"}</div><div class="stat-label">Telegram</div></div>
<div class="stat-card"><div class="stat-value">{"✅" if wa.get("enabled") else "❌"}</div><div class="stat-label">WhatsApp</div></div>
<div class="stat-card"><div class="stat-value">{"✅" if PDF_AVAILABLE else "❌"}</div><div class="stat-label">PDF Generation</div></div>
<div class="stat-card"><div class="stat-value">v{VERSION}</div><div class="stat-label">Version</div></div>
</div>
<div class="card"><h3>Quick Actions</h3>
<div style="display:flex;gap:8px;flex-wrap:wrap;">
<a href="/admin/ai" class="btn">Manage AI</a>
<a href="/admin/telegram" class="btn">Telegram</a>
<a href="/admin/whatsapp" class="btn">WhatsApp</a>
<a href="/admin/config" class="btn">Config</a>
<a href="/chat" class="btn">Chat</a>
</div>
</div>
</div>
</body>
</html>
""")

# ============================================================
# ADMIN: AI PROVIDERS
# ============================================================
@app.get("/admin/ai")
async def admin_ai():
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")
    providers = ConfigStore.get_ai_providers()
    html = ""
    for idx, p in enumerate(providers):
        html += f"""
        <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #1e293b;">
            <span><strong>{p.get("name")}</strong> <span style="padding:2px 12px;border-radius:12px;font-size:0.7rem;background:{'#10b98120' if p.get('enabled') else '#ef444420'};color:{'#10b981' if p.get('enabled') else '#ef4444'};border:1px solid {'#10b98140' if p.get('enabled') else '#ef444440'};">{"ON" if p.get("enabled") else "OFF"}</span></span>
            <div><button class="btn" onclick="toggleProvider({idx})">Toggle</button> <button class="btn" onclick="testProvider({idx})">Test</button> <span id="test_result_{idx}"></span></div>
        </div>
        """
    return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head><title>{brand} - AI</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; background: #0f172a; color: #e2e8f0; display: flex; min-height: 100vh; }}
.sidebar {{ width:220px; background:#0f172a; border-right:1px solid #1e293b; padding:24px 16px; position:fixed; top:0; left:0; bottom:0; overflow-y:auto; }}
.sidebar h2 {{ color:#60a5fa; margin-bottom:24px; padding-bottom:16px; border-bottom:1px solid #1e293b; }}
.sidebar a {{ display:block; padding:10px 14px; color:#94a3b8; text-decoration:none; border-radius:8px; margin-bottom:2px; }}
.sidebar a:hover {{ background:#1e293b; color:#e2e8f0; }}
.sidebar a.active {{ background:#1e293b; color:#60a5fa; }}
.main {{ margin-left:220px; padding:32px 40px; flex:1; }}
.main h1 {{ font-size:2rem; margin-bottom:24px; }}
.card {{ background:#1e293b; padding:24px; border-radius:12px; border:1px solid #334155; margin-bottom:20px; }}
.btn {{ padding:8px 16px; border:none; border-radius:6px; font-weight:600; cursor:pointer; background:#3b82f6; color:white; }}
.btn:hover {{ background:#2563eb; }}
</style>
</head>
<body>
<div class="sidebar"><h2>{brand}</h2>
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
</div>
<script>
const providers = {json.dumps(providers)};
async function toggleProvider(idx) {{
    providers[idx].enabled = !providers[idx].enabled;
    await fetch('/api/config/batch', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{configs: {{ai_providers: providers}}}})
    }});
    location.reload();
}}
async function testProvider(idx) {{
    const span = document.getElementById('test_result_' + idx);
    span.textContent = 'Testing...';
    span.style.color = '#fbbf24';
    try {{
        const res = await fetch('/api/admin/ai/test', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{ provider_index: idx, message: "What is Nigerian contract law?" }})
        }});
        const data = await res.json();
        if (data.status === 'success') {{
            span.textContent = '✅ ' + data.response;
            span.style.color = '#10b981';
        }} else {{
            span.textContent = '❌ ' + data.response;
            span.style.color = '#ef4444';
        }}
    }} catch(e) {{
        span.textContent = '❌ Error';
        span.style.color = '#ef4444';
    }}
}}
</script>
</body>
</html>
""")

# ============================================================
# ADMIN: TELEGRAM
# ============================================================
@app.get("/admin/telegram")
async def admin_telegram():
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")
    tg = ConfigStore.get_telegram()
    return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head><title>{brand} - Telegram</title>
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
.card h3 {{ margin-bottom:12px; }}
.btn {{ padding:8px 20px; border:none; border-radius:8px; font-weight:600; cursor:pointer; }}
.btn-primary {{ background:#3b82f6; color:white; }}
.btn-primary:hover {{ background:#2563eb; }}
.btn-success {{ background:#10b981; color:white; }}
.btn-success:hover {{ background:#059669; }}
.btn-danger {{ background:#ef4444; color:white; }}
.btn-danger:hover {{ background:#dc2626; }}
.input-field {{ background:#0f172a; color:#e2e8f0; border:1px solid #334155; border-radius:6px; padding:8px 12px; width:100%; margin-bottom:8px; }}
.grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
label {{ color:#94a3b8; display:block; margin-bottom:4px; font-size:0.9rem; }}
.status-on {{ background:#10b98120; color:#10b981; padding:8px 16px; border-radius:8px; border:1px solid #10b98140; display:inline-block; }}
.status-off {{ background:#ef444420; color:#ef4444; padding:8px 16px; border-radius:8px; border:1px solid #ef444440; display:inline-block; }}
</style>
</head>
<body>
<div class="sidebar"><h2>{brand}</h2>
<a href="/admin">Dashboard</a>
<a href="/admin/ai">AI</a>
<a href="/admin/telegram" class="active">Telegram</a>
<a href="/admin/whatsapp">WhatsApp</a>
<a href="/admin/plans">Plans</a>
<a href="/admin/config">Config</a>
</div>
<div class="main">
<h1>Telegram Settings</h1>
<div class="card">
<h3>Status: <span class="status-{"on" if tg.get("enabled") else "off"}">{"🟢 Enabled" if tg.get("enabled") else "🔴 Disabled"}</span></h3>
<div class="grid-2">
<div><label>Bot Token</label><input type="text" id="bot_token" class="input-field" value="{tg.get('bot_token', '')}"></div>
<div><label>Bot Username</label><input type="text" id="bot_username" class="input-field" value="{tg.get('bot_username', '')}"></div>
</div>
<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;">
<button class="btn btn-primary" onclick="saveTelegram()">💾 Save</button>
<button class="btn btn-success" onclick="toggleTelegram()">{"🔴 Disable" if tg.get("enabled") else "🟢 Enable"}</button>
</div>
<div id="tg_msg" style="margin-top:12px;padding:12px;border-radius:8px;display:none;"></div>
</div>
<div class="card">
<h3>Test Telegram Bot</h3>
<div class="grid-2">
<div><label>Chat ID</label><input type="text" id="test_chat_id" class="input-field" placeholder="Enter your chat ID"></div>
<div><label>Message</label><input type="text" id="test_message" class="input-field" value="Hello from {brand}! Try: 'Generate a PDF'"></div>
</div>
<button class="btn btn-success" onclick="testTelegram()">📤 Send Test</button>
<div id="test_result" style="margin-top:12px;padding:12px;border-radius:8px;display:none;"></div>
</div>
</div>
<script>
async function saveTelegram() {{
    const msg = document.getElementById('tg_msg');
    try {{
        const res = await fetch('/api/config/batch', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{configs: {{telegram: {{enabled: true, bot_token: document.getElementById('bot_token').value, bot_username: document.getElementById('bot_username').value}}}}}})
        }});
        const data = await res.json();
        msg.style.display = 'block';
        msg.style.background = data.status === 'success' ? '#10b98120' : '#ef444420';
        msg.style.color = data.status === 'success' ? '#10b981' : '#ef4444';
        msg.textContent = data.status === 'success' ? '✅ Saved!' : '❌ Failed';
        if (data.status === 'success') setTimeout(() => location.reload(), 1000);
    }} catch(e) {{
        msg.style.display = 'block';
        msg.style.background = '#ef444420';
        msg.style.color = '#ef4444';
        msg.textContent = '❌ Error: ' + e.message;
    }}
}}
async function toggleTelegram() {{
    const current = {str(tg.get("enabled")).lower()};
    try {{
        const res = await fetch('/api/config/batch', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{configs: {{telegram: {{enabled: !current}}}}}})
        }});
        const data = await res.json();
        if (data.status === 'success') location.reload();
    }} catch(e) {{
        alert('Error: ' + e.message);
    }}
}}
async function testTelegram() {{
    const result = document.getElementById('test_result');
    const chatId = document.getElementById('test_chat_id').value;
    if (!chatId) {{
        result.style.display = 'block';
        result.style.background = '#ef444420';
        result.style.color = '#ef4444';
        result.textContent = '❌ Chat ID required';
        return;
    }}
    result.style.display = 'block';
    result.textContent = '⏳ Sending...';
    result.style.background = '#0f172a';
    result.style.color = '#fbbf24';
    try {{
        const res = await fetch('/api/telegram/test', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{chat_id: chatId, message: document.getElementById('test_message').value}})
        }});
        const data = await res.json();
        result.style.background = data.status === 'success' ? '#10b98120' : '#ef444420';
        result.style.color = data.status === 'success' ? '#10b981' : '#ef4444';
        result.textContent = data.status === 'success' ? '✅ Message sent!' : '❌ ' + data.message;
    }} catch(e) {{
        result.style.background = '#ef444420';
        result.style.color = '#ef4444';
        result.textContent = '❌ Error: ' + e.message;
    }}
}}
</script>
</body>
</html>
""")

# ============================================================
# ADMIN: WHATSAPP
# ============================================================
@app.get("/admin/whatsapp")
async def admin_whatsapp():
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")
    wa = ConfigStore.get_whatsapp()
    return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head><title>{brand} - WhatsApp</title>
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
.card h3 {{ margin-bottom:12px; }}
.btn {{ padding:8px 20px; border:none; border-radius:8px; font-weight:600; cursor:pointer; }}
.btn-primary {{ background:#3b82f6; color:white; }}
.btn-primary:hover {{ background:#2563eb; }}
.btn-success {{ background:#10b981; color:white; }}
.btn-success:hover {{ background:#059669; }}
.btn-danger {{ background:#ef4444; color:white; }}
.btn-danger:hover {{ background:#dc2626; }}
.input-field {{ background:#0f172a; color:#e2e8f0; border:1px solid #334155; border-radius:6px; padding:8px 12px; width:100%; margin-bottom:8px; }}
.grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
label {{ color:#94a3b8; display:block; margin-bottom:4px; font-size:0.9rem; }}
.status-on {{ background:#10b98120; color:#10b981; padding:8px 16px; border-radius:8px; border:1px solid #10b98140; display:inline-block; }}
.status-off {{ background:#ef444420; color:#ef4444; padding:8px 16px; border-radius:8px; border:1px solid #ef444440; display:inline-block; }}
</style>
</head>
<body>
<div class="sidebar"><h2>{brand}</h2>
<a href="/admin">Dashboard</a>
<a href="/admin/ai">AI</a>
<a href="/admin/telegram">Telegram</a>
<a href="/admin/whatsapp" class="active">WhatsApp</a>
<a href="/admin/plans">Plans</a>
<a href="/admin/config">Config</a>
</div>
<div class="main">
<h1>WhatsApp Settings</h1>
<div class="card">
<h3>Status: <span class="status-{"on" if wa.get("enabled") else "off"}">{"🟢 Enabled" if wa.get("enabled") else "🔴 Disabled"}</span></h3>
<div class="grid-2">
<div><label>Phone Number ID</label><input type="text" id="wa_phone" class="input-field" value="{wa.get('phone_number_id', '')}"></div>
<div><label>Access Token</label><input type="password" id="wa_token" class="input-field" value="{wa.get('access_token', '')}"></div>
</div>
<div><label>Verify Token</label><input type="text" id="wa_verify" class="input-field" value="{wa.get('verify_token', 'pocket_lawyer_2024')}"></div>
<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;">
<button class="btn btn-primary" onclick="saveWhatsApp()">💾 Save</button>
<button class="btn btn-success" onclick="toggleWhatsApp()">{"🔴 Disable" if wa.get("enabled") else "🟢 Enable"}</button>
</div>
<div id="wa_msg" style="margin-top:12px;padding:12px;border-radius:8px;display:none;"></div>
</div>
<div class="card">
<h3>Test WhatsApp</h3>
<div class="grid-2">
<div><label>Phone Number</label><input type="text" id="wa_test_to" class="input-field" placeholder="e.g., 2348012345678"></div>
<div><label>Message</label><input type="text" id="wa_test_msg" class="input-field" value="Hello from {brand}! Try: 'Generate a PDF'"></div>
</div>
<button class="btn btn-success" onclick="testWhatsApp()">📤 Send Test</button>
<div id="wa_test_result" style="margin-top:12px;padding:12px;border-radius:8px;display:none;"></div>
</div>
</div>
<script>
async function saveWhatsApp() {{
    const msg = document.getElementById('wa_msg');
    try {{
        const res = await fetch('/api/config/batch', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{configs: {{whatsapp: {{enabled: true, phone_number_id: document.getElementById('wa_phone').value, access_token: document.getElementById('wa_token').value, verify_token: document.getElementById('wa_verify').value}}}}}})
        }});
        const data = await res.json();
        msg.style.display = 'block';
        msg.style.background = data.status === 'success' ? '#10b98120' : '#ef444420';
        msg.style.color = data.status === 'success' ? '#10b981' : '#ef4444';
        msg.textContent = data.status === 'success' ? '✅ Saved!' : '❌ Failed';
    }} catch(e) {{
        msg.style.display = 'block';
        msg.style.background = '#ef444420';
        msg.style.color = '#ef4444';
        msg.textContent = '❌ Error: ' + e.message;
    }}
}}
async function toggleWhatsApp() {{
    const current = {str(wa.get("enabled")).lower()};
    try {{
        const res = await fetch('/api/config/batch', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{configs: {{whatsapp: {{enabled: !current}}}}}})
        }});
        const data = await res.json();
        if (data.status === 'success') location.reload();
    }} catch(e) {{
        alert('Error: ' + e.message);
    }}
}}
async function testWhatsApp() {{
    const result = document.getElementById('wa_test_result');
    const to = document.getElementById('wa_test_to').value;
    if (!to) {{
        result.style.display = 'block';
        result.style.background = '#ef444420';
        result.style.color = '#ef4444';
        result.textContent = '❌ Phone number required';
        return;
    }}
    result.style.display = 'block';
    result.textContent = '⏳ Sending...';
    result.style.background = '#0f172a';
    result.style.color = '#fbbf24';
    try {{
        const res = await fetch('/api/whatsapp/test', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{to: to, message: document.getElementById('wa_test_msg').value}})
        }});
        const data = await res.json();
        result.style.background = data.status === 'success' ? '#10b98120' : '#ef444420';
        result.style.color = data.status === 'success' ? '#10b981' : '#ef4444';
        result.textContent = data.status === 'success' ? '✅ Message sent!' : '❌ ' + data.message;
    }} catch(e) {{
        result.style.background = '#ef444420';
        result.style.color = '#ef4444';
        result.textContent = '❌ Error: ' + e.message;
    }}
}}
</script>
</body>
</html>
""")

# ============================================================
# ADMIN: PLANS
# ============================================================
@app.get("/admin/plans")
async def admin_plans():
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")
    plans = ConfigStore.get_plans()
    html = ""
    for p in plans:
        html += f"""
        <div style="background:#1e293b;padding:16px 20px;border-radius:10px;border:1px solid #334155;margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div><strong style="font-size:1.1rem;">{p.get('name')}</strong><br><span style="color:#94a3b8;font-size:0.8rem;">{', '.join(p.get('features', []))}</span></div>
                <div style="text-align:right;"><span style="font-size:1.2rem;color:#60a5fa;">₦{p.get('price_monthly')}</span><br><span style="color:#94a3b8;font-size:0.7rem;">/month</span></div>
            </div>
        </div>
        """
    return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head><title>{brand} - Plans</title>
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
.btn {{ padding:8px 20px; border:none; border-radius:8px; font-weight:600; cursor:pointer; }}
.btn-success {{ background:#10b981; color:white; }}
.btn-success:hover {{ background:#059669; }}
</style>
</head>
<body>
<div class="sidebar"><h2>{brand}</h2>
<a href="/admin">Dashboard</a>
<a href="/admin/ai">AI</a>
<a href="/admin/telegram">Telegram</a>
<a href="/admin/whatsapp">WhatsApp</a>
<a href="/admin/plans" class="active">Plans</a>
<a href="/admin/config">Config</a>
</div>
<div class="main">
<h1>Plans</h1>
{html}
<button class="btn btn-success" onclick="addPlan()" style="margin-top:12px;">Add Plan</button>
<div id="message" style="margin-top:12px;padding:12px;border-radius:8px;display:none;"></div>
</div>
<script>
let plans = {json.dumps(plans)};
function addPlan() {{
    const name = prompt('Enter plan name:');
    if (!name) return;
    const price = parseInt(prompt('Enter monthly price (NGN):')) || 0;
    const features = prompt('Enter features (comma separated):')?.split(',').map(f => f.trim()) || [];
    plans.push({{name: name, slug: name.toLowerCase().replace(/ /g, '_'), price_monthly: price, features: features, limits: {{requests: price > 0 ? 1000 : 100}}}});
    savePlans();
}}
async function savePlans() {{
    const msg = document.getElementById('message');
    try {{
        const res = await fetch('/api/config/batch', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{configs: {{plans: plans}}}})
        }});
        const data = await res.json();
        msg.style.display = 'block';
        msg.style.background = data.status === 'success' ? '#10b98120' : '#ef444420';
        msg.style.color = data.status === 'success' ? '#10b981' : '#ef4444';
        msg.textContent = data.status === 'success' ? '✅ Plans saved!' : '❌ Failed';
        if (data.status === 'success') setTimeout(() => location.reload(), 1000);
    }} catch(e) {{
        msg.style.display = 'block';
        msg.style.background = '#ef444420';
        msg.style.color = '#ef4444';
        msg.textContent = '❌ Error: ' + e.message;
    }}
}}
</script>
</body>
</html>
""")

# ============================================================
# ADMIN: CONFIG
# ============================================================
@app.get("/admin/config")
async def admin_config():
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")
    config = ConfigStore.get_all()
    return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head><title>{brand} - Config</title>
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
.card h3 {{ margin-bottom:12px; }}
.btn {{ padding:8px 20px; border:none; border-radius:8px; font-weight:600; cursor:pointer; }}
.btn-primary {{ background:#3b82f6; color:white; }}
.btn-primary:hover {{ background:#2563eb; }}
.input-field {{ background:#0f172a; color:#e2e8f0; border:1px solid #334155; border-radius:6px; padding:8px 12px; width:100%; margin-bottom:8px; }}
.grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
label {{ color:#94a3b8; display:block; margin-bottom:4px; font-size:0.9rem; }}
</style>
</head>
<body>
<div class="sidebar"><h2>{brand}</h2>
<a href="/admin">Dashboard</a>
<a href="/admin/ai">AI</a>
<a href="/admin/telegram">Telegram</a>
<a href="/admin/whatsapp">WhatsApp</a>
<a href="/admin/plans">Plans</a>
<a href="/admin/config" class="active">Config</a>
</div>
<div class="main">
<h1>Configuration</h1>
<div class="card">
<h3>Brand Settings</h3>
<div class="grid-2">
<div><label>Brand Name</label><input type="text" id="brand_name" class="input-field" value="{config.get('brand_name', 'Pocket Lawyer')}"></div>
<div><label>Currency</label><input type="text" id="currency" class="input-field" value="{config.get('currency', 'NGN')}"></div>
</div>
</div>
<div class="card">
<h3>System Prompt</h3>
<textarea id="system_prompt" class="input-field" rows="6">{config.get('system_prompt', '')}</textarea>
</div>
<button class="btn btn-primary" onclick="saveConfig()">Save</button>
<div id="message" style="margin-top:12px;padding:12px;border-radius:8px;display:none;"></div>
</div>
<script>
async function saveConfig() {{
    const msg = document.getElementById('message');
    try {{
        const res = await fetch('/api/config/batch', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{configs: {{
                brand_name: document.getElementById('brand_name').value,
                currency: document.getElementById('currency').value,
                system_prompt: document.getElementById('system_prompt').value
            }}}})
        }});
        const data = await res.json();
        msg.style.display = 'block';
        msg.style.background = data.status === 'success' ? '#10b98120' : '#ef444420';
        msg.style.color = data.status === 'success' ? '#10b981' : '#ef4444';
        msg.textContent = data.status === 'success' ? '✅ Saved!' : '❌ Failed';
        if (data.status === 'success') setTimeout(() => location.reload(), 1000);
    }} catch(e) {{
        msg.style.display = 'block';
        msg.style.background = '#ef444420';
        msg.style.color = '#ef4444';
        msg.textContent = '❌ Error: ' + e.message;
    }}
}}
</script>
</body>
</html>
""")

# ============================================================
# CHAT UI
# ============================================================
@app.get("/chat")
async def chat_ui():
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")
    return HTMLResponse(f"""
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
<div class="header"><h2>{brand}</h2><div><a href="/admin" class="btn">Admin</a><a href="/" class="btn">Home</a></div></div>
<div class="chat-container">
<div id="chatBox" class="chat-box">
<div class="message ai"><strong>{brand}</strong><br>Hello! I am your AI legal assistant for Nigerian Law.<br>Try: <strong>"Generate a tenancy agreement PDF"</strong></div>
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
    if (isHTML) {{ div.innerHTML = text; }} else {{ div.textContent = text; }}
    chatBox.appendChild(div);
    chatBox.scrollTop=chatBox.scrollHeight;
}}
function addTyping() {{
    const div=document.createElement('div');
    div.className='typing';
    div.id='typing';
    div.textContent='Thinking...';
    chatBox.appendChild(div);
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
""")

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
