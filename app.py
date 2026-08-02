# ============================================================
# POCKET LAWYER v14.0 - PDF ANALYSIS & GENERATION
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
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
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
    import fitz  # PyMuPDF
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
             "features": ["AI Chat", "PDF Analysis", "PDF Generation"], "limits": {"requests": 1000}},
            {"name": "Enterprise", "slug": "enterprise", "price_monthly": 15000,
             "features": ["AI Chat", "PDF Analysis", "PDF Generation", "Team"], "limits": {"requests": 10000}}
        ],
        "quick_issues": [
            {"id": "tenancy", "title": "🏠 Tenancy & Landlord Disputes", "icon": "🏠"},
            {"id": "employment", "title": "💼 Employment & Labour Law", "icon": "💼"},
            {"id": "contract", "title": "📝 Contracts & Agreements", "icon": "📝"},
            {"id": "family", "title": "👨‍👩‍👧‍👦 Family Law", "icon": "👨‍👩‍👧‍👦"},
            {"id": "debt", "title": "💰 Debt Recovery", "icon": "💰"},
            {"id": "criminal", "title": "⚖️ Criminal Law", "icon": "⚖️"},
            {"id": "corporate", "title": "🏢 Corporate Law (CAMA)", "icon": "🏢"},
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
        """Prepare content for AI analysis"""
        # Truncate if too long
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
# API ENDPOINTS
# ============================================================
@app.post("/api/documents/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """Upload and process a PDF document"""
    try:
        content = await file.read()
        filename = file.filename
        
        if not filename.lower().endswith('.pdf'):
            return {"status": "error", "message": "Only PDF files are supported"}
        
        if not PDF_READER_AVAILABLE:
            return {"status": "error", "message": "PDF reader not available"}
        
        # Extract text
        extracted_text = PDFAnalyzer.extract_text_from_pdf(content)
        
        # Save uploaded file
        doc_id = f"upload_{int(time.time())}_{hashlib.md5(filename.encode()).hexdigest()[:6]}"
        uploaded_docs[doc_id] = {
            "filename": filename,
            "content": extracted_text,
            "size": len(content),
            "created_at": datetime.utcnow().isoformat(),
            "analysis": None
        }
        
        # Save file to disk
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
    """Analyze an uploaded PDF document"""
    doc = uploaded_docs.get(request.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    try:
        # Prepare analysis prompt
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
    """List all uploaded documents"""
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
    """Get an uploaded document"""
    doc = uploaded_docs.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "success", "document": doc}

@app.delete("/api/documents/uploaded/{doc_id}")
async def delete_uploaded_document(doc_id: str):
    """Delete an uploaded document"""
    if doc_id in uploaded_docs:
        del uploaded_docs[doc_id]
        return {"status": "success", "message": "Document deleted"}
    raise HTTPException(status_code=404, detail="Document not found")

# ============================================================
# QUICK ISSUES ENDPOINT
# ============================================================
@app.get("/api/quick-issues")
async def get_quick_issues():
    return {"issues": ConfigStore.get_quick_issues()}

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
# UI PAGES - COMPLETE WITH WELCOME
# ============================================================
@app.get("/")
async def home():
    brand = ConfigStore.get("brand_name", "Pocket Lawyer")
    issues = ConfigStore.get_quick_issues()
    issues_html = ""
    for issue in issues:
        issues_html += f"""
        <div class="issue-card" onclick="handleIssueClick('{issue.get('id')}', '{issue.get('title')}')">
            <div class="issue-icon">{issue.get('icon', '📄')}</div>
            <div class="issue-title">{issue.get('title')}</div>
        </div>
        """
    
    return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <title>{brand} - AI Legal Assistant</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
            background: #0f172a; 
            color: #e2e8f0; 
            min-height: 100vh;
        }}
        .header {{ 
            background: #1e293b; 
            padding: 20px 40px; 
            border-bottom: 1px solid #334155;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .header h1 {{ color: #60a5fa; font-size: 1.8rem; }}
        .header .subtitle {{ color: #94a3b8; font-size: 0.9rem; }}
        .btn {{ 
            padding: 10px 24px;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            transition: all 0.3s;
        }}
        .btn-primary {{ background: #3b82f6; color: white; }}
        .btn-primary:hover {{ background: #2563eb; transform: translateY(-2px); }}
        .btn-secondary {{ background: #334155; color: #e2e8f0; }}
        .btn-secondary:hover {{ background: #475569; transform: translateY(-2px); }}
        .btn-success {{ background: #10b981; color: white; }}
        .btn-success:hover {{ background: #059669; transform: translateY(-2px); }}
        
        .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
        
        .hero {{ 
            text-align: center; 
            padding: 40px 0 30px;
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border-radius: 16px;
            border: 1px solid #334155;
            margin-bottom: 32px;
        }}
        .hero h1 {{ font-size: 3rem; color: #60a5fa; margin-bottom: 12px; }}
        .hero p {{ font-size: 1.2rem; color: #94a3b8; max-width: 600px; margin: 0 auto 20px; }}
        .hero .badge {{ 
            display: inline-block;
            background: #10b98120;
            color: #10b981;
            padding: 4px 16px;
            border-radius: 20px;
            font-size: 0.8rem;
            border: 1px solid #10b98140;
            margin: 4px;
        }}
        .hero .btn-group {{ display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; margin-top: 20px; }}
        
        .features {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin: 32px 0; }}
        .feature {{ 
            background: #1e293b; 
            padding: 24px;
            border-radius: 12px;
            border: 1px solid #334155;
            text-align: center;
            transition: all 0.3s;
        }}
        .feature:hover {{ border-color: #60a5fa; transform: translateY(-4px); }}
        .feature .icon {{ font-size: 2.5rem; margin-bottom: 12px; }}
        .feature h3 {{ color: #60a5fa; margin-bottom: 8px; }}
        .feature p {{ color: #94a3b8; font-size: 0.9rem; }}
        
        .issues-section {{ margin: 32px 0; }}
        .issues-section h2 {{ color: #e2e8f0; margin-bottom: 16px; font-size: 1.5rem; }}
        .issues-grid {{ 
            display: grid; 
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 12px;
        }}
        .issue-card {{ 
            background: #1e293b;
            padding: 16px 20px;
            border-radius: 10px;
            border: 1px solid #334155;
            display: flex;
            align-items: center;
            gap: 12px;
            cursor: pointer;
            transition: all 0.3s;
        }}
        .issue-card:hover {{ 
            border-color: #60a5fa; 
            transform: translateX(4px);
            background: #253450;
        }}
        .issue-icon {{ font-size: 1.5rem; }}
        .issue-title {{ color: #e2e8f0; font-weight: 500; }}
        
        .upload-zone {{
            border: 2px dashed #334155;
            border-radius: 16px;
            padding: 40px;
            text-align: center;
            background: #1e293b;
            cursor: pointer;
            transition: all 0.3s;
            margin: 24px 0;
        }}
        .upload-zone:hover {{ border-color: #3b82f6; background: #253450; }}
        .upload-zone .icon {{ font-size: 3rem; }}
        .upload-zone input {{ display: none; }}
        
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; margin: 24px 0; }}
        .stat-card {{ background: #1e293b; padding: 20px; border-radius: 12px; border: 1px solid #334155; text-align: center; }}
        .stat-value {{ font-size: 2rem; font-weight: bold; color: #60a5fa; }}
        .stat-label {{ color: #94a3b8; font-size: 0.85rem; }}
        
        .footer {{ text-align: center; color: #64748b; font-size: 0.8rem; margin-top: 32px; padding-top: 16px; border-top: 1px solid #1e293b; }}
        
        .modal {{
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(15, 23, 42, 0.95);
            z-index: 1000;
            padding: 40px;
            overflow-y: auto;
        }}
        .modal.active {{ display: block; }}
        .modal-content {{
            max-width: 700px;
            margin: 0 auto;
            background: #1e293b;
            padding: 32px;
            border-radius: 16px;
            border: 1px solid #334155;
        }}
        .modal-content h2 {{ color: #60a5fa; margin-bottom: 16px; }}
        .modal-content .result {{ 
            background: #0f172a;
            padding: 16px;
            border-radius: 8px;
            max-height: 400px;
            overflow-y: auto;
            white-space: pre-wrap;
            font-family: monospace;
            font-size: 0.9rem;
            line-height: 1.6;
        }}
        .modal-actions {{ display: flex; gap: 12px; margin-top: 20px; justify-content: flex-end; }}
        
        @media (max-width: 768px) {{
            .header {{ flex-direction: column; text-align: center; padding: 16px; }}
            .hero h1 {{ font-size: 2rem; }}
            .features {{ grid-template-columns: 1fr; }}
            .issues-grid {{ grid-template-columns: 1fr; }}
            .modal {{ padding: 16px; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>⚖️ {brand}</h1>
            <div class="subtitle">AI Legal Assistant for Nigerian Law</div>
        </div>
        <div>
            <a href="/chat" class="btn btn-primary">💬 Chat</a>
            <a href="/admin" class="btn btn-secondary">⚙️ Admin</a>
        </div>
    </div>
    
    <div class="container">
        <!-- Hero Section -->
        <div class="hero">
            <h1>🇳🇬 Nigerian Law, Powered by AI</h1>
            <p>Get instant legal guidance, generate documents, and analyze contracts — all with AI.</p>
            <div>
                <span class="badge">📄 PDF Generation</span>
                <span class="badge">🔍 Document Analysis</span>
                <span class="badge">⚖️ Nigerian Law</span>
            </div>
            <div class="btn-group">
                <a href="/chat" class="btn btn-primary">💬 Start Chat</a>
                <a href="#upload" class="btn btn-success">📤 Upload PDF</a>
                <a href="/admin" class="btn btn-secondary">⚙️ Admin</a>
            </div>
        </div>
        
        <!-- Features -->
        <div class="features">
            <div class="feature">
                <div class="icon">📄</div>
                <h3>Generate PDFs</h3>
                <p>Create legal documents, contracts, and agreements</p>
            </div>
            <div class="feature">
                <div class="icon">🔍</div>
                <h3>Analyze Documents</h3>
                <p>Upload PDFs for AI-powered legal analysis</p>
            </div>
            <div class="feature">
                <div class="icon">💬</div>
                <h3>AI Chat</h3>
                <p>Ask legal questions and get instant answers</p>
            </div>
            <div class="feature">
                <div class="icon">⚖️</div>
                <h3>Nigerian Law</h3>
                <p>Specialized in Nigerian legal system</p>
            </div>
        </div>
        
        <!-- Quick Issues -->
        <div class="issues-section">
            <h2>📌 Common Nigerian Legal Issues</h2>
            <div class="issues-grid" id="issuesGrid">
                {issues_html}
            </div>
        </div>
        
        <!-- Upload Zone -->
        <div id="upload" class="upload-zone" onclick="document.getElementById('fileInput').click()">
            <div class="icon">📤</div>
            <h3>Upload PDF Document</h3>
            <p>Upload a PDF for AI analysis and review</p>
            <input type="file" id="fileInput" accept=".pdf" onchange="uploadPDF(this)">
            <div id="uploadStatus" style="margin-top:12px;color:#94a3b8;"></div>
        </div>
        
        <!-- Stats -->
        <div class="stats" id="stats">
            <div class="stat-card">
                <div class="stat-value" id="docCount">0</div>
                <div class="stat-label">Documents</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="uploadCount">0</div>
                <div class="stat-label">Uploaded PDFs</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="version">v{VERSION}</div>
                <div class="stat-label">Version</div>
            </div>
        </div>
        
        <div class="footer">
            <p>⚖️ {brand} v{VERSION} • Powered by AI • General guidance only</p>
            <p style="margin-top: 4px; color: #475569; font-size: 0.7rem;">
                ⚠️ For legal advice, consult a qualified lawyer.
            </p>
        </div>
    </div>
    
    <!-- Upload Status Modal -->
    <div id="uploadModal" class="modal">
        <div class="modal-content">
            <h2 id="modalTitle">📄 Document Analysis</h2>
            <div id="modalContent" class="result">Processing...</div>
            <div class="modal-actions">
                <button class="btn btn-secondary" onclick="closeModal('uploadModal')">Close</button>
            </div>
        </div>
    </div>
    
    <script>
        // ============================================================
        // QUICK ISSUES
        // ============================================================
        function handleIssueClick(issueId, issueTitle) {{
            const messages = {{
                'tenancy': "What are my rights as a tenant in Lagos?",
                'employment': "What are my rights as an employee in Nigeria?",
                'contract': "What makes a contract legally binding in Nigeria?",
                'family': "What are the laws on marriage and divorce in Nigeria?",
                'debt': "How can I recover a debt legally in Nigeria?",
                'criminal': "What are my rights if arrested in Nigeria?",
                'corporate': "What is CAMA 2020 and how does it affect my business?",
                'property': "What are the laws on property ownership in Nigeria?"
            }};
            const message = messages[issueId] || `Tell me about ${issueTitle}`;
            window.location.href = `/chat?q=${encodeURIComponent(message)}`;
        }}
        
        // ============================================================
        // PDF UPLOAD
        // ============================================================
        async function uploadPDF(input) {{
            if (!input.files || input.files.length === 0) return;
            
            const file = input.files[0];
            const formData = new FormData();
            formData.append('file', file);
            
            const status = document.getElementById('uploadStatus');
            status.textContent = '⏳ Uploading and processing...';
            status.style.color = '#fbbf24';
            
            try {{
                const res = await fetch('/api/documents/upload', {{
                    method: 'POST',
                    body: formData
                }});
                const data = await res.json();
                
                if (data.status === 'success') {{
                    status.textContent = `✅ Uploaded: ${data.filename} (${data.words} words)`;
                    status.style.color = '#10b981';
                    
                    // Show analysis modal
                    showAnalysis(data.document_id, data.filename);
                    updateStats();
                }} else {{
                    status.textContent = `❌ ${data.message}`;
                    status.style.color = '#ef4444';
                }}
            }} catch(e) {{
                status.textContent = `❌ Error: ${e.message}`;
                status.style.color = '#ef4444';
            }}
            
            input.value = '';
        }}
        
        async function showAnalysis(docId, filename) {{
            const modal = document.getElementById('uploadModal');
            const title = document.getElementById('modalTitle');
            const content = document.getElementById('modalContent');
            
            modal.classList.add('active');
            title.textContent = `📄 Analyzing: ${filename}`;
            content.textContent = '⏳ AI is analyzing your document...';
            
            try {{
                const res = await fetch('/api/documents/analyze', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{ document_id: docId }})
                }});
                const data = await res.json();
                
                if (data.status === 'success') {{
                    content.textContent = data.analysis;
                }} else {{
                    content.textContent = '❌ Analysis failed: ' + (data.message || 'Unknown error');
                }}
            }} catch(e) {{
                content.textContent = '❌ Error: ' + e.message;
            }}
        }}
        
        // ============================================================
        // STATS
        // ============================================================
        async function updateStats() {{
            try {{
                const res = await fetch('/api/documents/uploaded');
                const data = await res.json();
                if (data.status === 'success') {{
                    document.getElementById('uploadCount').textContent = data.documents.length;
                }}
            }} catch(e) {{
                console.error('Error updating stats:', e);
            }}
        }}
        
        // ============================================================
        // MODAL
        // ============================================================
        function closeModal(id) {{
            document.getElementById(id).classList.remove('active');
        }}
        
        document.querySelectorAll('.modal').forEach(modal => {{
            modal.addEventListener('click', function(e) {{
                if (e.target === this) {{
                    this.classList.remove('active');
                }}
            }});
        }});
        
        // ============================================================
        // LOAD
        // ============================================================
        document.addEventListener('DOMContentLoaded', function() {{
            updateStats();
            
            // Check if there's a query parameter for chat
            const urlParams = new URLSearchParams(window.location.search);
            const q = urlParams.get('q');
            if (q) {{
                window.location.href = `/chat?q=${encodeURIComponent(q)}`;
            }}
        }});
    </script>
</body>
</html>
""")

# ============================================================
# REST OF THE ADMIN PAGES (SAME AS BEFORE)
# ============================================================
# ... (Keep all the admin pages from previous version: /admin, /admin/ai, /admin/telegram, /admin/whatsapp, /admin/plans, /admin/config)
# ... and all the test endpoints and telegram polling

