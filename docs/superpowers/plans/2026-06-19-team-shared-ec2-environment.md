# Team Shared EC2 Environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a teammate's CLI agent able to read `README.md`, run the documented setup commands, and end with the same local project configuration backed by the shared EC2 Ollama endpoint.

**Architecture:** Keep Qdrant, SQLite, ingestion, tests, and the app container local to each developer. Move only Ollama model serving to a profile-driven endpoint choice: `shared-ec2` calls the team EC2 Ollama API, while `local-ollama` preserves the on-prem/local fallback. The reproducibility contract is `SETUP_OK` from `scripts/dev_verify.ps1`.

**Tech Stack:** PowerShell, Docker Compose, Ollama HTTP API, Qdrant, SQLite, pytest, AWS EC2.

---

## Environment Contract

The team setup is successful only when all of these are true:

- `.env` contains `TEAM_ENV_PROFILE=shared-ec2`.
- `.env` contains `OLLAMA_BASE_URL=http://YOUR_EC2_PUBLIC_IP:11434`.
- `.env` contains `LLM_MODEL=qwen3:4b-instruct`.
- `.env` contains `EMBEDDING_MODEL=bge-m3`.
- `docker compose run --rm rag-api python -m app.healthcheck` prints the shared EC2 Ollama URL.
- `scripts/dev_verify.ps1` prints `SETUP_OK`.
- The sample RAG answer includes `Sources:`.

## File Structure

- Modify `README.md`
  - Make "Agent Setup Quickstart" profile-driven.
  - Put shared EC2 setup first.
  - Keep local Ollama setup as a fallback profile.

- Create `.env.shared-ec2.example`
  - Committed template for the team EC2 endpoint.
  - Used by `scripts/dev_setup.ps1 -Profile shared-ec2`.

- Create `.env.local-ollama.example`
  - Committed template for developers who need fully local Ollama.
  - Used by `scripts/dev_setup.ps1 -Profile local-ollama`.

- Modify `.env.example`
  - Keep it as the local/on-prem default alias or replace it with a short pointer to profile templates.
  - The safest option is to keep it equivalent to `.env.local-ollama.example` for backwards compatibility.

- Modify `.gitignore`
  - Ignore generated `.env.backup.*` files.

- Modify `scripts/dev_setup.ps1`
  - Add `-Profile shared-ec2|local-ollama`.
  - Add `-ForceEnv`.
  - Backup existing `.env` before forced overwrite.
  - For `shared-ec2`, do not require the local `ollama` CLI.
  - For `shared-ec2`, verify the remote endpoint and required models through `/api/tags`.
  - For `local-ollama`, keep local Ollama checks and model pulls.

- Modify `scripts/dev_verify.ps1`
  - Print the active profile.
  - Verify Ollama endpoint reachability.
  - Verify required model names before running ingestion/question tests.

- Modify `tests/test_agent_setup_contract.py`
  - Lock the README and script behavior so future changes do not break agent-driven setup.

- Create `docs/TEAM_ENVIRONMENT.md`
  - Explain the two profiles, EC2 endpoint, security-group caveat, and troubleshooting.

---

### Task 1: Stabilize The Shared EC2 Endpoint

**Files:**
- No repository files.
- AWS resource: EC2 instance `YOUR_EC2_INSTANCE_ID` in `ap-northeast-3`.

- [ ] **Step 1: Confirm the current endpoint**

Run:

```powershell
Invoke-RestMethod http://YOUR_EC2_PUBLIC_IP:11434/api/tags | ConvertTo-Json -Depth 6
```

Expected: JSON includes both `qwen3:4b-instruct` and `bge-m3:latest`.

- [ ] **Step 2: Allocate and associate an Elastic IP**

Run:

```powershell
$region = "ap-northeast-3"
$instanceId = "YOUR_EC2_INSTANCE_ID"
$allocation = aws ec2 allocate-address --region $region --domain vpc | ConvertFrom-Json
aws ec2 associate-address `
  --region $region `
  --instance-id $instanceId `
  --allocation-id $allocation.AllocationId
aws ec2 describe-addresses `
  --region $region `
  --allocation-ids $allocation.AllocationId `
  --query "Addresses[0].PublicIp" `
  --output text
