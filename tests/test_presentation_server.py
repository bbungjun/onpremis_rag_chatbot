import io
import json
import threading
import urllib.request
from types import SimpleNamespace
from wsgiref.simple_server import WSGIRequestHandler, make_server

from app.presentation_server import make_app


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        return None


def call_app(app, method, path, body=b""):
    status_headers = {}

    def start_response(status, headers):
        status_headers["status"] = status
        status_headers["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "wsgi.input": io.BytesIO(body),
        "CONTENT_LENGTH": str(len(body)),
    }
    response_body = b"".join(app(environ, start_response))
    return status_headers["status"], status_headers["headers"], response_body


def test_make_app_serves_index(tmp_path):
    frontend_dir = tmp_path / "presentation"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text("<h1>Local LLM 챗봇</h1>", encoding="utf-8")
    cases_path = frontend_dir / "demo_cases.json"
    cases_path.write_text('{"cases":[]}', encoding="utf-8")

    app = make_app(frontend_dir=frontend_dir, cases_path=cases_path)

    status, headers, body = call_app(app, "GET", "/")

    assert status.startswith("200")
    assert headers["Content-Type"].startswith("text/html")
    assert b"Local LLM" in body


def test_make_app_returns_cases(tmp_path):
    frontend_dir = tmp_path / "presentation"
    frontend_dir.mkdir()
    cases_path = frontend_dir / "demo_cases.json"
    cases_path.write_text('{"cases":[{"id":"case-1"}]}', encoding="utf-8")

    app = make_app(
        frontend_dir=frontend_dir,
        cases_path=cases_path,
        cases_loader=lambda path: {"cases": [{"id": "case-1"}]},
    )

    status, headers, body = call_app(app, "GET", "/api/cases")

    assert status.startswith("200")
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(body)["cases"][0]["id"] == "case-1"


def test_make_app_returns_runtime_status(tmp_path):
    frontend_dir = tmp_path / "presentation"
    frontend_dir.mkdir()
    cases_path = frontend_dir / "demo_cases.json"
    cases_path.write_text('{"cases":[]}', encoding="utf-8")

    app = make_app(
        frontend_dir=frontend_dir,
        cases_path=cases_path,
        settings_factory=lambda: SimpleNamespace(
            retrieval_top_k=3,
            num_predict=192,
            llm_model="qwen3:4b-instruct",
            ollama_base_url="http://203.0.113.10:11434",
        ),
        status_provider=lambda settings, env: {
            "local": {
                "label": "Ollama + Qwen",
                "model": settings.llm_model,
                "endpoint": settings.ollama_base_url,
                "integration_status": "ok",
                "integration_message": "EC2 Ollama endpoint reachable",
            },
            "api": {
                "label": "AWS Bedrock",
                "model": env["BEDROCK_MODEL_ID"],
                "region": env["BEDROCK_REGION"],
                "integration_status": "ok",
                "integration_message": "AWS credentials detected",
            },
        },
        env={
            "BEDROCK_REGION": "ap-northeast-2",
            "BEDROCK_MODEL_ID": "anthropic.claude-3-5-sonnet-20240620-v1:0",
            "BEDROCK_MODEL_LABEL": "AWS Bedrock",
        },
    )

    status, headers, body = call_app(app, "GET", "/api/status")

    payload = json.loads(body)
    assert status.startswith("200")
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert payload["local"]["model"] == "qwen3:4b-instruct"
    assert payload["api"]["model"] == "anthropic.claude-3-5-sonnet-20240620-v1:0"


