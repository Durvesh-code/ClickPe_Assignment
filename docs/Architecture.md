# The Loan Eligibility Engine — Complete Architecture

> **Stack**: Python 3.11 · AWS S3 · AWS Lambda · AWS API Gateway · AWS RDS (PostgreSQL 16) · AWS SES · Self-Hosted n8n (Docker) · OpenAI `gpt-4o-mini`

---

## 1. High-Level System Diagram

```mermaid
flowchart TD
    subgraph BROWSER["Browser - localhost"]
        UI["index.html\nVanilla HTML / JS / CSS"]
    end

    subgraph AWS["AWS Cloud Tier"]
        APIGW["API Gateway\nHTTP API"]
        LU["Lambda: get_upload_url\nPython 3.11"]
        S3[("S3 Bucket\nloan-engine-uploads")]
        LI["Lambda: ingest_users\nPython 3.11 + pg8000"]
        RDS[("AWS RDS\nPostgreSQL 16\ndb.t3.micro")]
        SES["AWS SES\nap-south-1"]
    end

    subgraph DOCKER["Docker Local Tier"]
        subgraph N8N["Self-Hosted n8n - localhost:5678"]
            WFA["Workflow A\nLoan Discovery\nDaily Cron"]
            WFB["Workflow B\nUser-Loan Matching\nWebhook Trigger"]
            WFC["Workflow C\nEmail Notification\nExecute Workflow"]
        end
    end

    OPENAI["OpenAI API\ngpt-4o-mini"]
    INBOX["Gmail Test Inbox\nyourname+1@gmail.com"]

    UI -- "1. GET /upload-url" --> APIGW
    APIGW --> LU
    LU -- "2. Pre-signed PUT URL" --> UI
    UI -- "3. Direct PUT users.csv" --> S3
    S3 -- "4. s3:ObjectCreated" --> LI
    LI -- "5a. Batch UPSERT 500 rows/chunk" --> RDS
    UI -- "5b. POST webhook after 5s" --> WFB
    WFA -- "Crawl and UPSERT loan_products" --> RDS
    WFB -- "Stage 1: Indexed SQL JOIN" --> RDS
    RDS -- "Filtered candidates" --> WFB
    WFB -- "Stage 3: Underwriting check" --> OPENAI
    OPENAI -- "ai_reasoning" --> WFB
    WFB -- "INSERT INTO matches" --> RDS
    WFB -- "Execute Workflow" --> WFC
    WFC -- "SELECT notified=FALSE" --> RDS
    WFC -- "UPDATE notified=TRUE" --> RDS
    WFC -- "Send HTML email" --> SES
    SES --> INBOX

    classDef aws fill:#FF9900,stroke:#232F3E,color:#000
    classDef docker fill:#0DB7ED,stroke:#384D54,color:#000
    classDef browser fill:#4285F4,stroke:#1A73E8,color:#fff
    classDef external fill:#10A37F,stroke:#0D7A5F,color:#fff
    classDef inbox fill:#EA4335,stroke:#C5221F,color:#fff

    class APIGW,LU,S3,LI,RDS,SES aws
    class WFA,WFB,WFC docker
    class UI browser
    class OPENAI external
    class INBOX inbox
```

---

## 2. Component Breakdown

| # | Component | Where It Runs | Technology | Architectural Purpose |
|---|---|---|---|---|
| 1 | **Web UI** | Localhost (browser) | HTML5 · JS · Vanilla CSS | Requests pre-signed URL, uploads CSV directly to S3, then fires `localhost:5678` webhook after 5s buffer |
| 2 | **Pre-Signed URL API** | AWS Cloud | API Gateway (HTTP API) + Lambda `get_upload_url` | Issues short-lived (300s) S3 PUT URLs — AWS credentials never touch the browser |
| 3 | **File Storage** | AWS Cloud | AWS S3 `loan-engine-uploads` | Decouples file upload from compute; bypasses API Gateway's 10 MB payload limit and 29s timeout |
| 4 | **CSV Ingestion Worker** | AWS Cloud | AWS Lambda `ingest_users` (Python 3.11 + `pg8000`) | Triggered asynchronously by `s3:ObjectCreated`; bulk-upserts 10,001 rows in 500-row chunks in < 2s |
| 5 | **Relational Database** | AWS Cloud | AWS RDS PostgreSQL 16 (`db.t3.micro`, Public Endpoint) | Single shared DB reachable by both AWS Lambda and local Docker n8n via one `DATABASE_URL` — no tunnels |
| 6 | **Workflow Engine** | Docker Local | Self-Hosted n8n (`docker-compose.yml`) | Orchestrates all three workflows visually; mandatory per assignment |
| 7 | **AI Reasoning Layer** | Cloud API | OpenAI `gpt-4o-mini` | Called only after Stage 1+2 filtering removes 99%+ of pairs — cost near $0 |
| 8 | **Email Dispatcher** | AWS Cloud | AWS SES (`ap-south-1`) | Delivers personalized HTML loan offer emails to verified Gmail `+alias` test inboxes |