```

Expected: AWS prints a stable public IPv4 address.

- [ ] **Step 3: Verify the stable endpoint**

Use the Elastic IP printed in Step 2. The current shared team endpoint is `YOUR_EC2_PUBLIC_IP`.

Run:

```powershell
Invoke-RestMethod http://YOUR_EC2_PUBLIC_IP:11434/api/tags | ConvertTo-Json -Depth 6
```

Expected: JSON includes both `qwen3:4b-instruct` and `bge-m3:latest`.

- [ ] **Step 4: Keep port 11434 restricted**

Confirm the security group does not expose Ollama to the whole internet.

Run:

```powershell
aws ec2 describe-security-groups `
  --region ap-northeast-3 `
  --group-ids sg-070ff2b14da37516a `
  --query "SecurityGroups[0].IpPermissions[?FromPort==`11434`]"
```

Expected: inbound port `11434` is limited to approved team IP ranges or VPN CIDRs, not `0.0.0.0/0`.

---

### Task 2: Add Environment Profile Templates

**Files:**
- Create: `.env.shared-ec2.example`
- Create: `.env.local-ollama.example`
- Modify: `.env.example`
- Modify: `.gitignore`
- Test: `tests/test_agent_setup_contract.py`

- [ ] **Step 1: Write failing tests for profile templates**

Add these tests to `tests/test_agent_setup_contract.py`:

```python
def test_shared_ec2_env_template_uses_team_endpoint() -> None:
    env_template = read_repo_file(".env.shared-ec2.example")

    assert "TEAM_ENV_PROFILE=shared-ec2" in env_template
    assert "OLLAMA_BASE_URL=http://YOUR_EC2_PUBLIC_IP:11434" in env_template
    assert "LLM_MODEL=qwen3:4b-instruct" in env_template
    assert "EMBEDDING_MODEL=bge-m3" in env_template
    assert "QDRANT_URL=http://qdrant:6333" in env_template
    assert "SQLITE_PATH=/app/storage/metadata.sqlite" in env_template


def test_local_ollama_env_template_preserves_on_prem_story() -> None:
    env_template = read_repo_file(".env.local-ollama.example")

    assert "TEAM_ENV_PROFILE=local-ollama" in env_template
    assert "OLLAMA_BASE_URL=http://host.docker.internal:11434" in env_template
    assert "LLM_MODEL=qwen3:4b-instruct" in env_template
    assert "EMBEDDING_MODEL=bge-m3" in env_template


def test_gitignore_excludes_env_backups() -> None:
    gitignore = read_repo_file(".gitignore")

    assert ".env.backup.*" in gitignore
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
pytest tests/test_agent_setup_contract.py -v
```

Expected: fails because `.env.shared-ec2.example`, `.env.local-ollama.example`, and `.env.backup.*` do not exist yet.

- [ ] **Step 3: Create `.env.shared-ec2.example`**

Create this exact file:

```env
TEAM_ENV_PROFILE=shared-ec2
OLLAMA_BASE_URL=http://YOUR_EC2_PUBLIC_IP:11434
LLM_MODEL=qwen3:4b-instruct
EMBEDDING_MODEL=bge-m3

QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=llmenhance_chunks

SQLITE_PATH=/app/storage/metadata.sqlite

CHUNK_SIZE=1200
CHUNK_OVERLAP=250
RETRIEVAL_TOP_K=5
TEMPERATURE=0.2
NUM_CTX=4096
NUM_PREDICT=512
```

- [ ] **Step 4: Create `.env.local-ollama.example`**

Create this exact file:

```env
TEAM_ENV_PROFILE=local-ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
LLM_MODEL=qwen3:4b-instruct
EMBEDDING_MODEL=bge-m3

QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=llmenhance_chunks

SQLITE_PATH=/app/storage/metadata.sqlite

CHUNK_SIZE=1200
CHUNK_OVERLAP=250
RETRIEVAL_TOP_K=5
TEMPERATURE=0.2
NUM_CTX=4096
NUM_PREDICT=512
```

- [ ] **Step 5: Keep `.env.example` backwards compatible**

Make `.env.example` match `.env.local-ollama.example` exactly. This preserves the local/on-prem default for existing docs and tooling.

- [ ] **Step 6: Ignore generated env backups**

Add this line to `.gitignore`:

