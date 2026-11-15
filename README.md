# Indian Market Vendor Onboarding Automation

Automated compliance verification and onboarding pipeline for Indian vendors with deterministic statutory validation (PAN, GSTIN, CIN, LLPIN, Bank / Cheque, MSME Udyam) and AI document extraction.

> **Core Architecture Principle:** The LLM extracts structured fields from uploaded documents only. All approve / reject / flag decisions are deterministic rule code. The LLM never decides compliance outcomes.

---

## 1. Environment Variables & Security

All sensitive settings are read exclusively from environment variables. Secrets are strictly prohibited from being committed to source control or baked into Docker images.

| Variable | Description | Default | Notes |
|---|---|---|---|
| `GEMINI_API_KEY` | Google Gemini API key for document extraction | `""` | Never logged or echoed. Required only for live AI extraction in `auto` mode. |
| `EXTRACTOR_MODE` | Extraction operational mode (`auto` or `offline`) | `auto` | Set to `offline` to run completely offline without making external LLM calls. |
| `DEMO_MODE` | Enables demo buttons and audit tampering simulations | `true` | Set to `false` in production. |
| `HMAC_SECRET` | Secret key for duplicate bank account hashing | `dev-secret...` | Required in production for cryptographic data privacy. |
| `DATA_DIR` | Path to persistent storage disk directory | `.` | Stores `vendor_onboarding.db` and persistent caches. |
| `EXTRACTION_CACHE_DIR` | Path to persistent document extraction cache | `data/extraction_cache` | Caches sha256-verified extraction outputs for zero-latency demos. |
| `PORT` | HTTP server port | `8000` | Standard web service port. |

---

## 2. Local Setup & Execution

### Prerequisites
* Python 3.9+
* SQLite 3

### Running Locally
```bash
# 1. Clone repository and navigate to workspace
cd asa_case_study

# 2. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. (Optional) Configure environment variables
export EXTRACTOR_MODE=offline
export DEMO_MODE=true

# 5. Run development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Open [http://localhost:8000](http://localhost:8000) in your browser.

---

## 3. Docker Deployment

### Building the Image
```bash
docker build -t vendor-onboarding:latest .
```

### Running with Persistent Storage
```bash
docker run -d \
  --name vendor-app \
  -p 8000:8000 \
  -v $(pwd)/persistent_data:/data \
  -e EXTRACTOR_MODE=offline \
  -e DEMO_MODE=true \
  vendor-onboarding:latest
```

Check health:
```bash
curl http://localhost:8000/health
```

---

## 4. Render Deployment (render.yaml)

A complete `render.yaml` blueprint is provided in the repository root:
1. Connect your repository to Render.
2. Select **New Blueprint Instance** and point to `render.yaml`.
3. Render automatically provisions:
   * A containerized web service.
   * A 1GB persistent disk mounted at `/data` (persisting SQLite DB and extraction caches across redeploys).
   * Health checks on `/health`.
4. In the Render Dashboard, set your `GEMINI_API_KEY` under Environment Variables.

---

## 5. Endpoints & Features

* **`/` (Dashboard):** Real-time monitoring of vendor submissions, risk score distributions, and pending re-uploads.
* **`/submit`:** Form-based multi-slot document uploader (PAN, GSTIN, Cheque, COI, Udyam) with built-in demo scenarios.
* **`/eval`:** Compliance evaluation dashboard displaying:
  * Section 1: Mocked Rule-Engine evaluation (38-record dataset).
  * Section 2: Before / After comparison table tracking layout parsing bug fixes.
  * Section 3: End-to-End PDF evaluation across 24 real generated PDFs and 6 raster scans.
  * Extractor mode switcher (`Offline` vs `Auto Mode (Gemini)`).
* **`/audit`:** Cryptographic hash-chained audit log with SQLite `BEGIN IMMEDIATE` transaction ordering, "Verify Hash Chain" tool, and demo tamper simulator.
* **`/health`:** JSON status check for orchestrators.

---

## 6. Running Tests

```bash
# Run full unit and integration test suite (249+ tests)
pytest tests/ -v
```
