# Team Environment

The default team profile is `shared-ec2`.

```text
local repo + Docker Compose
-> local Qdrant
-> local Qdrant payload metadata + parent expansion
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
TEAM_ENV_PROFILE=shared-ec2
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
