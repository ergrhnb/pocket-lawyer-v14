# Pocket Lawyer v14.0 - Render Deployment Guide

## Deploy on Render

1. Go to: https://dashboard.render.com
2. Click "New +" → "Web Service"
3. Connect your GitHub repository
4. Render auto-detects settings
5. Click "Create Web Service"

## Environment Variables
Add these in Render Dashboard:

| Key | Value |
|-----|-------|
| SECRET_KEY | (auto-generated) |
| TELEGRAM_BOT_TOKEN | 8875705717:AAEsq786bJYypamBCokHlMvOJAVjKTPb82I |
| TELEGRAM_ENABLED | true |
| PDF_GENERATION | true |
| DEBUG | false |

## Your App
https://pocket-lawyer-v14.onrender.com
