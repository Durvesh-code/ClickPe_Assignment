-- 1. USERS TABLE (Stores the 10,000 users from users.csv)
CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    monthly_income INTEGER NOT NULL CHECK (monthly_income >= 0),
    credit_score INTEGER NOT NULL CHECK (credit_score BETWEEN 300 AND 900),
    employment_status VARCHAR(50) NOT NULL,
    age INTEGER NOT NULL CHECK (age >= 18 AND age <= 100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Fast B-Tree Index for Stage 1 SQL Filtering (~15ms across 10,000 rows)
CREATE INDEX IF NOT EXISTS idx_users_eligibility
ON users (employment_status, monthly_income, credit_score, age);

-- 2. LOAN PRODUCTS TABLE (Stores loan offers crawled by Workflow A)
CREATE TABLE IF NOT EXISTS loan_products (
    product_id SERIAL PRIMARY KEY,
    product_name VARCHAR(255) UNIQUE NOT NULL,
    provider_name VARCHAR(255) NOT NULL,
    source_url TEXT NOT NULL,
    interest_rate NUMERIC(5, 2) NOT NULL,
    min_monthly_income INTEGER NOT NULL,
    min_credit_score INTEGER NOT NULL,
    max_credit_score INTEGER DEFAULT 900,
    allowed_employment_status VARCHAR(100) NOT NULL,
    min_age INTEGER NOT NULL DEFAULT 21,
    max_age INTEGER NOT NULL DEFAULT 60,
    special_criteria TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. MATCHES TABLE (Stores matched User <-> Loan pairs from Workflow B)
CREATE TABLE IF NOT EXISTS matches (
    match_id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES loan_products(product_id) ON DELETE CASCADE,
    match_score INTEGER DEFAULT 100,
    ai_reasoning TEXT,
    notified BOOLEAN DEFAULT FALSE,
    notified_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_matches_unnotified
ON matches (notified) WHERE notified = FALSE;

-- Seed 5 initial loan products so you can test matching immediately
INSERT INTO loan_products (
    product_name, provider_name, source_url, interest_rate,
    min_monthly_income, min_credit_score, max_credit_score,
    allowed_employment_status, min_age, max_age, special_criteria
) VALUES
('HDFC Xpress Personal Loan', 'HDFC Bank', 'https://www.hdfcbank.com/personal/borrow/popular-loans/personal-loan', 10.75, 35000, 720, 900, 'Salaried', 21, 60, 'Salaried applicants with monthly income >= 35,000 and credit score >= 720.'),
('ICICI Instant Flexi Cash Loan', 'ICICI Bank', 'https://www.icicibank.com/personal-banking/loans/personal-loan', 10.85, 30000, 700, 900, 'Salaried', 23, 58, 'Salaried employment and credit score >= 700.'),
('Bajaj Finserv Business & Self-Employed Loan', 'Bajaj Finserv', 'https://www.bajajfinserv.in/personal-loan', 11.50, 45000, 685, 900, 'Self-Employed', 24, 65, 'Self-employed professionals with monthly income >= 45,000.'),
('Axis Bank Prime Personal Loan', 'Axis Bank', 'https://www.axisbank.com/retail/loans/personal-loan', 10.49, 60000, 750, 900, 'Salaried', 21, 60, 'High-income salaried earners (>= 60,000) with prime credit (>= 750).'),
('Kotak Mahindra MSME & Business Growth Loan', 'Kotak Mahindra Bank', 'https://www.kotak.com/en/personal-banking/loans/personal-loan.html', 12.25, 50000, 680, 900, 'Business', 25, 65, 'Business owners with monthly income >= 50,000.')
ON CONFLICT (product_name) DO UPDATE SET
    interest_rate = EXCLUDED.interest_rate,
    updated_at = CURRENT_TIMESTAMP;