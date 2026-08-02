# ============================================================
# RENDER DEPLOYMENT CHECKLIST
# ============================================================

## STEP 1: Create Web Service
1. Go to https://dashboard.render.com
2. Click "New +" → "Web Service"
3. Connect to GitHub: ergrhnb/pocket-lawyer-v14

## STEP 2: Configure Service
- **Name**: pocket-lawyer-v14
- **Environment**: Python 3 (Python 3.10)
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
- **Plan**: Free

## STEP 3: Add Environment Variables
- GROQ_API_KEY = your_groq_key
- SAMBANOVA_API_KEY = your_sambanova_key
- MISTRAL_API_KEY = your_mistral_key
- OPENROUTER_API_KEY = your_openrouter_key
- TELEGRAM_BOT_TOKEN = your_telegram_token
- PYTHON_VERSION = 3.10.0

## STEP 4: Deploy
1. Click "Create Web Service"
2. Wait for deployment (~3-5 minutes)
3. Check logs for any errors

## STEP 5: Verify
- [ ] Home page loads: https://pocket-lawyer-v14.onrender.com
- [ ] Chat works: https://pocket-lawyer-v14.onrender.com/chat
- [ ] Admin works: https://pocket-lawyer-v14.onrender.com/admin
- [ ] Health check: https://pocket-lawyer-v14.onrender.com/api/health

## STEP 6: Test Telegram
1. Open Telegram
2. Search: @Mypocket_lawyerbot
3. Send: "Hello"
4. Send: "Generate a tenancy agreement PDF"

## STEP 7: Test WhatsApp (Optional)
1. Go to Admin → WhatsApp
2. Add Phone Number ID and Access Token
3. Enable WhatsApp
4. Test with a message
