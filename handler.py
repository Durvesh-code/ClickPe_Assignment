import csv
import io
import json
import logging
import os
import ssl
import time
import urllib.parse
import urllib.request
import uuid
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client("s3")


def parse_database_url(db_url: str) -> dict:
    parsed = urllib.parse.urlparse(db_url)
    hostname = parsed.hostname or "localhost"
    query = parsed.query or ""

    use_ssl = (
        "sslmode=require" in query
        or "rds.amazonaws.com" in hostname
        or hostname != "localhost"
    )
    ssl_context = None
    if use_ssl:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    return {
        "user": urllib.parse.unquote(parsed.username or "postgres"),
        "password": urllib.parse.unquote(parsed.password or ""),
        "host": hostname,
        "port": parsed.port or 5432,
        "database": (parsed.path or "/postgres").lstrip("/"),
        "ssl_context": ssl_context,
    }


def get_upload_url(event, context):
    bucket_name = os.environ.get("UPLOAD_BUCKET")
    query_params = event.get("queryStringParameters") or {}
    filename = query_params.get("filename", "users.csv")

    safe_name = os.path.basename(filename).replace(" ", "_")
    object_key = f"uploads/{int(time.time())}-{uuid.uuid4().hex[:8]}-{safe_name}"

    try:
        presigned_url = s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": bucket_name,
                "Key": object_key,
                "ContentType": "text/csv",
            },
            ExpiresIn=300,
        )

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(
                {
                    "uploadUrl": presigned_url,
                    "objectKey": object_key,
                    "expiresIn": 300,
                }
            ),
        }
    except Exception as exc:
        logger.error(f"Failed to generate pre-signed URL: {exc}")
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": str(exc)}),
        }


def ingest_users(event, context):
    import pg8000.native

    start_time = time.time()
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable is required.")

    conn_params = parse_database_url(db_url)
    conn = pg8000.native.Connection(**conn_params)

    total_processed = 0
    batch_size = 500

    try:
        for record in event.get("Records", []):
            bucket = record["s3"]["bucket"]["name"]
            key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
            logger.info(f"Processing S3 object: s3://{bucket}/{key}")

            response = s3_client.get_object(Bucket=bucket, Key=key)
            body_stream = io.TextIOWrapper(response["Body"], encoding="utf-8")
            reader = csv.DictReader(body_stream)

            batch = []
            for row in reader:
                try:
                    user_id = row["user_id"].strip()
                    name = row["name"].strip()
                    email = row["email"].strip()
                    monthly_income = int(float(row["monthly_income"]))
                    credit_score = int(float(row["credit_score"]))
                    employment_status = row["employment_status"].strip()
                    age = int(float(row["age"]))
                    batch.append(
                        (
                            user_id,
                            name,
                            email,
                            monthly_income,
                            credit_score,
                            employment_status,
                            age,
                        )
                    )
                except (KeyError, ValueError) as row_err:
                    logger.warning(f"Skipping malformed CSV row: {row} ({row_err})")
                    continue

                if len(batch) >= batch_size:
                    _upsert_batch(conn, batch)
                    total_processed += len(batch)
                    batch.clear()

            if batch:
                _upsert_batch(conn, batch)
                total_processed += len(batch)
                batch.clear()

        elapsed = round(time.time() - start_time, 2)
        logger.info(f"Successfully ingested {total_processed} users into AWS RDS in {elapsed}s.")

        webhook_url = os.environ.get("N8N_WEBHOOK_URL")
        if webhook_url and not webhook_url.startswith("http://localhost"):
            try:
                payload = json.dumps(
                    {
                        "status": "completed",
                        "rows_ingested": total_processed,
                        "elapsed_seconds": elapsed,
                    }
                ).encode("utf-8")
                req = urllib.request.Request(
                    webhook_url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=5)
                logger.info(f"Triggered n8n webhook at {webhook_url}")
            except Exception as wh_err:
                logger.warning(f"Webhook notification skipped/failed: {wh_err}")

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "status": "completed",
                    "rows_ingested": total_processed,
                    "elapsed_seconds": elapsed,
                }
            ),
        }
    finally:
        conn.close()


def _upsert_batch(conn, batch: list):
    placeholders = []
    params = {}
    for idx, row in enumerate(batch):
        placeholders.append(
            f"(:u_{idx}, :n_{idx}, :e_{idx}, :m_{idx}, :c_{idx}, :s_{idx}, :a_{idx})"
        )
        params[f"u_{idx}"] = row[0]
        params[f"n_{idx}"] = row[1]
        params[f"e_{idx}"] = row[2]
        params[f"m_{idx}"] = row[3]
        params[f"c_{idx}"] = row[4]
        params[f"s_{idx}"] = row[5]
        params[f"a_{idx}"] = row[6]

    sql = f"""
        INSERT INTO users (
            user_id, name, email, monthly_income, credit_score, employment_status, age
        ) VALUES {", ".join(placeholders)}
        ON CONFLICT (user_id) DO UPDATE SET
            name = EXCLUDED.name,
            email = EXCLUDED.email,
            monthly_income = EXCLUDED.monthly_income,
            credit_score = EXCLUDED.credit_score,
            employment_status = EXCLUDED.employment_status,
            age = EXCLUDED.age,
            updated_at = CURRENT_TIMESTAMP;
    """
    conn.run(sql, **params)