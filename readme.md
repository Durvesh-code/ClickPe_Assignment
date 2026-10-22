# ClickPe — The Loan Eligibility Engine

An event-driven, cloud-native personal loan discovery, eligibility matching, and automated notification system built with **Python 3.11**, **AWS Serverless (API Gateway, S3, Lambda, RDS)**, **Self-Hosted n8n (Docker)**, and **OpenAI (`gpt-4o-mini`)**.

---

## 🏛️ System Architecture

```
BROWSER (templates/index.html — ClickPe UI)
  │
  ├── 1. Request S3 Pre-Signed PUT URL ─────────► AWS API Gateway (HTTP API)
  │                                                  └── Lambda: get_upload_url
  │
  ├── 2. Direct S3 PUT Stream (data/users.csv) ──► AWS S3 Bucket
  │      (Bypasses API Gateway 10MB limit & 29s timeout)
  │
  └── 4. 8-second Ingestion Buffer ──────────────► Local Docker n8n (:5678)
         (Simple POST /webhook/ingest-complete)      └── Workflow B (Matching Engine)
                                                         └── Workflow C (Notification)

AWS S3 (loan-engine-uploads)
  └── 3. s3:ObjectCreated Event ────────────────► AWS Lambda: ingest_users (pg8000)
                                                     └── Multi-Row Batch UPSERT (500 rows/chunk)
                                                         └── AWS RDS (PostgreSQL 16)
```

---

## 📂 Project Repository Structure (MVP Layout)

```
ClickPe_Assignment/
├── .env.example                   # Template for AWS, RDS, OpenAI, and n8n environment variables
├── .gitignore                     # Protects AWS credentials, node_modules, and local volumes
├── docker-compose.yml             # 1-click self-hosted n8n container with CORS & volume persistence
├── handler.py                     # AWS Lambda functions (get_upload_url, ingest_users)
├── package.json                   # Serverless Framework configuration & plugins
├── README.md                      # Project documentation and quickstart guide
├── requirements.txt               # Lambda Python dependencies (pg8000)
├── serverless.yml                 # Infrastructure as Code (API Gateway, S3, Lambda IAM)
│
├── data/
│   └── users.csv                  # 10,001 candidate borrower dataset
│
├── database/
│   └── schema.sql                 # PostgreSQL DDL (users, loan_products, matches + index)
│
├── docs/
│   ├── Architecture.md            # In-depth system architecture & whiteboard defense
│   └── The Loan Eligibility Engine (Engineering Intern).pdf # Assignment mission & specs
│
├── n8n/
│   ├── workflow_a_crawler.json    # Workflow A: Loan Discovery Daily Crawler
│   ├── workflow_b_matching.json   # Workflow B: 3-Stage Optimization Matching Pipeline
│   └── workflow_c_notification.json # Workflow C: Email Notification Engine
│
└── templates/
    ├── index.html                 # ClickPe portal with client-side dataset insights
    └── index.css                  # ClickPe design system (Porcelain & Mint Aurora)
```

---

## 🚀 Quickstart Guide

### 1. Database Setup (AWS RDS PostgreSQL)
Run the initialization script from the repository root:
```powershell
python -c "import ssl, pg8000.native; ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE; conn=pg8000.native.Connection(user='postgres', password='YOUR_PASSWORD', host='loan-db.c016wigc2ubu.us-east-1.rds.amazonaws.com', port=5432, database='postgres', ssl_context=ctx); conn.run(open('database/schema.sql').read()); print('Tables created successfully!')"
```

### 2. Deploy AWS Cloud Infrastructure
```powershell
npm install
npx serverless deploy --region us-east-1
```

### 3. Launch Self-Hosted n8n
```powershell
docker compose up -d
```
Access n8n in your browser at `http://localhost:5678` and import the three workflows from the `n8n/` directory.

### 4. Open Ingestion Portal
Open `templates/index.html` in your browser, select `data/users.csv`, and click **Stream to S3 & Trigger Ingestion**.

---

## 🏆 Key Architectural Highlights

1. **Direct S3 Streaming**: Browser streams 10,000+ CSV rows directly to S3 via pre-signed URLs, bypassing API Gateway's 10 MB payload limit and 29s timeout.
2. **High-Throughput Ingestion**: AWS Lambda uses pure-Python `pg8000` with 500-row batch UPSERTs (`ON CONFLICT DO UPDATE`), committing 10,001 records into AWS RDS in under 2 seconds.
3. **3-Stage Matching Optimization**:
   * **Stage 1 (SQL Pushdown)**: Composite B-Tree index filters 50,000+ candidate pairs down to eligible matches in ~15ms.
   * **Stage 2 (Deterministic Scoring)**: Code node ranks applicants and caps batch sizes.
   * **Stage 3 (Targeted AI)**: OpenAI `gpt-4o-mini` evaluates qualitative underwriting criteria on top candidates only, reducing LLM costs by >99%.
4. **Idempotency & Resilience**: All operations support safe re-execution without duplicate matches or emails.