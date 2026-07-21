# 发票 OCR 部署、验收与回滚手册

本手册适用于 Windows 主机 `D:\rayher`、现有 `D:\rayher\rayher-compose.yml` 和站点 `rayher.localhost`。所有正式操作都必须使用已经通过隔离验收的 Git SHA；不要从有未提交修改的目录部署。下面命令不会开放 OCR 主机端口，也不会删除 Docker 数据卷。

## 1. 变量与部署前核对

在 PowerShell 中设置本次唯一目录。`$InvoiceOcrSource` 必须指向已经检出验收 SHA 的源码目录。

```powershell
$InvoiceOcrSource = "D:\rayher\.worktrees\invoice-ocr-reimbursement"
$InvoiceOcrCompose = Join-Path $InvoiceOcrSource "deploy\docker-compose.invoice-ocr.yml"
$env:INVOICE_OCR_BUILD_CONTEXT = (Join-Path $InvoiceOcrSource "services\invoice_ocr") -replace '\\','/'
$InvoiceOcrMainCompose = "D:\rayher\rayher-compose.yml"
$InvoiceOcrStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$InvoiceOcrBackup = "D:\rayher\backups\invoice-ocr\$InvoiceOcrStamp"
$AcceptedSha = git -C $InvoiceOcrSource rev-parse HEAD
New-Item -ItemType Directory -Path $InvoiceOcrBackup | Out-Null

git -C $InvoiceOcrSource status --short
git -C $InvoiceOcrSource show --no-patch --oneline $AcceptedSha
docker compose -p rayher -f $InvoiceOcrMainCompose -f $InvoiceOcrCompose config --quiet
```

若 `status --short` 有输出、SHA 与验收记录不一致，或者 Compose 校验失败，应停止操作。

## 2. 构建与首次模型联网预热

正式 sidecar 只在 `internal: true` 网络内，无法下载模型。因此首次模型联网预热必须用一次性容器完成；模型只写入命名卷 `rayher-invoice-ocr-models`。

```powershell
docker compose -p rayher -f $InvoiceOcrMainCompose -f $InvoiceOcrCompose build invoice-ocr
docker volume create rayher-invoice-ocr-models
docker run --rm --network bridge --mount type=volume,source=rayher-invoice-ocr-models,target=/models rayher/invoice-ocr:0.1.0 python -c "from invoice_ocr.engine import PaddleOCREngine; PaddleOCREngine(); print('model cache ready')"
```

联网预热成功后，立即做一次无网络加载验证。此命令成功才说明正式内网启动不会临时联网：

```powershell
docker run --rm --network none --mount type=volume,source=rayher-invoice-ocr-models,target=/models rayher/invoice-ocr:0.1.0 python -c "from invoice_ocr.engine import PaddleOCREngine; PaddleOCREngine(); print('offline model cache ready')"
```

模型卷是可复用缓存。失败时保留它供排查，不要把模型或样本复制到 Git。

## 3. 正式内网启动与 health 检查

```powershell
docker compose -p rayher -f $InvoiceOcrMainCompose -f $InvoiceOcrCompose up -d invoice-ocr
docker compose -p rayher -f $InvoiceOcrMainCompose -f $InvoiceOcrCompose ps invoice-ocr
docker run --rm --network rayher-ocr-internal rayher/invoice-ocr:0.1.0 python -c "import urllib.request; print(urllib.request.urlopen('http://invoice-ocr:8080/health', timeout=3).read().decode())"
```

预期 health 返回 `{"status":"ok","engine":"paddleocr"}`。确认 `docker compose ps` 中 sidecar 没有已发布端口；完成下一节备份后，第 6 节才会把 `rayher-bench` 同时接入原业务网络和 `rayher-ocr-internal`。

## 4. 正式变更前备份

依次备份数据库、站点文件、private files、应用目录、站点配置和当前 Compose。任何一步失败或产物为 0 字节都停止部署。

```powershell
Copy-Item -LiteralPath $InvoiceOcrMainCompose -Destination (Join-Path $InvoiceOcrBackup "rayher-compose.yml")

docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench && bench --site rayher.localhost backup --with-files --compress"
docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench && tar -czf /tmp/site-backups-$InvoiceOcrStamp.tgz sites/rayher.localhost/private/backups"
docker cp "rayher-bench:/tmp/site-backups-$InvoiceOcrStamp.tgz" (Join-Path $InvoiceOcrBackup "site-backups.tgz")

docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench/sites/rayher.localhost/private && tar --exclude='./backups' -czf /tmp/private-files-$InvoiceOcrStamp.tgz files"
docker cp "rayher-bench:/tmp/private-files-$InvoiceOcrStamp.tgz" (Join-Path $InvoiceOcrBackup "private-files.tgz")

docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench && tar -czf /tmp/rayher-app-$InvoiceOcrStamp.tgz apps/rayher_hr_payroll"
docker cp "rayher-bench:/tmp/rayher-app-$InvoiceOcrStamp.tgz" (Join-Path $InvoiceOcrBackup "rayher-app.tgz")
docker cp "rayher-bench:/workspace/development/frappe-bench/sites/rayher.localhost/site_config.json" (Join-Path $InvoiceOcrBackup "site_config.json")

Get-ChildItem -LiteralPath $InvoiceOcrBackup | Select-Object Name,Length
Get-FileHash -Algorithm SHA256 (Join-Path $InvoiceOcrBackup "*")
```

在变更记录中保存备份目录、文件大小、SHA256、验收 Git SHA 和 `rayher/invoice-ocr:0.1.0` 的镜像 digest。

