"""Initialize this machine's isolated Frappe bench through the deployment entry point."""
from pathlib import Path
import argparse
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = "planck-logistics-bench"
SITE = "logistics.localhost"
BENCH = "/workspace/development/frappe-bench"


def run(*args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    env_file = ROOT / ".local/logistics.env"
    if not env_file.is_file():
        raise SystemExit("Missing .local/logistics.env; see deploy/LOCAL-DEPLOYMENT.md")
    compose = ("docker", "compose", "--env-file", str(env_file), "-f", str(ROOT / "deploy/docker-compose.local.yml"))
    run(*compose, "config", "--quiet")
    if args.dry_run:
        print("Local initialization plan: fresh Frappe/ERPNext/HRMS v15; no business data restore.")
        print("HTTP 127.0.0.1:8082; WebSocket 127.0.0.1:9082; private database and Redis.")
        print("Only local commit", args.commit, "will enter Docker through a Git bundle.")
        print("DryRun complete; no Docker services were started.")
        return
    engine = run("docker", "info", "--format", "{{.OSType}}", capture_output=True, text=True).stdout.strip()
    if engine != "linux":
        raise SystemExit("Docker must be running Linux containers.")
    ref = "refs/heads/local-bootstrap-deploy"
    existing = subprocess.run(["git", "show-ref", "--verify", "--quiet", ref], cwd=ROOT)
    if existing.returncode == 0:
        raise SystemExit("Temporary deployment ref already exists; inspect it before retrying.")
    bundle = ROOT / ".local/logistics-source.bundle"
    run("git", "update-ref", ref, args.commit)
    try:
        run("git", "bundle", "create", str(bundle), ref)
    finally:
        run("git", "update-ref", "-d", ref)
    run("git", "bundle", "verify", str(bundle))
    run(*compose, "up", "-d", "--wait")
    run("docker", "exec", "-u", "root", CONTAINER, "chown", "frappe:frappe", "/workspace/development")
    run("docker", "cp", str(bundle), CONTAINER + ":/tmp/logistics-source.bundle")
    launcher = r"""
set -eo pipefail
source "$NVM_DIR/nvm.sh"
nvm use 22
cd /workspace/development
if [[ ! -d frappe-bench ]]; then
    pyver=$(pyenv latest 3.12)
    bench init frappe-bench --frappe-branch version-15 --python "$PYENV_ROOT/versions/$pyver/bin/python" --skip-redis-config-generation --skip-assets
fi
cd frappe-bench
# A Desktop restart may interrupt first-time dependency installation after
# bench creates its directory. Resume through bench's own installer.
if [[ ! -s sites/apps.txt ]] || ! ./env/bin/python -c 'import frappe' >/dev/null 2>&1; then
    if [[ ! -f apps/frappe/pyproject.toml || ! -x env/bin/python ]]; then
        echo 'Incomplete framework checkout or Python environment; inspect the preserved bench.' >&2
        exit 1
    fi
    bench setup requirements frappe
fi
if [[ ! -d apps/rayher_hr_payroll/.git ]]; then
    git clone --branch local-bootstrap-deploy /tmp/logistics-source.bundle apps/rayher_hr_payroll
fi
actual=$(git -C apps/rayher_hr_payroll rev-parse HEAD)
if [[ "$actual" != "$LOCAL_DEPLOY_SHA" ]]; then
    echo 'Existing local app has a different commit; use the regular deployment workflow first.' >&2
    exit 1
fi
bash apps/rayher_hr_payroll/deploy/local-bootstrap.sh
"""
    run("docker", "exec", "-i", "-e", "LOCAL_DEPLOY_SHA=" + args.commit,
        CONTAINER, "bash", "-s", input=launcher.encode("utf-8"))
    for attempt in range(30):
        result = subprocess.run(["docker", "exec", CONTAINER, "curl", "-fsS", "-H", "Host: " + SITE,
                                 "http://127.0.0.1:8000/api/method/ping"], capture_output=True)
        if result.returncode == 0:
            print("Local Frappe HTTP is ready; continuing the official deployment workflow.")
            return
        time.sleep(2)
    raise SystemExit("Local Frappe HTTP did not become ready; inspect container logs. Volumes are preserved.")


if __name__ == "__main__":
    main()
