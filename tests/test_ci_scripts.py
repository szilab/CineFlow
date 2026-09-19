"""Regression tests for CI helper scripts."""

from pathlib import Path
import os
import shutil
import stat
import subprocess


def test_docker_build_retries_registry_push_failures(tmp_path) -> None:
    project_root = tmp_path
    scripts_dir = project_root / ".github" / "scripts"
    scripts_dir.mkdir(parents=True)
    dist_dir = project_root / "dist"
    dist_dir.mkdir()

    repo_root = Path(__file__).resolve().parents[1]
    shutil.copy2(repo_root / ".github" / "scripts" / "docker-build.sh", scripts_dir / "docker-build.sh")
    shutil.copy2(repo_root / ".github" / "scripts" / "utils.sh", scripts_dir / "utils.sh")

    (project_root / "pyproject.toml").write_text("[project]\nname='cineflow'\n", encoding="utf-8")
    (project_root / "VERSION").write_text("2.2.0\n", encoding="utf-8")
    (dist_dir / "cineflow-2.2.0-py3-none-any.whl").write_text("", encoding="utf-8")

    fakebin = project_root / "fakebin"
    fakebin.mkdir()
    log_path = project_root / "docker.log"
    push_count_path = project_root / "push-count.txt"

    docker_script = fakebin / "docker"
    docker_script.write_text(
        f"""#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "{log_path}"
case "$1" in
  build|tag)
    exit 0
    ;;
  push)
    count=0
    if [ -f "{push_count_path}" ]; then
      count=$(cat "{push_count_path}")
    fi
    count=$((count + 1))
    printf '%s' "$count" > "{push_count_path}"
    if [ "$count" -eq 1 ]; then
      echo "unknown blob" >&2
      exit 1
    fi
    exit 0
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    docker_script.chmod(docker_script.stat().st_mode | stat.S_IEXEC)

    sleep_script = fakebin / "sleep"
    sleep_script.write_text(
        f"""#!/bin/sh
printf 'sleep %s\\n' "$*" >> "{log_path}"
""",
        encoding="utf-8",
    )
    sleep_script.chmod(sleep_script.stat().st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fakebin}{os.pathsep}{env['PATH']}",
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY_OWNER": "szilab",
            "GITHUB_REF": "refs/heads/main",
        }
    )

    result = subprocess.run(
        ["bash", str(scripts_dir / "docker-build.sh")],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "Retrying in 5s" in result.stdout
    assert log_path.read_text(encoding="utf-8").splitlines().count("push ghcr.io/szilab/cineflow:2.2.0") == 2