## 5. 应用受审差异

从基线 `11c018f` 到验收 SHA 生成受限补丁，只包含应用和前端。先在容器内执行 `git apply --check`，通过后才应用。

```powershell
$PatchFile = Join-Path $InvoiceOcrBackup "invoice-ocr-$AcceptedSha.patch"
cmd /d /c "git -C $InvoiceOcrSource diff --binary 11c018f $AcceptedSha -- frontend rayher_hr_payroll > $PatchFile"
docker cp $PatchFile rayher-bench:/tmp/invoice-ocr.patch
docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench/apps/rayher_hr_payroll && git apply --check /tmp/invoice-ocr.patch"
docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench/apps/rayher_hr_payroll && git apply /tmp/invoice-ocr.patch"
```

若检查失败，不覆盖应用目录；应回到隔离工作区解决差异并重新验收。

## 6. site config、迁移、构建和重启

```powershell
docker compose -p rayher -f $InvoiceOcrMainCompose -f $InvoiceOcrCompose up -d bench
docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench && bench --site rayher.localhost set-config invoice_ocr_url http://invoice-ocr:8080"
docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench && bench --site rayher.localhost migrate"
docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench && bench build --app rayher_hr_payroll"
docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench && bench --site rayher.localhost clear-cache && bench --site rayher.localhost clear-website-cache"
docker restart rayher-bench
docker exec rayher-bench curl -fsS http://invoice-ocr:8080/health
```

必须逐条执行；任一命令失败都停止，不继续执行后续写操作。`invoice_ocr_url` 只使用容器内地址，不配置外部 OCR 接口。

## 7. 冒烟验收

打开 `http://203.0.113.88:8000/rayher/approval/purchase`，使用专门的测试报销单完成：

1. 一次选择多张 PDF/JPG/PNG，确认最多 20 张、单张最多 10 MB 的提示正常。
2. 核对发票类别、项目名称、开票日期、发票号码、税前金额、税额、合计金额七项；人工确认前不得自动回填。
3. 把每张已确认发票关联到正确费用明细，保存草稿后重新打开，关联仍存在。
4. 重复上传同一文件，确认被标记为疑似重复且不能直接提交。
5. 每行“查看发票”只能通过安全预览打开正确文件；普通用户不能查看他人的私有发票。
6. 提交一张金额匹配的测试单；OCR 未完成、未确认、未关联或金额差异无原因时必须阻止提交。
7. 检查 OA 看板、审批、费用统计和其他主要页面没有回归。
8. 检查后台队列没有持续异常，并确认 sidecar 仍无主机端口。

验收完成后记录测试单名称，便于按业务规则单独清理测试数据；不要批量处理历史记录。

## 8. 日常运维

每日 scheduler 调用 `cleanup_orphan_invoice_batches(retention_days=7)`。它只清理过期、无申请单、所有记录未确认且未关联、状态一致、没有查看审计、File 严格独占的批次。状态变化、共享文件、审计记录或异常都会安全跳过并写错误日志。

```powershell
docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench && bench --site rayher.localhost execute rayher_hr_payroll.maintenance.invoice_ocr_cleanup.cleanup_orphan_invoice_batches"
# 跳过或异常原因记录在 Frappe Desk 的 Error Log，标题为 Invoice OCR cleanup
```

手动执行只用于维护窗口；不要在识别或用户确认高峰期运行。执行后在 Frappe Desk 的 Error Log 中按标题 `Invoice OCR cleanup` 核对安全跳过和异常。

## 9. 回滚

先停止新增 OCR 请求，再停止 sidecar；保留模型卷作为无业务数据的缓存。用部署时保存的同一补丁做反向检查和反向应用，然后恢复 site config、Compose 并重新迁移/构建。

```powershell
docker compose -p rayher -f $InvoiceOcrMainCompose -f $InvoiceOcrCompose stop invoice-ocr
docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench/apps/rayher_hr_payroll && git apply --reverse --check /tmp/invoice-ocr.patch"
docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench/apps/rayher_hr_payroll && git apply --reverse /tmp/invoice-ocr.patch"
docker cp (Join-Path $InvoiceOcrBackup "site_config.json") "rayher-bench:/workspace/development/frappe-bench/sites/rayher.localhost/site_config.json"
Copy-Item -LiteralPath (Join-Path $InvoiceOcrBackup "rayher-compose.yml") -Destination $InvoiceOcrMainCompose -Force
docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench && bench --site rayher.localhost migrate && bench build --app rayher_hr_payroll && bench --site rayher.localhost clear-cache"
docker compose -p rayher -f $InvoiceOcrMainCompose up -d bench
docker exec rayher-bench curl -fsS -H "Host: rayher.localhost" http://127.0.0.1:8000/api/method/ping
```

如果迁移已经写入业务数据库且必须恢复快照，应先停止平台写入，从 `site-backups.tgz` 解出本次精确的数据库与文件备份，再使用 `bench --site rayher.localhost restore <精确数据库备份路径>`；随后从 `private-files.tgz` 恢复对应 private files。数据库恢复会覆盖备份时间之后的数据，必须由负责人确认维护窗口和精确备份文件后执行。

反向补丁检查失败时不要强行覆盖。保留现场，使用 `rayher-app.tgz` 与 SHA256 记录进行人工比对后再恢复。回滚完成后重复平台 ping、登录、历史报销查看和主流程冒烟，确认原平台恢复。
