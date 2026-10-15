# 把本地已经 commit 的版本部署进 Docker 卷（含卷上的 Git 检出）。
# 不拷源码文件，避免天锐密文进入容器。
#
# 在仓库根目录 rayher-logistics-main 执行:
#   powershell -File .\scripts\deploy-to-docker.ps1
#   powershell -File .\scripts\deploy-to-docker.ps1 -DryRun
#   powershell -File .\scripts\deploy-to-docker.ps1 -Migrate
#   powershell -File .\scripts\deploy-to-docker.ps1 -FromGitHub
#   powershell -File .\scripts\deploy-to-docker.ps1 -Force
#
# 默认: 本地 HEAD -> git bundle -> 容器 Git reset 到同一 commit -> 按需 yarn build -> 清缓存。
# 未 commit 的本地改动不会进 Docker。GitHub 不是必须，没 push 也能部署。
#
# 唯一的开发流程: 本地工作区修改 -> 本地 git commit -> 本脚本部署。
# 本脚本每次都会: 检查要部署的提交里没有天锐密文 / 非 UTF-8 文本;
# 在容器的 Git 里装上禁止 commit 的钩子, 容器里不能直接改代码提交。

[CmdletBinding()]
param(
    [string]$Commit = "HEAD",
    [string]$Container = "rayher-bench",
    [string]$Site = "rayher.localhost",
    [switch]$FromGitHub,
    [switch]$Migrate,
    [switch]$SkipBuild,
    [switch]$Force,
    [switch]$DryRun,
    [switch]$InitializeLocal
)

$ErrorActionPreference = "Stop"
$AppPath = "/workspace/development/frappe-bench/apps/rayher_hr_payroll"
$BenchPath = "/workspace/development/frappe-bench"

function Get-RepoRoot {
    $here = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
    return (Resolve-Path (Join-Path $here "..")).Path
}

function Test-TipRayEncrypted {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $false }
    $fs = [System.IO.File]::Open($Path, "Open", "Read", "ReadWrite")
    try {
        $buf = New-Object byte[] 16
        $n = $fs.Read($buf, 0, 16)
        if ($n -lt 16) { return $false }
        $mark = [System.Text.Encoding]::ASCII.GetString($buf)
        return $mark.StartsWith("%TSD-Header-###%")
    }
    finally {
        $fs.Close()
    }
}

function Get-PlainCopy {
    param([string]$Path)
    if (-not (Test-TipRayEncrypted $Path)) { return $Path }
    throw "TipRay ciphertext detected: $Path. Deployment stopped; recreate and verify a plaintext Git bundle locally. cmd type cannot decrypt this file."
}

function Invoke-GitLocal {
    param([string[]]$GitArgs)
    & git -C $script:RepoRoot @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw ("local git failed: git " + ($GitArgs -join " "))
    }
}

function Invoke-Docker {
    param([string[]]$Cmd)
    & docker @Cmd
    if ($LASTEXITCODE -ne 0) {
        throw ("docker failed: docker " + ($Cmd -join " "))
    }
}

function Get-DockerOutput {
    param([string[]]$Cmd)
    $text = & docker @Cmd
    if ($LASTEXITCODE -ne 0) {
        throw ("docker failed: docker " + ($Cmd -join " "))
    }
    return (($text | Out-String).Trim())
}

function Test-GitAncestor {
    param([string]$MaybeAncestor, [string]$Descendant)
    & git -C $script:RepoRoot merge-base --is-ancestor $MaybeAncestor $Descendant | Out-Null
    return ($LASTEXITCODE -eq 0)
}

$script:RepoRoot = Get-RepoRoot
if (-not (Test-Path (Join-Path $script:RepoRoot ".git"))) {
    throw "local git repo not found: $script:RepoRoot"
}

$localSha = (Invoke-GitLocal -GitArgs @("rev-parse", $Commit) | Select-Object -Last 1).Trim()
$localShort = (Invoke-GitLocal -GitArgs @("rev-parse", "--short", $Commit) | Select-Object -Last 1).Trim()
$localBranch = (Invoke-GitLocal -GitArgs @("rev-parse", "--abbrev-ref", "HEAD") | Select-Object -Last 1).Trim()
$localSubject = (Invoke-GitLocal -GitArgs @("log", "-1", "--format=%s", $localSha) | Select-Object -Last 1).Trim()

