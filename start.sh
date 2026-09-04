#!/bin/bash
set -e

echo "⚡ AI Payment Guardian — Revenue Recovery"
echo "   Razorpay AI Buildathon 2026 — Track 03"
echo ""

# Check .env exists
if [ ! -f backend/.env ]; then
  if [ -f .env.example ]; then
    cp .env.example backend/.env
    echo "⚠️  Created backend/.env from .env.example"
    echo "   → Add your GROQ_API_KEY to backend/.env before continuing"
    echo ""
    echo "   Get a free key at: https://console.groq.com"
    exit 1
  else
    echo "❌ No backend/.env found. Create it with GROQ_API_KEY=your_key"
    exit 1
  fi
fi

# Check GROQ_API_KEY is set
if ! grep -q "GROQ_API_KEY=gsk_" backend/.env 2>/dev/null; then
  echo "⚠️  GROQ_API_KEY looks unset in backend/.env"
  echo "   AI agent queries will fail without it."
  echo ""
fi

# Create virtual environment if needed
if [ ! -d "backend/.venv" ]; then
  echo "📦 Creating Python virtual environment..."
  python3 -m venv backend/.venv
  echo "✅ Virtual environment created"
fi

echo "📦 Installing dependencies..."
backend/.venv/bin/pip install -q -r backend/requirements.txt
echo "✅ Dependencies ready"

echo ""
echo "🚀 Starting server on http://localhost:8000"
echo "🌐 Open frontend/index.html in your browser"
echo ""
echo "   Swagger docs: http://localhost:8000/docs"
echo "   Health check: http://localhost:8000/api/health"
echo ""
echo "Press Ctrl+C to stop."
echo ""

cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
