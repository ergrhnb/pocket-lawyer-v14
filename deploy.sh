#!/bin/bash
# ============================================================
# POCKET LAWYER v14.0.1 - DEPLOYMENT SCRIPT
# ============================================================

echo "🚀 Starting Pocket Lawyer Deployment..."

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt

# Create directories
echo "📁 Creating directories..."
mkdir -p logs data documents uploads static templates

# Check Python version
echo "🐍 Python version: $(python --version)"

# Set environment variables
export PYTHONPATH="${PYTHONPATH}:${PWD}"

# Start the application
echo "🚀 Starting Pocket Lawyer..."
uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}