Write-Host "checking $localShort for TipRay ciphertext and non-UTF-8 text..."
& python (Join-Path $script:RepoRoot "scripts\check_plaintext.py") --commit $localSha
if ($LASTEXITCODE -ne 0) {
    throw "commit $localShort contains encrypted or non-UTF-8 files. Fix them locally, commit, then deploy again. Never patch them inside Docker."
}

if ($InitializeLocal) {
    if ($FromGitHub -or $Force -or $Commit -ne "HEAD") {
        throw "InitializeLocal requires current local HEAD, without FromGitHub or Force."
    }
    if ((Invoke-GitLocal -GitArgs @("status", "--porcelain") | Out-String).Trim()) {
        throw "Commit local deployment files before initializing Docker."
    }
    if ($PSBoundParameters.ContainsKey("Container") -or $PSBoundParameters.ContainsKey("Site")) {
        throw "InitializeLocal uses isolated planck-logistics-bench / logistics.localhost targets."
    }
    $Container = "planck-logistics-bench"
    $Site = "logistics.localhost"
    $initializeArgs = @("--commit", $localSha)
    if ($DryRun) { $initializeArgs += "--dry-run" }
    & python (Join-Path $script:RepoRoot "scripts\initialize_local_docker.py") @initializeArgs
    if ($LASTEXITCODE -ne 0) { throw "Local Docker initialization failed; volumes were preserved." }
    if ($DryRun) { exit 0 }
}

$dockerSha = Get-DockerOutput -Cmd @("exec", "-w", $AppPath, $Container, "git", "rev-parse", "HEAD")
$dockerShort = Get-DockerOutput -Cmd @("exec", "-w", $AppPath, $Container, "git", "rev-parse", "--short", "HEAD")
$dockerBranch = Get-DockerOutput -Cmd @("exec", "-w", $AppPath, $Container, "git", "rev-parse", "--abbrev-ref", "HEAD")
$dockerDirty = Get-DockerOutput -Cmd @("exec", "-w", $AppPath, $Container, "git", "status", "--porcelain")
$localDirty = (Invoke-GitLocal -GitArgs @("status", "--porcelain") | Out-String)

$changed = @()
if ($dockerSha -ne $localSha) {
    $changed = @(Invoke-GitLocal -GitArgs @("diff", "--name-only", $dockerSha, $localSha))
}

# The bundles under rayher_hr_payroll/public/frontend/ are tracked in Git and the committed
# copies lag behind the source, so the git reset below always reverts the container to a stale
# build. Rebuild every time unless explicitly skipped.
$needBuild = -not $SkipBuild

$suggestMigrate = $false
foreach ($path in $changed) {
    if ($path -match "(^|/)patches\.txt$|doctype/.+\.json$|(^|/)hooks\.py$|(^|/)patches/") {
        $suggestMigrate = $true
        break
    }
}

$mode = "local git bundle (no source copy)"
if ($FromGitHub) { $mode = "GitHub fetch" }
$buildLabel = "no"
if ($needBuild) { $buildLabel = "yes" }
$migrateLabel = "no"
if ($Migrate) { $migrateLabel = "yes" }

Write-Host ""
Write-Host "==== deploy plan ===="
Write-Host "local repo : $script:RepoRoot"
Write-Host ("local     : {0} {1}  {2}" -f $localBranch, $localShort, $localSubject)
Write-Host ("Docker    : {0} {1}" -f $dockerBranch, $dockerShort)
Write-Host "target SHA: $localSha"
Write-Host "transfer  : $mode"
Write-Host "frontend  : $buildLabel"
Write-Host "migrate   : $migrateLabel"
if ($suggestMigrate -and -not $Migrate) {
    Write-Host "note      : patches/DocType/hooks changed; add -Migrate if database schema must update"
}
if ($localDirty.Trim()) {
    Write-Host ""
    Write-Host ("note: local worktree has uncommitted files; only committed {0} will be deployed" -f $localShort)
}