---

## 3. Database Schema

```mermaid
erDiagram
    users {
        UUID user_id PK
        VARCHAR name
        VARCHAR email
        INTEGER monthly_income
        INTEGER credit_score
        VARCHAR employment_status
        INTEGER age
        TIMESTAMPTZ created_at
        TIMESTAMPTZ updated_at
    }

    loan_products {
        SERIAL product_id PK
        VARCHAR product_name UK
        VARCHAR provider_name
        TEXT source_url
        NUMERIC interest_rate
        INTEGER min_monthly_income
        INTEGER min_credit_score
        INTEGER max_credit_score
        VARCHAR allowed_employment_status
        INTEGER min_age
        INTEGER max_age
        TEXT special_criteria
        TIMESTAMPTZ updated_at
    }

    matches {
        SERIAL match_id PK
        UUID user_id FK
        INTEGER product_id FK
        TEXT ai_reasoning
        BOOLEAN notified
        TIMESTAMPTZ matched_at
    }

    users ||--o{ matches : "is matched to"
    loan_products ||--o{ matches : "is matched in"
```

> **Index**: `idx_users_eligibility` — Composite B-Tree on `(employment_status, monthly_income, credit_score, age)` — enables Stage 1 SQL JOIN to complete in ~15ms across 10,001 rows.

---

## 4. The Optimization Treasure Hunt — 3-Stage Filtering Pipeline

> **Problem**: 10,001 users × 5+ loan products = 50,000+ pairs. Sending 50,000 LLM prompts costs ~$50/run and fails on rate limits.

```mermaid
flowchart TD
    START(["10,001 Users x N Loan Products = 50,000 pairs"])

    subgraph S1["Stage 1 - Indexed SQL Pushdown - 15ms"]
        S1A["Composite B-Tree Index\nidx_users_eligibility"]
        S1B["INNER JOIN filters:\nmonthly_income, credit_score,\nage, employment_status"]
        S1C["DISTINCT ON user_id\nORDER BY interest_rate ASC\nSkip existing matches"]
        S1A --> S1B --> S1C
    end

    subgraph S2["Stage 2 - Deterministic Rank in Code Node - under 5ms"]
        S2A["Compute eligibility score\nfrom credit buffer above minimum"]
        S2B["Keep top-scored match per user"]
        S2C["Hard cap batch size\nto protect OpenAI rate limits"]
        S2A --> S2B --> S2C
    end

    subgraph S3["Stage 3 - Targeted OpenAI gpt-4o-mini - cost approx $0.001"]
        S3A["Evaluate special_criteria\nqualitative checks only"]
        S3B["Generate 1-sentence\npersonalized underwriting note"]
        S3C["Store result in\nmatches.ai_reasoning"]
        S3A --> S3B --> S3C
    end

    RESULT(["Final matches saved\nWorkflow C triggered"])

    START --> S1
    S1 -- "~500 pairs - 99% eliminated" --> S2
    S2 -- "~50 pairs - 90% eliminated" --> S3
    S3 --> RESULT

    classDef stage1 fill:#146EB4,stroke:#0D4F80,color:#fff
    classDef stage2 fill:#2E7D32,stroke:#1B5E20,color:#fff
    classDef stage3 fill:#E65100,stroke:#BF360C,color:#fff
    classDef endpoint fill:#37474F,stroke:#263238,color:#fff

    class S1A,S1B,S1C stage1
    class S2A,S2B,S2C stage2
    class S3A,S3B,S3C stage3
    class START,RESULT endpoint
```

---

## 5. End-to-End Request Flow (Step by Step)

