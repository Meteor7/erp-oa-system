# Local Windows deployment

This creates an isolated development site using Frappe/ERPNext/HRMS version-15 and the locally committed custom app. It does not restore production backups or load employee/payroll data. The official bench v5.31.0 image is pinned by digest; Python 3.12 and Node 22 are selected for v15.

Prerequisites: firmware virtualization enabled, Docker Desktop Linux engine healthy using WSL 2 or Docker VMM (`docker info`), Git and Python in PATH. All frontend dependency installation and builds run in Docker.

## First initialization

The ignored `.local/logistics.env` contains generated `LOCAL_DB_ROOT_PASSWORD` and `LOCAL_ADMIN_PASSWORD`. Login is `Administrator` with `LOCAL_ADMIN_PASSWORD`. Preserve these values for the life of the local volumes. Do not commit or share this file.

From the repository root, after committing changes locally:

```powershell
$env:PATH = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin;$env:PATH"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-to-docker.ps1 -InitializeLocal -DryRun
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-to-docker.ps1 -InitializeLocal
```

DryRun validates Compose and committed source without starting services. Initialization transfers source only through a local Git bundle, installs a fresh site, then continues through the existing deploy script to build the frontend, install the no-commit guard, clear caches and check HTTP. Database volumes are preserved on failures. No GitHub credential is sent into Docker.

After verification, open <http://localhost:8082/planck-semicon>; `/app` opens ERPNext administration/setup. WebSockets use local port 9082. Database and Redis ports are not published. Configure company, employees and approval positions before using dependent business workflows. Email and scheduled jobs are disabled initially.

## Subsequent deployment and service management

```powershell
# Edit safely and commit locally first.
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-to-docker.ps1 -Container planck-logistics-bench -Site logistics.localhost -DryRun
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-to-docker.ps1 -Container planck-logistics-bench -Site logistics.localhost -Migrate

docker compose --env-file .local/logistics.env -f deploy/docker-compose.local.yml up -d
docker compose --env-file .local/logistics.env -f deploy/docker-compose.local.yml ps
```

Do not use `down -v`; it removes the local database and bench volumes. Optional `LOCAL_HTTP_PROXY` / `LOCAL_HTTPS_PROXY` in the env file must be reachable from containers; the host's 127.0.0.1 is not the container proxy address. Docker image-pull proxy settings are configured separately in Docker Desktop.

The optional PaddleOCR service in `deploy/docker-compose.invoice-ocr.yml` is not initialized here. Invoice recognition requires building that service, connecting its network and passing its real-model readiness check.

A second clone must create `.local/logistics.env` with independently generated random values using the AGENTS.md safe writer and verify the Git raw blob hash. The initialization command requires a clean local commit. It never pushes GitHub changes.

Preparation and static validation do not prove the site is running: image pull, dependency installation, fresh-site hooks, frontend compilation, API checks and browser verification must each finish on a working Linux engine.

Upstream reference: [Frappe Docker development setup](https://github.com/frappe/frappe_docker/blob/main/docs/05-development/04-alternate-setup.md).
