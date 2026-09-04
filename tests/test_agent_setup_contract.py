import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def decode_powershell_char_codes(script: str, variable_name: str) -> str:
    match = re.search(rf"\${variable_name}\s*=\s*@\((.*?)\)", script, re.DOTALL)
    assert match is not None
    codes = re.findall(r"0x[0-9A-Fa-f]+", match.group(1))
    return "".join(chr(int(code, 16)) for code in codes)


def test_readme_has_agent_setup_quickstart_contract() -> None:
    readme = read_repo_file("README.md")

    assert "## Agent Setup Quickstart" in readme
    assert "CLI coding agent" in readme
    assert "shared EC2 Ollama endpoint" in readme
    assert ".\\scripts\\dev_setup.ps1 -Profile shared-ec2 -ForceEnv" in readme
    assert "scripts/dev_verify.ps1" in readme
    assert "SETUP_OK" in readme
    assert "Do not move Ollama/Qwen into Docker" in readme
    assert "local-ollama" in readme
    assert "docs/TEAM_ENVIRONMENT.md" in readme


def test_dev_setup_script_bootstraps_profile_driven_environment() -> None:
    script = read_repo_file("scripts/dev_setup.ps1")

    assert '[ValidateSet("shared-ec2", "local-ollama")]' in script
    assert '[string]$Profile = "shared-ec2"' in script
    assert "[switch]$ForceEnv" in script
    assert ".env.shared-ec2.example" in script
    assert ".env.local-ollama.example" in script
    assert "Test-OllamaEndpoint" in script
    assert "Assert-OllamaModels" in script
    assert 'if ($Profile -eq "local-ollama")' in script
    assert 'Require-Command "ollama"' in script
    assert "ollama pull $embeddingModel" in script
    assert "ollama pull $llmModel" in script
    assert "docker compose up -d --build" in script
    assert "python scripts/ingest_md.py datasets/docs --reset" in script
    assert "SETUP_DONE" in script


def test_dev_setup_can_backup_existing_env_when_forcing_profile() -> None:
    script = read_repo_file("scripts/dev_setup.ps1")

    assert ".env.backup." in script
    assert "Copy-Item .env $backupPath" in script
    assert "Copy-Item $templatePath .env" in script


def test_shared_ec2_env_template_uses_team_endpoint() -> None:
    env_template = read_repo_file(".env.shared-ec2.example")

    assert "TEAM_ENV_PROFILE=shared-ec2" in env_template
    assert re.search(r"^OLLAMA_BASE_URL=http://[A-Za-z0-9_.-]+:11434$", env_template, re.M)
    assert "YOUR_EC2_PUBLIC_IP" in env_template
    assert "LLM_MODEL=qwen3:4b-instruct" in env_template
    assert "EMBEDDING_MODEL=bge-m3" in env_template
    assert "QDRANT_URL=http://qdrant:6333" in env_template


def test_local_ollama_env_template_preserves_on_prem_story() -> None:
    env_template = read_repo_file(".env.local-ollama.example")

    assert "TEAM_ENV_PROFILE=local-ollama" in env_template
    assert "OLLAMA_BASE_URL=http://host.docker.internal:11434" in env_template
    assert "LLM_MODEL=qwen3:4b-instruct" in env_template
    assert "EMBEDDING_MODEL=bge-m3" in env_template


def test_env_example_uses_local_ollama_bootstrap_models() -> None:
    env_example = read_repo_file(".env.example")

    assert "TEAM_ENV_PROFILE=local-ollama" in env_example
    assert "LLM_MODEL=qwen3:4b-instruct" in env_example
    assert "EMBEDDING_MODEL=bge-m3" in env_example
    assert "OLLAMA_BASE_URL=http://host.docker.internal:11434" in env_example


def test_dev_verify_script_checks_runtime_and_prints_setup_ok() -> None:
    script = read_repo_file("scripts/dev_verify.ps1")

    assert "Read-DotEnv" in script
    assert "TEAM_ENV_PROFILE" in script
    assert "OLLAMA_BASE_URL" in script
    assert "/api/tags" in script
    assert "qwen3:4b-instruct" in read_repo_file(".env.shared-ec2.example")
    assert "bge-m3" in read_repo_file(".env.shared-ec2.example")
    assert "http://localhost:6333" in script
    assert "python -m app.healthcheck" in script
    assert "pytest -v" in script
    assert "python scripts/ask_rag.py" in script
    assert "$sampleQuestionCodes" in script
    assert "0xBC95" in script
    assert "$sampleQuestion = -join" in script
    assert "Sources:" in script
    assert "$fallbackPhraseCodes" in script
    assert "$fallbackPhrase = -join" in script
    assert "$ragText.Contains($fallbackPhrase)" in script
    assert "SETUP_OK" in script


def test_dev_verify_sample_question_is_confirmed_by_current_corpus() -> None:
    script = read_repo_file("scripts/dev_verify.ps1")

    assert decode_powershell_char_codes(script, "sampleQuestionCodes") == (
        "법인카드 사용 후 전표 처리는 언제까지 해야 하나요?"
    )


def test_dev_verify_allows_docker_status_stderr_during_sample_question() -> None:
    script = read_repo_file("scripts/dev_verify.ps1")

    assert "System.Diagnostics.ProcessStartInfo" in script
    assert 'FileName = "docker"' in script
    assert "RedirectStandardOutput = $true" in script
    assert "RedirectStandardError = $true" in script
    assert "$sampleExitCode = $process.ExitCode" in script


def test_gitignore_excludes_local_rag_state() -> None:
    gitignore = read_repo_file(".gitignore")

    assert "storage/" in gitignore
    assert "*.sqlite" in gitignore
    assert "*.sqlite3" in gitignore
    assert ".env.backup.*" in gitignore
    assert "!.env.shared-ec2.example" in gitignore
    assert "!.env.local-ollama.example" in gitignore


def test_team_environment_doc_exists_and_mentions_security_group() -> None:
    doc = read_repo_file("docs/TEAM_ENVIRONMENT.md")

    assert "shared-ec2" in doc
    assert "local-ollama" in doc
    assert re.search(r"http://[A-Za-z0-9_.-]+:11434", doc)
    assert "security group" in doc
    assert "SETUP_OK" in doc


def test_tracked_files_do_not_contain_real_public_endpoint():
    """추적 파일에는 실제 공인 IP 엔드포인트가 없어야 한다.

    사설망(10/8, 172.16/12, 192.168/16)과 문서용 예약 대역(RFC 5737)은 허용한다.
    """
    allowed = re.compile(
        r"^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|192\.0\.2\.|198\.51\.100\.|203\.0\.113\.)"
    )
    pattern = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3}):11434")
    if shutil.which("git") is None or not (REPO_ROOT / ".git").exists():
        pytest.skip("git CLI or .git directory not available (e.g. inside the Docker image)")
    grep = subprocess.run(
        ["git", "grep", "-n", "-E", r"[0-9]{1,3}(\.[0-9]{1,3}){3}:11434"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    offending = [
        line
        for line in grep.stdout.splitlines()
        if any(not allowed.match(ip) for ip in pattern.findall(line))
    ]

    assert offending == [], "\n".join(offending)