```gitignore
.env.backup.*
```

- [ ] **Step 7: Run tests and verify pass**

Run:

```powershell
pytest tests/test_agent_setup_contract.py -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

Run:

```powershell
git add .env.shared-ec2.example .env.local-ollama.example .env.example .gitignore tests/test_agent_setup_contract.py
git commit -m "chore: add reproducible environment profiles"
```

---

### Task 3: Make Setup Script Profile-Driven

**Files:**
- Modify: `scripts/dev_setup.ps1`
- Test: `tests/test_agent_setup_contract.py`

- [ ] **Step 1: Write failing tests for setup profile behavior**

Add these tests to `tests/test_agent_setup_contract.py`:

```python
def test_dev_setup_supports_shared_ec2_profile_without_local_ollama_requirement() -> None:
    script = read_repo_file("scripts/dev_setup.ps1")

    assert "[ValidateSet(\"shared-ec2\", \"local-ollama\")]" in script
    assert "[string]$Profile = \"shared-ec2\"" in script
    assert "[switch]$ForceEnv" in script
    assert ".env.shared-ec2.example" in script
    assert ".env.local-ollama.example" in script
    assert "Test-OllamaEndpoint" in script
    assert "Assert-OllamaModels" in script
    assert "Require-Command \"ollama\"" in script
    assert "if ($Profile -eq \"local-ollama\")" in script


def test_dev_setup_can_backup_existing_env_when_forcing_profile() -> None:
    script = read_repo_file("scripts/dev_setup.ps1")

    assert ".env.backup." in script
    assert "Copy-Item .env $backupPath" in script
    assert "Copy-Item $templatePath .env" in script
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
pytest tests/test_agent_setup_contract.py -v
```

Expected: fails because `scripts/dev_setup.ps1` does not support profiles yet.

- [ ] **Step 3: Replace `scripts/dev_setup.ps1` with profile-aware setup**

Use this implementation:

```powershell
param(
    [ValidateSet("shared-ec2", "local-ollama")]
    [string]$Profile = "shared-ec2",
    [switch]$ForceEnv
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Require-Command {
    param(
        [string]$Name,
        [string]$InstallHint
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is required. $InstallHint"
    }
}

function Read-DotEnv {
    param([string]$Path)

    $values = @{}
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) {
            return
        }
        $parts = $line -split "=", 2
        if ($parts.Count -eq 2) {
            $values[$parts[0]] = $parts[1]
        }
    }
    return $values
}

function Test-OllamaEndpoint {
    param([string]$BaseUrl)

    $tagsUrl = "$BaseUrl/api/tags"
    try {
        return Invoke-RestMethod -Uri $tagsUrl -TimeoutSec 20
    } catch {
        throw "Ollama endpoint is not reachable at $tagsUrl. Check VPN/security group/IP allowlist, then rerun setup."
    }
}

function Assert-OllamaModels {
    param(
        [object]$Tags,
        [string]$LlmModel,
        [string]$EmbeddingModel
    )

    $modelNames = @($Tags.models | ForEach-Object { $_.name })
    if ($modelNames -notcontains $LlmModel) {
        throw "Required LLM model $LlmModel was not found on the configured Ollama endpoint."
    }
    if (($modelNames -notcontains $EmbeddingModel) -and ($modelNames -notcontains "$EmbeddingModel`:latest")) {
        throw "Required embedding model $EmbeddingModel was not found on the configured Ollama endpoint."
    }
}

Write-Step "Checking required local tools"
Require-Command "docker" "Install and start Docker Desktop, then rerun this script."

docker version | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "Docker is installed but not reachable. Start Docker Desktop, then rerun this script."
}

docker compose version | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose is not available through the Docker CLI."
}

$templatePath = ".env.$Profile.example"
if (-not (Test-Path $templatePath)) {
    throw "Environment template not found: $templatePath"
}

Write-Step "Creating .env from $templatePath"
if ((Test-Path ".env") -and $ForceEnv) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupPath = ".env.backup.$timestamp"
    Copy-Item .env $backupPath
    Write-Host "Backed up existing .env to $backupPath"
}

if ((-not (Test-Path ".env")) -or $ForceEnv) {
    Copy-Item $templatePath .env
    Write-Host "Created .env for profile $Profile"
} else {
    Write-Host ".env already exists. Rerun with -ForceEnv to replace it with profile $Profile."
}