def test_make_app_runs_live_compare_with_stable_response_contract(tmp_path):
    frontend_dir = tmp_path / "presentation"
    frontend_dir.mkdir()
    cases_path = frontend_dir / "demo_cases.json"
    cases_path.write_text('{"cases":[]}', encoding="utf-8")

    def fake_compare(question, filters, **kwargs):
        return {
            "question": question,
            "filters": filters,
            "local": {"status": "ok", "answer": "local", "sources": []},
            "api": {"status": "ok", "answer": "api", "sources": []},
            "shared_sources": [],
        }

    app = make_app(
        frontend_dir=frontend_dir,
        cases_path=cases_path,
        settings_factory=lambda: SimpleNamespace(retrieval_top_k=3, num_predict=192),
        compare=fake_compare,
        env={
            "BEDROCK_REGION": "ap-northeast-2",
            "BEDROCK_MODEL_ID": "bedrock-model",
            "BEDROCK_MODEL_LABEL": "AWS Bedrock",
        },
    )
    body = json.dumps({"question": "연차 신청은?", "filters": {"department": "hr"}}).encode()

    status, headers, response = call_app(app, "POST", "/api/compare", body)

    payload = json.loads(response)
    assert status.startswith("200")
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert set(payload) == {"question", "filters", "local", "api", "shared_sources"}
    assert payload["question"] == "연차 신청은?"


def test_make_app_passes_selected_local_model_to_compare(tmp_path):
    frontend_dir = tmp_path / "presentation"
    frontend_dir.mkdir()
    cases_path = frontend_dir / "demo_cases.json"
    cases_path.write_text('{"cases":[]}', encoding="utf-8")
    captured = {}

    def fake_compare(question, filters, **kwargs):
        captured["question"] = question
        captured["filters"] = filters
        captured["local_model"] = kwargs["local_model"]
        return {
            "question": question,
            "filters": filters,
            "local": {"status": "ok", "answer": "local", "sources": []},
            "api": {"status": "pending", "answer": "api pending", "sources": []},
            "shared_sources": [],
        }

    app = make_app(
        frontend_dir=frontend_dir,
        cases_path=cases_path,
        settings_factory=lambda: SimpleNamespace(retrieval_top_k=3, num_predict=192),
        compare=fake_compare,
        env={
            "BEDROCK_REGION": "ap-northeast-2",
            "BEDROCK_MODEL_ID": "",
            "BEDROCK_MODEL_LABEL": "AWS Bedrock",
        },
    )
    body = json.dumps(
        {
            "question": "연차 신청은?",
            "filters": {"department": "hr"},
            "local_model": "exaone3.5:7.8b",
        }
    ).encode()

    status, headers, response = call_app(app, "POST", "/api/compare", body)

    assert status.startswith("200")
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(response)["question"] == "연차 신청은?"
    assert captured == {
        "question": "연차 신청은?",
        "filters": {"department": "hr"},
        "local_model": "exaone3.5:7.8b",
    }


def test_presentation_server_serves_page_while_compare_request_is_running(tmp_path):
    import app.presentation_server as server_module

    frontend_dir = tmp_path / "presentation"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text("<h1>Local LLM 챗봇</h1>", encoding="utf-8")
    cases_path = frontend_dir / "demo_cases.json"
    cases_path.write_text('{"cases":[]}', encoding="utf-8")
    compare_started = threading.Event()
    release_compare = threading.Event()
    compare_error = []

    def fake_compare(question, filters, **kwargs):
        compare_started.set()
        release_compare.wait(timeout=3)
        return {
            "question": question,
            "filters": filters,
            "local": {"status": "ok", "answer": "local", "sources": []},
            "api": {"status": "pending", "answer": "api pending", "sources": []},
            "shared_sources": [],
        }

    app = make_app(
        frontend_dir=frontend_dir,
        cases_path=cases_path,
        settings_factory=lambda: SimpleNamespace(retrieval_top_k=3, num_predict=192),
        compare=fake_compare,
        env={
            "BEDROCK_REGION": "ap-northeast-2",
            "BEDROCK_MODEL_ID": "",
            "BEDROCK_MODEL_LABEL": "AWS Bedrock",
        },
    )
    server = make_server(
        "127.0.0.1",
        0,
        app,
        server_class=server_module.ThreadingWsgiServer,
        handler_class=QuietHandler,
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    def run_compare_request():
        payload = json.dumps({"question": "연차 신청은?"}).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/compare",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5).read()
        except Exception as exc:
            compare_error.append(exc)

    compare_thread = threading.Thread(target=run_compare_request, daemon=True)
    try:
        compare_thread.start()
        assert compare_started.wait(timeout=1)

        page = urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=1)

        assert b"Local LLM" in page.read()
    finally:
        release_compare.set()
        compare_thread.join(timeout=5)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)

    assert compare_error == []