$dockerSourceDirty = @()
$syncedGeneratedDeclaration = $false
foreach ($line in ($dockerDirty -split "`n")) {
    $item = $line.Trim()
    if (-not $item) { continue }
    if ($item -match "public/frontend/|www/rayher\.html$") { continue }
    # unplugin-vue-components updates this tracked declaration during a build.
    # Accept it only after its exact bytes have been committed locally.
    if ($item -eq "M frontend/components.d.ts") {
        $targetBlob = (& git -C $script:RepoRoot rev-parse ($localSha + ":frontend/components.d.ts")).Trim()
        $dockerBlob = Get-DockerOutput -Cmd @("exec", "-w", $AppPath, $Container, "git", "hash-object", "--no-filters", "frontend/components.d.ts")
        if ($targetBlob -eq $dockerBlob) {
            $syncedGeneratedDeclaration = $true
            Write-Host "generated component declaration is already preserved in the local target commit"
            continue
        }
    }
    $dockerSourceDirty += $item
}
if ($dockerSourceDirty.Count -gt 0) {
    Write-Host ""
    Write-Host "Docker source worktree is dirty (excluding frontend build output):"
    foreach ($item in $dockerSourceDirty) { Write-Host "  $item" }
    if (-not $Force) {
        throw "refusing to overwrite dirty Docker source. Someone edited code inside Docker. Bring those edits into the local repo and commit them there first; rerun with -Force only after confirming nothing in Docker needs keeping."
    }
}

if ($dockerSha -eq $localSha -and -not $needBuild -and -not $Migrate) {
    Write-Host ""
    Write-Host "Docker is already on this commit; no build/migrate requested. Nothing to deploy."
    exit 0
}

if ($DryRun) {
    Write-Host ""
    Write-Host "DryRun: stopping before any Docker change."
    if ($changed.Count -gt 0) {
        Write-Host "files that would update:"
        foreach ($path in $changed) { Write-Host "  $path" }
    }
    exit 0
}

if ($dockerSha -ne $localSha) {
    $isAncestor = Test-GitAncestor $dockerSha $localSha
    if (-not $isAncestor -and -not $Force) {
        throw ("Docker {0} is not an ancestor of local {1} (diverged). Something was committed in Docker without this script. Do not copy files or commit inside Docker: fetch Docker's history (git bundle), merge it into the local branch, commit, then deploy again. Use -Force only if local should overwrite Docker." -f $dockerShort, $localShort)
    }

    if ($FromGitHub) {
        Write-Host ""
        Write-Host ("fetching {0} from GitHub..." -f $localSha)
        Invoke-Docker -Cmd @("exec", "-w", $AppPath, $Container, "git", "fetch", "origin")
        & docker exec -w $AppPath $Container git cat-file -e $localSha
        if ($LASTEXITCODE -ne 0) {
            throw ("GitHub does not have {0} yet. Push first, or omit -FromGitHub to use a local bundle." -f $localShort)
        }
    }
    else {
        $bundle = Join-Path $env:TEMP ("rayher-deploy-{0}.bundle" -f $localShort)
        if (Test-Path $bundle) { Remove-Item -Force $bundle }
        Write-Host ""
        Write-Host "creating local bundle: $bundle"
        # a bundle carries refs, not bare SHAs, so publish the target under a temp ref first
        $deployRef = "refs/rayher-deploy/target"
        Invoke-GitLocal -GitArgs @("update-ref", $deployRef, $localSha)
        try {
            if ($isAncestor) {
                Invoke-GitLocal -GitArgs @("bundle", "create", $bundle, $deployRef, ("^" + $dockerSha))
            }
            else {
                Invoke-GitLocal -GitArgs @("bundle", "create", $bundle, $deployRef)
            }
        }
        finally {
            Invoke-GitLocal -GitArgs @("update-ref", "-d", $deployRef)
        }
        $bundle = Get-PlainCopy $bundle
        Invoke-Docker -Cmd @("cp", $bundle, ($Container + ":/tmp/rayher-deploy.bundle"))
        Invoke-Docker -Cmd @("exec", "-w", $AppPath, $Container, "git", "fetch", "/tmp/rayher-deploy.bundle", ($deployRef + ":refs/remotes/local-deploy/HEAD"))
    }

    if ($syncedGeneratedDeclaration) {
        # Recheck after transfer; staging the already-committed target bytes lets
        # checkout carry the generated file forward without discarding a change.
        $currentBlob = Get-DockerOutput -Cmd @("exec", "-w", $AppPath, $Container, "git", "hash-object", "--no-filters", "frontend/components.d.ts")
        $incomingBlob = Get-DockerOutput -Cmd @("exec", "-w", $AppPath, $Container, "git", "rev-parse", ($localSha + ":frontend/components.d.ts"))
        if ($currentBlob -ne $incomingBlob) { throw "generated declaration changed during deployment; stopping" }
        Invoke-Docker -Cmd @("exec", "-w", $AppPath, $Container, "git", "add", "--", "frontend/components.d.ts")
    }

    Write-Host ("checking out {0} into the Docker volume Git worktree..." -f $localShort)
    Invoke-Docker -Cmd @("exec", "-w", $AppPath, $Container, "git", "checkout", "-B", $localBranch, $localSha)
    Invoke-Docker -Cmd @("exec", "-w", $AppPath, $Container, "git", "reset", "--hard", $localSha)
    Invoke-Docker -Cmd @("exec", "-w", $AppPath, $Container, "git", "clean", "-fd", "--", "frontend", "rayher_hr_payroll/public/frontend", "rayher_hr_payroll/www")
}

