# MSGI ONE – AI Student Project Evaluator API

A FastAPI service that takes a student's project details and GitHub repository link, reads the **public** repository through the GitHub REST API, asks **Google Gemini** to evaluate it, and returns structured feedback, an explainable score out of 100 and the *criteria* for a suitable alumni mentor. The MSGI ONE app matches those criteria against its own alumni database; this API never invents alumni.

## 1. Features

- `POST /api/v1/projects/evaluate`: domain detection, technologies/languages, strengths, weaknesses, improvement/architecture/documentation suggestions, security concerns, next steps, extra feature ideas, score and mentor requirements.
- `GET /api/v1/projects/{project_id}/result`: fetch a saved evaluation (SQLite persistence).
- `GET /api/v1/health`: liveness check.
- Strict GitHub URL validation (SSRF-safe), request timeouts, per-IP rate limiting, optional `X-API-Key`.
- Configurable CORS; wildcard is refused when `ENVIRONMENT=production`.
- Consistent JSON errors with correct status codes. No stack traces, keys or internals are ever returned.
- Score total is **computed by the server** from five 0–20 sub-scores, so the breakdown always sums to the total.

## 2. Architecture

```
app/
  main.py                    app factory, CORS, exception handlers
  config.py                  Settings from environment (.env supported)
  schemas/project.py         request, AI-output and response models (Pydantic)
  routes/
    health.py  evaluation.py  deps.py (API key, rate limit)
  services/
    github_service.py        GitHub REST client, file selection, size limits
    gemini_service.py        prompt building, Gemini REST call, JSON validation
    evaluation_service.py    orchestration + score assembly + persistence
    storage.py               SQLite store
  utils/
    validators.py            GitHub URL parsing   rate_limit.py   errors.py
tests/                       39 tests, all external calls mocked
```

Flow: validate request → check Gemini key → GitHub metadata, languages, file tree → select a few key text files (README, manifests, entry points, source) → Gemini → validate JSON → save → respond.

### Security design

| Concern | How it is handled |
|---|---|
| SSRF | Only `https://github.com/<owner>/<repo>` is accepted (no credentials, ports, queries, other hosts). The user URL is never fetched. Only the extracted owner/repo is sent to the fixed host `api.github.com`; redirects are not followed. |
| Code execution | Repositories are read file-by-file via the API. Nothing is cloned, installed, imported or run. |
| Prompt injection | Repo text is sent inside an `<untrusted_data>` JSON block; the system prompt says it is data, not instructions. The AI output is schema-validated and the score total is recomputed by the server. |
| Secrets | Keys come from environment variables only; Gemini key is sent in a header, never in a URL or response. `.env`, `*.pem`, `*.key`, `google-services.json` etc. are reported by filename only, and their contents are never fetched. |
| Private repos | Refused by default (`REPO_PRIVATE`). They are analysed only if the server sets `ALLOW_PRIVATE_REPOS=true` **and** the request has `"repo_access_consent": true`. Enable this only with a `GITHUB_TOKEN` scoped to repositories you are authorised to read. |
| Content limits | Max 10 files, files over 100 KB skipped, 6,000 chars per file, 40,000 chars total, 300 paths listed. `node_modules`, binaries, data files and lockfiles are skipped. |
| Abuse | In-memory per-IP rate limit (default 10 requests/minute), optional `API_ACCESS_KEY`, overall 120 s request timeout. |

**Limitations:** the score is an AI estimate from a sample of files; it does not prove correctness or security. The rate limiter is per-process (fine for a single Render instance). SQLite on Render's free tier is **ephemeral**: saved results are lost on redeploy/restart. Attach a persistent disk (paid plan) and set `DATABASE_PATH=/app/data/evaluations.db`, or have MSGI ONE store the returned JSON itself.

## 3. Installation

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env               # then edit .env
```

## 4. Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | **yes** | – | Gemini key from https://aistudio.google.com/apikey |
| `CORS_ORIGINS` | prod: yes | `http://localhost:3000` | Comma-separated allowed origins |
| `ENVIRONMENT` | no | `development` | `production` enforces no `*` CORS |
| `GITHUB_TOKEN` | no | – | Raises GitHub limit from 60 to 5,000 requests/hour |
| `API_ACCESS_KEY` | no | – | If set, callers must send `X-API-Key` |
| `GEMINI_MODEL` | no | `gemini-2.5-flash` | Any Gemini model that supports `generateContent` |
| `GEMINI_TIMEOUT_SECONDS` / `GITHUB_TIMEOUT_SECONDS` | no | `60` / `15` | Upstream timeouts |
| `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` | no | `10` / `60` | Per-IP limit for `/evaluate` |
| `MAX_FILES_TO_ANALYZE` / `MAX_TOTAL_CHARS` | no | `10` / `40000` | Repo content limits |
| `ALLOW_PRIVATE_REPOS` | no | `false` | See security table |
| `DATABASE_PATH` | no | `data/evaluations.db` | SQLite file |

