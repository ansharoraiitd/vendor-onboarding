"""
scripts/check_gemini.py — Minimal test script verifying Gemini API connectivity.
Prints ONLY the HTTP status code and extractor_type.
NEVER prints, logs, or exposes the API key.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

import httpx

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("GEMINI_API_KEY loaded: no")
    print("HTTP Status Code: N/A")
    print("extractor_type: error_no_key")
    sys.exit(1)

url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
headers = {
    "x-goog-api-key": api_key,
    "Content-Type": "application/json",
}
payload = {
    "contents": [{"parts": [{"text": "Hello, respond with JSON {\"status\": \"ok\"}"}]}],
    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0},
}

try:
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        print("HTTP Status Code:", resp.status_code)
        print("extractor_type: gemini_api")
except Exception as exc:
    print("HTTP Status Code: network_error")
    print("extractor_type: gemini_api")
