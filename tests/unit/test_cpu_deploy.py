"""Verify deployment fails before startup and never builds or pulls images."""

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ARCH = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
pytestmark = pytest.mark.skipif(platform.system() != "Linux" or ARCH is None, reason="Linux amd64/arm64 deployment")


@pytest.fixture
def deployment(tmp_path):
    """Create loaded-image fixtures without using a real Docker daemon."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("deploy_cpu.sh", "cpu_docker_common.sh"):
        shutil.copy2(ROOT / "scripts" / name, scripts / name)
    tools = tmp_path / "bin"
    tools.mkdir()
    docker = tools / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "with open(os.environ['DOCKER_CALLS'],'a') as log: log.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "if sys.argv[1] == 'info': print('linux/'+os.environ.get('DAEMON_ARCH',os.environ['HOST_ARCH']))\n"
        "elif sys.argv[1:3] == ['image','inspect']:\n"
        " if os.environ.get('MISSING_IMAGE'): sys.exit(1)\n"
        " print(os.environ.get('IMAGE_ARCH',os.environ['HOST_ARCH']))\n"
    )
    docker.chmod(0o755)
    models = tmp_path / "models"
    models.mkdir()
    for name in ("asr.gguf", "llm.gguf", "server.crt", "server.key"):
        (models / name).write_text("fixture")
    settings = tmp_path / ".env.cpu"
    settings.write_text(
        f"CPU_IMAGE_VERSION=test\nCPU_MODELS_DIR={models}\n"
        f"NEMO_ASR_MODEL_FILE=asr.gguf\nLLM_MODEL_FILE=llm.gguf\n"
        f"VOICE_AGENT_TLS_CERT={models}/server.crt\nVOICE_AGENT_TLS_KEY={models}/server.key\n"
    )
    original_env = tmp_path / ".env"
    original_env.write_text("HOST_NATIVE_ENV=preserve\n")
    calls = tmp_path / "docker-calls.jsonl"
    env = {**os.environ, "PATH": f"{tools}:{os.environ['PATH']}", "DOCKER_CALLS": str(calls), "HOST_ARCH": ARCH}
    env.pop("CPU_DEPLOY_ENV", None)

    def run(**overrides):
        result = subprocess.run(
            ["bash", str(scripts / "deploy_cpu.sh"), "up"], env={**env, **overrides}, capture_output=True, text=True
        )
        invoked = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
        assert original_env.read_text() == "HOST_NATIVE_ENV=preserve\n"
        return result, invoked

    return run, models


def test_loaded_images_start_without_build_or_pull(deployment):
    """Start only the four CPU services with offline deployment flags."""
    run, _ = deployment
    result, calls = run()
    assert result.returncode == 0, result.stderr
    startup = [args for args in calls if args[0] == "compose"]
    assert len(startup) == 1
    assert "--no-build" in startup[0] and "--wait" in startup[0]
    assert startup[0][startup[0].index("--pull") + 1] == "never"
    assert startup[0][-4:] == ["cpu-asr", "cpu-llm", "cpu-tts", "cpu-app"]
    assert not any(args[0] in ("build", "pull", "load") for args in calls)


@pytest.mark.parametrize("failure", ["MISSING_IMAGE", "IMAGE_ARCH", "DAEMON_ARCH"])
def test_invalid_loaded_environment_does_not_start(deployment, failure):
    """Reject missing images and incompatible architectures before Compose startup."""
    run, _ = deployment
    value = "1" if failure == "MISSING_IMAGE" else ("arm64" if ARCH == "amd64" else "amd64")
    result, calls = run(**{failure: value})
    assert result.returncode != 0
    assert not any(args[0] == "compose" for args in calls)


def test_missing_tls_does_not_start(deployment):
    """Refuse to start services when the trusted TLS files are absent."""
    run, models = deployment
    (models / "server.key").unlink()
    result, calls = run()
    assert result.returncode != 0 and "Missing absolute model/TLS path" in result.stderr
    assert not any(args[0] == "compose" for args in calls)
