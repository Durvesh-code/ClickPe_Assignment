# ClickPe — The Loan Eligibility Engine

An event-driven, cloud-native personal loan discovery, eligibility matching, and automated notification system built with **Python 3.11**, **AWS Serverless (API Gateway, S3, Lambda, RDS)**, **Self-Hosted n8n (Docker)**, and **OpenAI (`gpt-4o-mini`)**.

---

## 🏛️ System Architecture

```
BROWSER (index.html — ClickPe UI)
  │
  ├── 1. Request S3 Pre-Signed PUT URL ─────────► AWS API Gateway (HTTP API)
  │                                                  └── Lambda: get_upload_url
  │
  ├── 2. Direct S3 PUT Stream (users.csv: 10,001 rows) ──► AWS S3 Bucket
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

## 📂 Project Structure

```
├── .gitignore                     # Protects AWS credentials, node_modules, local volumes
├── Architecture.md                # Complete system architecture documentation
├── handler.py                     # AWS Lambda functions (get_upload_url, ingest_users)
├── serverless.yml                 # Infrastructure as Code (API Gateway, S3, Lambda)
├── schema.sql                     # PostgreSQL schema (users, loan_products, matches)
├── users.csv                      # 10,001 candidate borrower dataset
├── requirements.txt               # Pure Python dependencies (pg8000)
├── package.json                   # Serverless Framework configuration
├── templates/
│   ├── index.html                 # ClickPe portal with client-side dataset insights
│   └── index.css                  # ClickPe design system (Porcelain & Mint Aurora)
└── n8n/
    ├── workflow_a_crawler.json    # Workflow A: Loan Discovery Daily Crawler
    ├── workflow_b_matching.json   # Workflow B: 3-Stage Optimization Matching Pipeline
    └── workflow_c_notification.json # Workflow C: Email Notification Engine
```

---

## 🚀 Key Architectural Highlights

1. **Direct S3 Streaming**: Browser uploads 10,000+ CSV rows directly to S3 via pre-signed URLs, bypassing API Gateway payload limits.
2. **High-Throughput Ingestion**: AWS Lambda uses pure-Python `pg8000` with 500-row batch UPSERTs (`ON CONFLICT DO UPDATE`), committing 10,001 records into AWS RDS in under 2 seconds.
3. **3-Stage Matching Optimization**:
   * **Stage 1 (SQL Pushdown)**: Composite B-Tree index filters 50,000+ candidate pairs down to eligible matches in ~15ms.
   * **Stage 2 (Deterministic Scoring)**: Code node ranks applicants and caps batch sizes.
   * **Stage 3 (Targeted AI)**: OpenAI `gpt-4o-mini` evaluates qualitative underwriting criteria on top candidates only, reducing LLM costs by >99%.
4. **Idempotency & Resilience**: All operations support safe re-execution without duplicate matches or emails.