## 5. Run locally

```bash
uvicorn app.main:app --reload --port 8000
```

Interactive docs: http://localhost:8000/docs

## 6. Test

```bash
pytest -q
```

All GitHub and Gemini calls are mocked with `httpx.MockTransport`; no API key or network is needed. Covered: health, valid submission, invalid/SSRF URLs, missing key, GitHub 404/403/rate-limit/500/empty/private/timeout, Gemini 429/500/403/timeout, non-JSON and wrong-shape AI output, prompt-injection framing, rate limiting, API key, CORS, sanitised 500s.

Not tested automatically (needs your real credentials): a live Gemini call and live GitHub traffic. Try one manually after adding your key (see curl below).

## 7. Deploy on Render

1. Push this folder to a GitHub repository (`.env` is git-ignored).
2. In Render: **New → Blueprint**, pick the repo. Render reads `render.yaml` and builds the `Dockerfile`.
3. When prompted, set `GEMINI_API_KEY`, `CORS_ORIGINS` (e.g. `https://app.example.com`), and optionally `GITHUB_TOKEN` and `API_ACCESS_KEY`.
4. After the deploy, check `https://<service-name>.onrender.com/api/v1/health`.

Production start command (used by the Dockerfile; Render supplies `$PORT`):

```bash
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'
```

Example deployed URL: `https://msgi-project-evaluator-api.onrender.com/api/v1/projects/evaluate`. Free instances sleep when idle, so the first call can take ~30 s.

## 8. API reference

All errors use: `{"success": false, "error": {"code": "...", "message": "...", "details": [...]}}`.

### `GET /api/v1/health`
```json
{"status":"ok","service":"MSGI ONE Project Evaluator API","version":"1.0.0","ai_configured":true,"timestamp":"2026-11-17T04:46:59+00:00"}
```

### `POST /api/v1/projects/evaluate`

| Field | Type | Rules |
|---|---|---|
| `student_id` | string | 1–64 chars: letters, digits, `_ . -` |
| `project_title` | string | 1–150 chars |
| `project_description` | string | 10–4000 chars |
| `technologies` | string[] | up to 30, each ≤ 50 chars (optional) |
| `github_url` | string | `https://github.com/<owner>/<repo>` |
| `repo_access_consent` | bool | optional; only for private repos (see above) |

```bash
curl -X POST https://YOUR-SERVICE.onrender.com/api/v1/projects/evaluate \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_ACCESS_KEY" \
  -d '{
    "student_id": "STU001",
    "project_title": "Fraud Detection System",
    "project_description": "An ML-based system for detecting fraudulent transactions",
    "technologies": ["Python", "Pandas", "Scikit-learn"],
    "github_url": "https://github.com/username/repository"
  }'
```
(Omit the `X-API-Key` header if you did not set `API_ACCESS_KEY`.)

Sample response (values illustrative):

```json
{
  "success": true,
  "project_id": "3f0c1a52-8d0b-4a8c-9a53-6d1c1f7e2b10",
  "student_id": "STU001",
  "evaluated_at": "2026-11-17T05:00:00Z",
  "project_analysis": {
    "project_title": "Fraud Detection System",
    "detected_domain": "Machine Learning",
    "technologies_identified": ["Python", "Pandas", "Scikit-learn"],
    "programming_languages": ["Python"],
    "strengths": ["Clear separation between data loading (src/model.py) and training."],
    "weaknesses": ["No automated tests were found."],
    "improvement_suggestions": ["Add stratified cross-validation and report precision/recall."],
    "documentation_feedback": ["README lacks dataset description and setup steps."],
    "architecture_suggestions": ["Split training and inference into separate modules."],
    "security_concerns": [],
    "next_steps": ["Add pytest tests for preprocessing."],
    "additional_features": ["Expose the model through a REST API."],
    "score": {
      "total": 58,
      "breakdown": {"organization": 14, "implementation": 13, "documentation": 10, "maintainability": 9, "innovation": 12},
      "explanation": "Reasonable structure, limited tests and documentation.",
      "criteria": {"organization": "...", "implementation": "...", "documentation": "...", "maintainability": "...", "innovation": "..."},
      "limitations": "This score is an AI-generated estimate ... does not prove that the code is correct, bug-free or secure ..."
    },
    "mentor_requirements": {
      "domain": "Machine Learning",
      "required_skills": ["Python", "Pandas", "Scikit-learn", "ML model evaluation"],
      "recommended_mentor_profile": "Alumni working in Machine Learning or Data Science."
    }
  },
  "repository": {
    "full_name": "username/repository", "url": "https://github.com/username/repository",
    "default_branch": "main", "primary_language": "Python", "languages": {"Python": 90.0, "Shell": 10.0},
    "stars": 3, "last_pushed_at": "2026-01-01T00:00:00Z", "has_readme": true, "has_tests": false,
    "has_license": false, "total_files": 7, "files_analyzed": ["README.md", "requirements.txt", "src/model.py"],
    "tree_truncated": false
  },
  "disclaimer": "AI-generated feedback. Repository code was read through the GitHub API only and was never executed."
}
```