$envValues = Read-DotEnv ".env"
$ollamaBaseUrl = $envValues["OLLAMA_BASE_URL"]
$llmModel = $envValues["LLM_MODEL"]
$embeddingModel = $envValues["EMBEDDING_MODEL"]

if ($Profile -eq "local-ollama") {
    Write-Step "Checking local Ollama and pulling required models"
    Require-Command "ollama" "Install Ollama on the Windows host, then rerun this script."
    ollama list | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Ollama is installed but not reachable. Start Ollama on the Windows host."
    }
    ollama pull $embeddingModel
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to pull $embeddingModel."
    }
    ollama pull $llmModel
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to pull $llmModel."
    }
} else {
    Write-Step "Checking shared EC2 Ollama endpoint"
    $tags = Test-OllamaEndpoint $ollamaBaseUrl
    Assert-OllamaModels $tags $llmModel $embeddingModel
    Write-Host "Shared Ollama endpoint is reachable: $ollamaBaseUrl"
}

Write-Step "Building and starting Docker services"
docker compose up -d --build
if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed."
}

Write-Step "Rebuilding local SQLite and Qdrant indexes from datasets/docs"
docker compose run --rm rag-api python scripts/ingest_md.py datasets/docs --reset
if ($LASTEXITCODE -ne 0) {
    throw "Document ingestion failed."
}

Write-Host ""
Write-Host "SETUP_DONE"
Write-Host "Next: run scripts/dev_verify.ps1"
```

- [ ] **Step 4: Run contract tests**

Run:

```powershell
pytest tests/test_agent_setup_contract.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Run shared EC2 setup**

Run:

```powershell
.\scripts\dev_setup.ps1 -Profile shared-ec2 -ForceEnv
```

Expected: script prints `SETUP_DONE`.

- [ ] **Step 6: Commit**

Run:

```powershell
git add scripts/dev_setup.ps1 tests/test_agent_setup_contract.py
git commit -m "chore: make dev setup profile driven"
```

---

### Task 4: Strengthen Verification Script

**Files:**
- Modify: `scripts/dev_verify.ps1`
- Test: `tests/test_agent_setup_contract.py`

- [ ] **Step 1: Write failing tests for endpoint verification**

Add this test to `tests/test_agent_setup_contract.py`:

```python
def test_dev_verify_checks_profile_endpoint_and_models() -> None:
    script = read_repo_file("scripts/dev_verify.ps1")

    assert "Read-DotEnv" in script
    assert "TEAM_ENV_PROFILE" in script
    assert "OLLAMA_BASE_URL" in script
    assert "/api/tags" in script
    assert "qwen3:4b-instruct" in script
    assert "bge-m3" in script
    assert "SETUP_OK" in script
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
pytest tests/test_agent_setup_contract.py -v
```

Expected: fails because `scripts/dev_verify.ps1` does not inspect `.env` or `/api/tags` yet.

- [ ] **Step 3: Add `.env` parsing and model verification to `scripts/dev_verify.ps1`**

Add these functions after `Require-Success`:

```powershell
function Read-DotEnv {
    param([string]$Path)

    $values = @{}
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) {
            return
        }
        $parts = $line -split "=", 2
        if ($parts.Count -eq 2) {
            $values[$parts[0]] = $parts[1]
        }
    }
    return $values
}

function Assert-OllamaEndpoint {
    param(
        [string]$BaseUrl,
        [string]$LlmModel,
        [string]$EmbeddingModel
    )

    $tags = Invoke-RestMethod -Uri "$BaseUrl/api/tags" -TimeoutSec 20
    $modelNames = @($tags.models | ForEach-Object { $_.name })
    if ($modelNames -notcontains $LlmModel) {
        throw "Required LLM model $LlmModel was not found at $BaseUrl."
    }
    if (($modelNames -notcontains $EmbeddingModel) -and ($modelNames -notcontains "$EmbeddingModel`:latest")) {
        throw "Required embedding model $EmbeddingModel was not found at $BaseUrl."
    }
}
```

Then add this block before Docker Compose checks:

```powershell
Write-Step "Checking active environment profile"
if (-not (Test-Path ".env")) {
    throw ".env does not exist. Run scripts/dev_setup.ps1 first."
}

