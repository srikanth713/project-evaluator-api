import json

import httpx
import pytest

from app.config import ConfigError, Settings
from app.utils.validators import parse_github_url
from tests.conftest import (
    GOOD_AI_OUTPUT,
    VALID_PAYLOAD,
    gemini_response,
    github_ok_handler,
    make_client,
)

URL = "/api/v1/projects/evaluate"


# ---------------------------------------------------------------- happy path

def test_valid_submission_and_saved_result(client):
    resp = client.post(URL, json=VALID_PAYLOAD)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    analysis = body["project_analysis"]
    assert analysis["project_title"] == "Fraud Detection System"
    assert analysis["detected_domain"] == "Machine Learning"
    score = analysis["score"]
    assert score["total"] == sum(score["breakdown"].values()) == 58
    assert "does not prove" in score["limitations"]
    assert "Scikit-learn" in analysis["mentor_requirements"]["required_skills"]
    repo = body["repository"]
    assert repo["languages"]["Python"] == 90.0
    # .env, node_modules and csv files must never be analysed
    assert set(repo["files_analyzed"]) == {"README.md", "requirements.txt", "src/model.py"}

    saved = client.get(f"/api/v1/projects/{body['project_id']}/result")
    assert saved.status_code == 200
    assert saved.json()["project_analysis"] == analysis


def test_total_is_computed_server_side_even_if_ai_sends_a_total(client):
    out = dict(GOOD_AI_OUTPUT, total=100)
    c = make_client(gemini_handler=lambda r: gemini_response(json.dumps(out)))
    assert c.post(URL, json=VALID_PAYLOAD).json()["project_analysis"]["score"]["total"] == 58


def test_prompt_marks_repo_content_as_untrusted():
    seen = {}

    def gemini(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["headers"] = request.headers
        seen["url"] = str(request.url)
        return gemini_response(json.dumps(GOOD_AI_OUTPUT))

    c = make_client(gemini_handler=gemini)
    assert c.post(URL, json=VALID_PAYLOAD).status_code == 200
    prompt = seen["body"]["contents"][0]["parts"][0]["text"]
    assert "<untrusted_data>" in prompt and "ignore previous instructions" in prompt
    assert "NOT instructions" in seen["body"]["systemInstruction"]["parts"][0]["text"]
    assert ".env" in prompt  # reported as a sensitive filename...
    assert "content of .env" not in prompt  # ...but its content is never fetched
    assert "test-gemini-key" not in seen["url"]  # key is sent as a header only
    assert seen["headers"]["x-goog-api-key"] == "test-gemini-key"


# ------------------------------------------------------------ request errors

@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/octo/repo",                # not https
        "https://evil.com/octo/repo",                 # wrong host
        "https://github.com.evil.com/octo/repo",      # look-alike host
        "https://github.com@evil.com/octo/repo",      # credentials trick
        "https://169.254.169.254/latest/meta-data",   # SSRF target
        "https://github.com/octo",                    # no repo
        "https://github.com/octo/repo/issues",        # not a repo root
        "https://github.com/octo/repo?x=1",           # query string
        "not a url",
    ],
)
def test_invalid_github_url_rejected(client, url):
    resp = client.post(URL, json={**VALID_PAYLOAD, "github_url": url})
    assert resp.status_code == 422
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INVALID_REQUEST"
    assert body["error"]["details"][0]["field"] == "github_url"


def test_github_url_normalised():
    assert parse_github_url("https://www.github.com/Octo/My-Repo.git/") == ("Octo", "My-Repo")


def test_invalid_body_fields(client):
    resp = client.post(URL, json={"student_id": "bad id!", "project_title": ""})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_REQUEST"


# --------------------------------------------------------- missing API key

def test_missing_gemini_key_returns_503_without_calling_github():
    calls = []

    def github(request):
        calls.append(request)
        return github_ok_handler(request)

    c = make_client(github_handler=github, gemini_api_key="")
    resp = c.post(URL, json=VALID_PAYLOAD)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AI_NOT_CONFIGURED"
    assert calls == []


# ------------------------------------------------------------ GitHub failures