# Code changes reach Docker only through this script, so any commit made inside the container is refused.
Write-Host "installing the no-commit guard in the Docker Git checkout..."
$guard = "printf '%s\n' '#!/bin/sh' 'echo Committing inside Docker is not allowed. >&2' 'echo Edit in the local worktree, git commit locally, then run scripts/deploy-to-docker.ps1. >&2' 'exit 1' > .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit && cp .git/hooks/pre-commit .git/hooks/pre-merge-commit && (git config --unset core.hooksPath || true)"
Invoke-Docker -Cmd @("exec", "-w", $AppPath, $Container, "sh", "-c", $guard)

$newSha = Get-DockerOutput -Cmd @("exec", "-w", $AppPath, $Container, "git", "rev-parse", "HEAD")
if ($newSha -ne $localSha) {
    throw ("Docker HEAD is {0}, expected {1}" -f $newSha, $localSha)
}

if ($needBuild) {
    Write-Host ""
    Write-Host "building frontend inside the container..."
    Invoke-Docker -Cmd @("exec", "-w", ($AppPath + "/frontend"), $Container, "yarn", "build")
}

if ($Migrate) {
    Write-Host ""
    Write-Host "migrating $Site ..."
    Invoke-Docker -Cmd @("exec", "-w", $BenchPath, $Container, "bench", "--site", $Site, "migrate")
}

Write-Host "clearing cache..."
Invoke-Docker -Cmd @("exec", "-w", $BenchPath, $Container, "bench", "--site", $Site, "clear-cache")
Invoke-Docker -Cmd @("exec", "-w", $BenchPath, $Container, "bench", "--site", $Site, "clear-website-cache")

# 发票识别服务（PaddleOCR）连通性检查（2026-09-28）：8 月 28 日系统容器重建时没接回识别服务的
# 内部网络，之后上传的发票都识别不了，直到 9 月 24 日才发现。每次部署顺便检查，连不上就接上并提示。
$OcrNetwork = "rayher-ocr-internal"
$ocr = "skipped (no $OcrNetwork network)"
$ocrNetworks = Get-DockerOutput -Cmd @("network", "ls", "--filter", ("name=^" + $OcrNetwork + "$") , "--format", "{{.Name}}")
if (($ocrNetworks -split "`n") -contains $OcrNetwork) {
    & docker exec $Container getent hosts invoice-ocr *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "OCR sidecar not reachable from $Container; connecting it to $OcrNetwork ..."
        Invoke-Docker -Cmd @("network", "connect", $OcrNetwork, $Container)
    }
    $ocr = & docker exec $Container curl -fsS -m 10 http://invoice-ocr:8080/health
    if ($LASTEXITCODE -ne 0) {
        $ocr = "NOT REACHABLE - invoice recognition will fail; check the rayher-invoice-ocr container"
    }
}

$ping = Get-DockerOutput -Cmd @("exec", $Container, "curl", "-fsS", "-H", ("Host: " + $Site), "http://127.0.0.1:8000/api/method/ping")
$finalSha = Get-DockerOutput -Cmd @("exec", "-w", $AppPath, $Container, "git", "rev-parse", "--short", "HEAD")

Write-Host ""
Write-Host "==== deploy done ===="
Write-Host ("Docker Git : {0} {1} (matches local {2})" -f $dockerBranch, $finalSha, $localShort)
Write-Host "Ping       : $ping"
Write-Host "OCR        : $ocr"
if ($Container -eq "planck-logistics-bench") {
    Write-Host "Site       : http://localhost:8082/planck-semicon"
} else {
    Write-Host ("Site       : http://{0}:8000 (check container port mapping)" -f $Site)
}
Write-Host "Note       : frontend build output may stay uncommitted in Docker; do not edit product source inside the container."
Write-Host ""