$envValues = Read-DotEnv ".env"
$profile = $envValues["TEAM_ENV_PROFILE"]
$ollamaBaseUrl = $envValues["OLLAMA_BASE_URL"]
$llmModel = $envValues["LLM_MODEL"]
$embeddingModel = $envValues["EMBEDDING_MODEL"]

Write-Host "TEAM_ENV_PROFILE=$profile"
Write-Host "OLLAMA_BASE_URL=$ollamaBaseUrl"
Write-Host "LLM_MODEL=$llmModel"
Write-Host "EMBEDDING_MODEL=$embeddingModel"

Assert-OllamaEndpoint $ollamaBaseUrl $llmModel $embeddingModel
```

- [ ] **Step 4: Run contract tests**

Run:

```powershell
pytest tests/test_agent_setup_contract.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Run full verification**

Run:

```powershell
.\scripts\dev_verify.ps1
```

Expected: script prints `SETUP_OK`.

- [ ] **Step 6: Commit**

Run:

```powershell
git add scripts/dev_verify.ps1 tests/test_agent_setup_contract.py
git commit -m "chore: verify active shared environment"
```

---

### Task 5: Update Agent-Facing README

**Files:**
- Modify: `README.md`
- Create: `docs/TEAM_ENVIRONMENT.md`
- Test: `tests/test_agent_setup_contract.py`

- [ ] **Step 1: Write failing README contract tests**

Replace `test_readme_has_agent_setup_quickstart_contract` with:

```python
def test_readme_has_agent_setup_quickstart_contract() -> None:
    readme = read_repo_file("README.md")

    assert "## Agent Setup Quickstart" in readme
    assert "CLI coding agent" in readme
    assert "shared EC2 Ollama endpoint" in readme
    assert "scripts/dev_setup.ps1 -Profile shared-ec2 -ForceEnv" in readme
    assert "scripts/dev_verify.ps1" in readme
    assert "SETUP_OK" in readme
    assert "Do not move Ollama/Qwen into Docker" in readme
    assert "local-ollama" in readme
    assert "docs/TEAM_ENVIRONMENT.md" in readme
```

Add:

```python
def test_team_environment_doc_exists_and_mentions_security_group() -> None:
    doc = read_repo_file("docs/TEAM_ENVIRONMENT.md")

    assert "shared-ec2" in doc
    assert "local-ollama" in doc
    assert "http://YOUR_EC2_PUBLIC_IP:11434" in doc
    assert "security group" in doc
    assert "SETUP_OK" in doc
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
pytest tests/test_agent_setup_contract.py -v
```

Expected: fails because README and `docs/TEAM_ENVIRONMENT.md` do not contain the new contract yet.

- [ ] **Step 3: Replace README quickstart section**

Use this exact section:

```markdown
## Agent Setup Quickstart

If you are a CLI coding agent asked to set up this project, follow this section exactly.

The default team environment uses the shared EC2 Ollama endpoint. Do not move Ollama/Qwen into Docker. For the MVP, Docker runs the app, Qdrant, SQLite ingestion, and tests locally; Ollama model serving stays outside Docker and is reached through `OLLAMA_BASE_URL`.

From the repository root, run:

```powershell
.\scripts\dev_setup.ps1 -Profile shared-ec2 -ForceEnv
.\scripts\dev_verify.ps1
```

Setup is complete only when `scripts/dev_verify.ps1` prints:

```text
SETUP_OK
```

The shared profile creates `.env` from `.env.shared-ec2.example` and uses:

```env
TEAM_ENV_PROFILE=shared-ec2
OLLAMA_BASE_URL=http://YOUR_EC2_PUBLIC_IP:11434
LLM_MODEL=qwen3:4b-instruct
EMBEDDING_MODEL=bge-m3
```

Use the local Ollama fallback only when the shared EC2 endpoint is unavailable or when explicitly asked:

```powershell
.\scripts\dev_setup.ps1 -Profile local-ollama -ForceEnv
.\scripts\dev_verify.ps1
```

Do not claim setup is complete unless `SETUP_OK` is printed. Do not commit `.env`, `.env.backup.*`, `storage/`, SQLite files, Qdrant vector data, model files, or local credentials.

Detailed team environment notes are in `docs/TEAM_ENVIRONMENT.md`.
```

