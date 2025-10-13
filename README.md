# LawYaar 🏛️⚖️

LawYaar is a voice-based legal chatbot on WhatsApp that helps Pakistanis get verified legal guidance — from inheritance to tenancy — using real federal and provincial laws, plus relevant court judgments.

Unlike static legal databases, LawYaar uses a RAG (Retrieval-Augmented Generation) system that pulls from real case law and judicial interpretations for practical, reliable answers.

**Built for everyone**: WhatsApp makes it accessible even in remote areas — legal help is just a message away.

**Accurate retrieval**: Multi-layer filtering ensures fact-based, citation-backed responses with official judgment links.

## Overview

LawYaar is an AI-powered legal research system that indexes legal documents (court cases, judgments) and provides contextual answers to legal queries. It uses vector embeddings and semantic search to retrieve relevant legal precedents and generate comprehensive research responses.

## Features

- **Document Ingestion**: Automatically processes and indexes legal documents from text files
- **Semantic Search**: Vector-based search using ChromaDB for relevant case retrieval
- **AI-Powered Research**: Generates comprehensive legal research using LLMs (OpenAI/Google Gemini)
- **REST API**: FastAPI backend with WebSocket support for real-time updates
- **WhatsApp Integration**: Query legal cases directly through WhatsApp
- **Docker Support**: Containerized deployment with Docker Compose
- **Progress Tracking**: Real-time progress updates during document processing

## Tech Stack

- **Backend**: FastAPI, Python
- **Vector Database**: ChromaDB
- **Embeddings**: Sentence Transformers
- **LLM Integration**: OpenAI API, Google Generative AI
- **Workflow**: PocketFlow for node-based processing
- **Deployment**: Docker

## Project Structure

```
LawYaar/
├── src/
│   ├── main.py                      # CLI entry point
│   ├── fastapi_server.py            # FastAPI REST API server
│   ├── flow.py                      # Workflow definitions
│   ├── nodes.py                     # Processing nodes
│   ├── nodes_agents.py              # LLM agent nodes
│   ├── whatsapp_legal_service.py    # WhatsApp integration
│   ├── config.py                    # Configuration management
│   ├── assets/
│   │   └── data/                    # Legal documents (case files)
│   ├── utils/
│   │   ├── vector_db.py             # Vector database operations
│   │   ├── call_llm.py              # LLM interaction
│   │   ├── chunking.py              # Document chunking
│   │   ├── embedding.py             # Text embeddings
│   │   └── file_processor.py        # File processing utilities
│   └── external/
│       └── whatsappbot/             # WhatsApp bot integration
├── chroma_db/                       # ChromaDB storage
├── docker-compose.yml               # Docker orchestration
├── Dockerfile                       # Container definition
└── requirements.txt                 # Python dependencies
```

## Installation

### Prerequisites

- Python 3.8+
- Docker & Docker Compose (optional, for containerized deployment)
- OpenAI API key or Google Gemini API key

### Local Setup

1. **Clone the repository**

   ```bash
   git clone https://github.com/zeeshanhxider/LawYaar.git
   cd LawYaar
   ```

2. **Create virtual environment**

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**

   Create a `.env` file in the project root:

   ```env
   # LLM Configuration
   OPENAI_API_KEY=your_openai_api_key_here
   # OR
   GOOGLE_API_KEY=your_google_api_key_here

   # Optional: Vector DB Configuration
   CHROMA_PERSIST_DIRECTORY=./chroma_db
   ```

5. **Add legal documents**

   Place your legal document text files in `src/assets/data/`

## Usage

### 1. Index Legal Documents (Offline)

First, build the vector database from your legal documents:

```bash
python src/main.py
```

This will:

- Process all documents in `src/assets/data/`
- Generate embeddings
- Store vectors in ChromaDB
- Cache results for future runs

### 2. Run the API Server

Start the FastAPI server:

```bash
uvicorn src.fastapi_server:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

### 3. API Endpoints

**Health Check**

```http
GET /
```

**Initialize Session**

```http
POST /api/initialize
```

**Query Legal Research**

```http
POST /api/query
Content-Type: application/json

{
  "session_id": "your-session-id",
  "user_query": "What are the legal precedents for contract disputes?",
  "max_results": 10
}
```

**WebSocket for Real-time Updates**

```javascript
ws://localhost:8000/ws/{session_id}
```

### Docker Deployment

Run the entire application with Docker Compose:

```bash
docker-compose up -d
```

This will:

- Build the Docker image
- Start the FastAPI server on port 8000
- Mount volumes for persistent data
- Set up health checks

## Configuration

Edit `src/config.py` to customize:

- LLM model selection (OpenAI GPT-4, Google Gemini, etc.)
- Vector database settings
- Embedding model configuration
- Chunk size and overlap
- Temperature and token limits

### Code Structure

- **Flow-based Processing**: Uses PocketFlow for modular node-based workflows
- **Offline Flow**: Document ingestion → Chunking → Embedding → Vector storage
- **Online Flow**: Query → Retrieval → LLM processing → Response composition
- **Agent Nodes**: Specialized LLM agents for document analysis and response generation

**Note**: This system is designed for legal research assistance. Always verify legal information with qualified legal professionals before making legal decisions.

---

### made with 🧡💚 by zeeshan and [bilal](https://github.com/Bilal-Ahmad6)