```
STEP 1   Browser opens index.html
         --> GET {API_GATEWAY_URL}/upload-url
             --> Lambda (get_upload_url) generates a 300s pre-signed S3 PUT URL
                 --> Returns pre-signed URL to browser

STEP 2   Browser PUTs users.csv directly to S3
         (Bypasses Lambda entirely -- no 10 MB limit, no 29s timeout)

STEP 3   S3 fires s3:ObjectCreated event
         --> Lambda (ingest_users) wakes up asynchronously
             --> urllib.parse.unquote_plus() decodes S3 key (handles special chars)
                 --> Each row validated in try/except (bad rows skipped, not failed)
                     --> pg8000 batch UPSERT in 500-row chunks
                         --> ON CONFLICT (user_id) DO UPDATE (idempotent re-uploads)

STEP 4   Browser waits 5 seconds (ingestion buffer)
         --> POST http://localhost:5678/webhook/ingest-complete
             (Works because browser and Docker n8n are both on localhost -- no ngrok)

STEP 5   n8n Workflow B: 3-Stage Matching Pipeline
         --> Stage 1: SQL JOIN in RDS (~15ms, B-Tree index)
             --> Stage 2: Code Node rank & cap (<5ms)
                 --> Stage 3: OpenAI gpt-4o-mini (targeted batch only)
                     --> INSERT into matches (ON CONFLICT DO NOTHING -- idempotent)
                         --> Execute Workflow Node fires Workflow C directly

STEP 6   n8n Workflow C: Notification Engine
         --> SELECT WHERE notified = FALSE LIMIT 5
             --> Rewrite @example.com --> yourname+userN@gmail.com
                 --> AWS SES sends personalized HTML email (throttled 1/sec)
                     --> UPDATE matches SET notified = TRUE (crash-safe & idempotent)
```

---

## 6. Key Engineering Decisions (Whiteboard Defense)

| Decision | Why |
|---|---|
| **S3 Pre-Signed URL instead of API Gateway POST** | API Gateway has a hard 10 MB payload limit and 29s timeout. Pre-signed URL streams the file directly to S3 and scales to any file size. |
| **`pg8000` instead of `psycopg2`** | `psycopg2-binary` uses compiled C extensions (`libpq.so`) that crash on AWS Lambda Linux when packaged from Windows/macOS. `pg8000` is 100% pure Python — zero binary issues. |
| **AWS RDS instead of Local Docker Postgres** | AWS Lambda runs in Amazon's data center and cannot reach `localhost:5432` on a laptop behind NAT. RDS provides a public endpoint reachable by both Lambda (cloud) and n8n (local Docker) via a single `DATABASE_URL`. |
| **Browser fires `localhost:5678` webhook (no ngrok)** | Free ngrok rotates URLs on every restart and injects HTML warning screens that break automated POSTs. Since both the browser and Docker n8n run on the same machine, `localhost:5678` always works. |
| **3-Stage SQL → Code Node → OpenAI pipeline** | Calling LLM on all 50,000 pairs costs ~$50 and fails on rate limits. SQL indexing eliminates ~99% in 15ms. OpenAI only called on the small filtered batch — cost drops to ~$0.001. |
| **`ON CONFLICT DO NOTHING` in matches** | Guarantees idempotency. Re-running Workflow B after failure never creates duplicate matches or sends duplicate emails. |
| **`notified = FALSE` flag in matches** | Database-backed state means Workflow C can crash mid-run and safely resume — queries unfulfilled records and marks done after confirmed SES delivery. |
| **`+alias` email rewriting** | PDF explicitly forbids emailing `@example.com` addresses. AWS SES automatically trusts all `+alias` variants of a verified base Gmail — no extra verification needed. |

---

## 7. Infrastructure Files Reference

| File | Purpose |
|---|---|
| `serverless.yml` | Deploys API Gateway, both Lambda functions, S3 bucket with CORS, and IAM roles |
| `handler.py` | Python Lambda functions — pre-signed URL generator and CSV ingestion worker |
| `schema.sql` | PostgreSQL DDL — creates all 3 tables, B-Tree index, and seeds initial loan products |
| `docker-compose.yml` | Runs self-hosted n8n with `N8N_CORS_ALLOW_ORIGIN=*` |
| `.env.example` | Template for all required environment variables |
| `workflow_a_crawler.json` | n8n Workflow A export — daily cron loan product crawler |
| `workflow_b_matching.json` | n8n Workflow B export — 3-stage matching pipeline |
| `workflow_c_notification.json` | n8n Workflow C export — SES email dispatcher |
| `index.html` | Minimal upload UI — Vanilla HTML5 / JS / CSS |

---

## 8. Environment Variables Reference

| Variable | Used By | Example |
|---|---|---|
| `DATABASE_URL` | Lambda + n8n | `postgresql://user:pass@your-db.rds.amazonaws.com:5432/loandb` |
| `S3_BUCKET_NAME` | Lambda | `loan-engine-uploads` |
| `AWS_REGION` | Lambda + n8n SES node | `ap-south-1` |
| `OPENAI_API_KEY` | n8n Workflow B | `sk-...` |
| `TEST_GMAIL_BASE` | n8n Workflow C | `yourname@gmail.com` |
| `N8N_WEBHOOK_URL` | n8n (docker-compose) | `http://localhost:5678` |
| `N8N_CORS_ALLOW_ORIGIN` | n8n (docker-compose) | `*` |