- [ ] **Step 4: Create `docs/TEAM_ENVIRONMENT.md`**

Create this file:

```markdown
# Team Environment

The default team profile is `shared-ec2`.

```text
local repo + Docker Compose
-> local Qdrant
-> local SQLite metadata
-> shared EC2 Ollama API
-> qwen3:4b-instruct + bge-m3
```

## Profiles

`shared-ec2` is the normal team setup. It does not require local Ollama or local model downloads.

```powershell
.\scripts\dev_setup.ps1 -Profile shared-ec2 -ForceEnv
.\scripts\dev_verify.ps1
```

`local-ollama` preserves the on-prem/local fallback. It requires Ollama on the Windows host and pulls the required models locally.

```powershell
.\scripts\dev_setup.ps1 -Profile local-ollama -ForceEnv
.\scripts\dev_verify.ps1
```

## Shared EC2 Endpoint

```env
OLLAMA_BASE_URL=http://YOUR_EC2_PUBLIC_IP:11434
LLM_MODEL=qwen3:4b-instruct
EMBEDDING_MODEL=bge-m3
```

Verify the endpoint directly:

```powershell
Invoke-RestMethod http://YOUR_EC2_PUBLIC_IP:11434/api/tags
```

## Security Group Access

Ollama does not provide authentication by default. The EC2 security group must keep port `11434` restricted to approved team IP ranges or VPN CIDRs.

If setup fails at `/api/tags`, check whether the current network IP is allowed by the security group. Do not open port `11434` to `0.0.0.0/0`.

## Completion Rule

The environment is considered ready only when:

```text
SETUP_OK
```

is printed by:

```powershell
.\scripts\dev_verify.ps1
```
```

- [ ] **Step 5: Run contract tests**

Run:

```powershell
pytest tests/test_agent_setup_contract.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```powershell
git add README.md docs/TEAM_ENVIRONMENT.md tests/test_agent_setup_contract.py
git commit -m "docs: document team shared EC2 setup"
```

---

### Task 6: End-To-End Verification

**Files:**
- No new files.

- [ ] **Step 1: Reset local env to shared profile**

Run:

```powershell
.\scripts\dev_setup.ps1 -Profile shared-ec2 -ForceEnv
```

Expected: prints `SETUP_DONE`.

- [ ] **Step 2: Verify project setup**

Run:

```powershell
.\scripts\dev_verify.ps1
```

Expected: prints `SETUP_OK`.

- [ ] **Step 3: Run Docker test suite**

Run:

```powershell
docker compose run --rm rag-api pytest -v
```

Expected: all tests pass.

- [ ] **Step 4: Run formatting and whitespace checks**

Run:

```powershell
ruff check .
git diff --check
```

Expected: both commands pass.

- [ ] **Step 5: Check git status**

Run:

```powershell
git status --short
```

Expected: only intentional README, docs, scripts, tests, env template, and `.gitignore` changes are listed. `.env` and `.env.backup.*` are not staged.

- [ ] **Step 6: Final commit**

Run:

```powershell
git add README.md docs/TEAM_ENVIRONMENT.md .env.example .env.shared-ec2.example .env.local-ollama.example .gitignore scripts/dev_setup.ps1 scripts/dev_verify.ps1 tests/test_agent_setup_contract.py
git commit -m "chore: standardize team development environment"
```

---

## Self-Review

- Spec coverage: The plan covers README-driven agent setup, team-shared EC2 endpoint use, local-only env generation, local Ollama fallback, verification, and tests.
- Placeholder scan: Elastic IP allocation in Task 1 is complete; the current working endpoint `http://YOUR_EC2_PUBLIC_IP:11434` is used everywhere else so the implementation can proceed without guessing.
- Type consistency: Profile names are consistently `shared-ec2` and `local-ollama`; model names are consistently `qwen3:4b-instruct` and `bge-m3`; success markers are consistently `SETUP_DONE` and `SETUP_OK`.

Plan complete and saved to `docs/superpowers/plans/2026-06-19-team-shared-ec2-environment.md`.

Two execution options:

1. Subagent-Driven (recommended) - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. Inline Execution - execute tasks in this session using executing-plans, batch execution with checkpoints.