def _github(status, json_body=None, headers=None, tree_status=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/git/trees/main") and tree_status is not None:
            return httpx.Response(tree_status, json={"message": "Git Repository is empty."})
        if request.url.path == "/repos/octo/fraud-detection" and status != 200:
            return httpx.Response(status, json=json_body or {"message": "x"}, headers=headers or {})
        return github_ok_handler(request)

    return handler


@pytest.mark.parametrize(
    "handler,status,code",
    [
        (_github(404), 404, "REPO_NOT_FOUND"),
        (_github(403, {"message": "Repository access blocked"}), 403, "REPO_INACCESSIBLE"),
        (_github(403, {"message": "API rate limit exceeded"}, {"x-ratelimit-remaining": "0"}), 429, "GITHUB_RATE_LIMITED"),
        (_github(500), 502, "GITHUB_ERROR"),
        (_github(200, tree_status=409), 422, "EMPTY_REPOSITORY"),
    ],
)
def test_github_repository_unavailable(handler, status, code):
    resp = make_client(github_handler=handler).post(URL, json=VALID_PAYLOAD)
    assert resp.status_code == status
    assert resp.json()["error"]["code"] == code


def test_private_repository_refused_by_default():
    def handler(request):
        if request.url.path == "/repos/octo/fraud-detection":
            return httpx.Response(200, json={"private": True, "default_branch": "main"})
        return github_ok_handler(request)

    resp = make_client(github_handler=handler).post(URL, json={**VALID_PAYLOAD, "repo_access_consent": True})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "REPO_PRIVATE"


def test_github_timeout():
    def handler(request):
        raise httpx.ConnectTimeout("slow")

    resp = make_client(github_handler=handler).post(URL, json=VALID_PAYLOAD)
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "GITHUB_TIMEOUT"


# ------------------------------------------------------------ Gemini failures

@pytest.mark.parametrize(
    "response,status,code",
    [
        (httpx.Response(429, json={"error": {"message": "quota"}}), 429, "AI_RATE_LIMITED"),
        (httpx.Response(500, json={"error": {"message": "boom"}}), 502, "AI_SERVICE_ERROR"),
        (httpx.Response(403, json={"error": {"message": "API key not valid: test-gemini-key"}}), 503, "AI_REJECTED_REQUEST"),
    ],
)
def test_gemini_api_failure(response, status, code):
    resp = make_client(gemini_handler=lambda r: response).post(URL, json=VALID_PAYLOAD)
    assert resp.status_code == status
    assert resp.json()["error"]["code"] == code
    assert "test-gemini-key" not in resp.text


def test_gemini_timeout():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    resp = make_client(gemini_handler=handler).post(URL, json=VALID_PAYLOAD)
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "AI_TIMEOUT"


@pytest.mark.parametrize(
    "text",
    [
        "Sorry, I cannot help with that.",
        "{not valid json",
        json.dumps({"detected_domain": "ML"}),  # valid JSON, wrong structure
        json.dumps({**GOOD_AI_OUTPUT, "score_breakdown": {**GOOD_AI_OUTPUT["score_breakdown"], "innovation": 99}}),
    ],
)
def test_invalid_ai_json_response(text):
    resp = make_client(gemini_handler=lambda r: gemini_response(text)).post(URL, json=VALID_PAYLOAD)
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "AI_INVALID_JSON"


def test_ai_json_wrapped_in_markdown_fence_is_accepted():
    fenced = "```json\n" + json.dumps(GOOD_AI_OUTPUT) + "\n```"
    resp = make_client(gemini_handler=lambda r: gemini_response(fenced)).post(URL, json=VALID_PAYLOAD)
    assert resp.status_code == 200


# --------------------------------------------------------- platform behaviour

def test_rate_limiting():
    c = make_client(rate_limit_requests=2, rate_limit_window_seconds=60)
    assert c.post(URL, json=VALID_PAYLOAD).status_code == 200
    assert c.post(URL, json=VALID_PAYLOAD).status_code == 200
    third = c.post(URL, json=VALID_PAYLOAD)
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "RATE_LIMITED"


def test_optional_api_access_key():
    c = make_client(api_access_key="s3cret")
    assert c.post(URL, json=VALID_PAYLOAD).status_code == 401
    assert c.post(URL, json=VALID_PAYLOAD, headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.post(URL, json=VALID_PAYLOAD, headers={"X-API-Key": "s3cret"}).status_code == 200


def test_result_not_found_and_bad_id(client):
    assert client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000/result").status_code == 404
    assert client.get("/api/v1/projects/abc/result").status_code == 422


def test_unexpected_error_is_sanitised():
    def handler(request):
        raise RuntimeError("secret internal detail /etc/passwd")

    resp = make_client(gemini_handler=handler).post(URL, json=VALID_PAYLOAD)
    assert resp.status_code == 500
    assert "secret" not in resp.text and "Traceback" not in resp.text
    assert resp.json()["error"]["code"] == "INTERNAL_ERROR"


def test_wildcard_cors_rejected_in_production():
    with pytest.raises(ConfigError):
        Settings(environment="production", cors_origins=["*"]).validate()