### `GET /api/v1/projects/{project_id}/result`
Returns the same body as above for a `project_id` previously returned by `/evaluate` (404 `RESULT_NOT_FOUND` otherwise).

### Error codes

| HTTP | `error.code` | Meaning |
|---|---|---|
| 401 | `UNAUTHORIZED` | Missing/invalid `X-API-Key` |
| 403 | `REPO_PRIVATE`, `REPO_INACCESSIBLE` | Private/blocked repository |
| 404 | `REPO_NOT_FOUND`, `RESULT_NOT_FOUND` | Not found (or private, unauthenticated) |
| 422 | `INVALID_REQUEST`, `EMPTY_REPOSITORY`, `INVALID_PROJECT_ID`, `AI_CONTENT_BLOCKED` | Bad input / nothing to evaluate |
| 429 | `RATE_LIMITED`, `GITHUB_RATE_LIMITED`, `AI_RATE_LIMITED` | Rate limits |
| 502 | `AI_INVALID_JSON`, `AI_INVALID_RESPONSE`, `AI_SERVICE_ERROR`, `AI_UNREACHABLE`, `GITHUB_ERROR`, `GITHUB_UNREACHABLE`, `GITHUB_AUTH_FAILED` | Upstream failure |
| 503 | `AI_NOT_CONFIGURED`, `AI_REJECTED_REQUEST`, `AI_MODEL_UNAVAILABLE` | Server AI config problem |
| 504 | `AI_TIMEOUT`, `GITHUB_TIMEOUT`, `REQUEST_TIMEOUT` | Timeout |
| 500 | `INTERNAL_ERROR`, `STORAGE_ERROR` | Unexpected (details never exposed) |

## 9. Connect from an app

Evaluations take roughly 5–30 seconds, so use a generous client timeout (≥ 90 s) and show a loading state. **Do not embed `GEMINI_API_KEY` or `GITHUB_TOKEN` in any app.** If you set `API_ACCESS_KEY`, a key shipped inside a mobile/web app can be extracted, so the safest pattern is for the MSGI ONE backend to call this API and the app to call your backend. The rate limit and CORS list still apply either way.

**React**
```js
const API = "https://YOUR-SERVICE.onrender.com/api/v1";
export async function evaluateProject(payload) {
  const res = await fetch(`${API}/projects/evaluate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error?.message ?? "Evaluation failed");
  return data.project_analysis;
}
```
Add your site's origin to `CORS_ORIGINS`.

**Flutter** (add the `http` package to pubspec.yaml)
```dart
import 'dart:convert';
import 'package:http/http.dart' as http;

Future<Map<String, dynamic>> evaluateProject(Map<String, dynamic> payload) async {
  final res = await http
      .post(Uri.parse('https://YOUR-SERVICE.onrender.com/api/v1/projects/evaluate'),
          headers: {'Content-Type': 'application/json'}, body: jsonEncode(payload))
      .timeout(const Duration(seconds: 90));
  final data = jsonDecode(res.body) as Map<String, dynamic>;
  if (res.statusCode != 200) throw Exception(data['error']?['message'] ?? 'Evaluation failed');
  return data['project_analysis'] as Map<String, dynamic>;
}
```
Native mobile apps are not subject to CORS.

**Android (Kotlin, OkHttp)**
```kotlin
val client = OkHttpClient.Builder().callTimeout(90, TimeUnit.SECONDS).build()
val body = json.toRequestBody("application/json".toMediaType())
val request = Request.Builder()
    .url("https://YOUR-SERVICE.onrender.com/api/v1/projects/evaluate")
    .post(body).build()
client.newCall(request).execute().use { response -> val text = response.body?.string() }
```
Run this off the main thread (coroutine/`Dispatchers.IO`). Add the `INTERNET` permission.

### Matching mentors
Use `project_analysis.mentor_requirements.domain` and `required_skills` as filters against your alumni table (e.g. skills overlap ≥ 2 and domain match).
