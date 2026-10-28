# KnowFlow AI

KnowFlow AI is a company knowledge intelligence platform foundation. The planned product will use retrieval-augmented generation (RAG) to help teams find answers in their company knowledge.

This repository is a monorepo with independently runnable applications:

```text
knowflow-ai/
├── backend/       # FastAPI service
├── frontend/      # Next.js App Router application
├── .gitignore
└── README.md
```

## Architecture

- **Frontend:** Next.js, React, TypeScript, Tailwind CSS, and ESLint
- **Backend:** Python and FastAPI, served locally with Uvicorn
- **Planned AI and data components:** LangChain, Google Gemini, Sentence Transformers, ChromaDB, PostgreSQL, Pandas, and NumPy

The AI, ingestion, persistence, authentication, and analytics components are not part of this foundation yet.

## Prerequisites

- Node.js 20.9 or newer and npm
- Python 3.10 or newer

No API keys, database, or external services are required to run the foundation.

## Setup

### Frontend

In a terminal:

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The environment file is optional for the starter page.

### Backend

In a separate terminal:

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload
```

The backend listens at [http://localhost:8000](http://localhost:8000). Verify its health at [http://localhost:8000/health](http://localhost:8000/health), which returns `{"status":"ok"}`.

On macOS or Linux, create and activate the backend environment with:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --reload
```

## Frontend checks

Run these commands from `frontend/`:

```powershell
npm run lint
npm run build
```

## Environment configuration

`frontend/.env.example` and `backend/.env.example` contain placeholders only. Copy them as shown above if you need local environment files. Replace placeholders locally only when a later feature requires real credentials; never commit `.env` or `.env.local` files.
