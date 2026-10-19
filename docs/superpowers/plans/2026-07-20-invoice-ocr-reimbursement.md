# 发票 OCR 与费用付款/报销单 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 Frappe 费用付款/报销单中交付可直接使用的本地批量发票 OCR、七字段人工确认、全局查重、费用明细关联和逐行私有预览。

**Architecture:** Frappe 保存批次、发票、确认值、查重和报销关联，并通过后台队列调用仅在 Docker 内网开放的 PaddleOCR sidecar。前端将独立的识别面板和预览抽屉嵌入现有 `ExpenseWorkbench`，提交审批时由服务端执行最终状态和权限校验。

**Tech Stack:** Frappe/ERPNext v15、Python 3.10+（Frappe 当前运行 Python 3.14.2）、Vue 3、frappe-ui、PaddleOCR 3.7.0、PaddlePaddle 3.3.1、FastAPI、Docker Compose、MariaDB、Redis Queue。

## Global Constraints

- 支持 PDF、JPG、JPEG、PNG；每批最多 20 个文件；每个不超过 10 MB。
- 七字段固定为：发票类别、项目名称、开票日期、发票号码、税前金额、税额、合计金额。
- 发票类别保留票面完整原文；多项目用中文分号连接；缺失字段留空；不得从文件名生成字段。
- 所有 OCR 结果必须人工确认；本期不做发票真伪验证。
- OCR 在本地 sidecar 运行，正式运行时不开放主机端口、不调用外部 OCR/税务接口。
- 一条费用明细可关联多张发票；一张发票只能关联一条费用明细和一张有效报销单。
- 发票文件必须为 Frappe 私有文件；提交后锁定关联。
- 有发票时未确认、失败或未处理重复均阻止提交；无发票允许提交但必须填写无票原因。
- 不删除旧 DocType、旧附件或消费明细下推数据；变更只提交到 `feat/invoice-ocr-reimbursement`，不提交到 `main`。
- 最终必须通过现有平台链接完成真实上传、识别、确认、查重、关联和预览验收。

## File Structure

- `services/invoice_ocr/invoice_ocr/`: 已验证 POC 提炼出的 OCR 核心与 HTTP 服务，不含 Frappe 业务规则。
- `services/invoice_ocr/tests/`: OCR 解析、文件安全、HTTP 演示员工116和样本指标测试。
- `rayher_hr_payroll/invoice_ocr/`: Frappe 领域规则、权限、sidecar 客户端、服务和后台任务。
- `rayher_hr_payroll/api/invoice_entry.py`: 批次、确认、关联、重试和预览 API。
- `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_invoice_*`: 批次、记录和查看日志 DocType。
- `frontend/src/components/invoice/`: 发票识别面板和预览抽屉。
- `frontend/src/lib/invoiceOcr.js`: 前端纯函数、状态判断和金额提示。
- `deploy/docker-compose.invoice-ocr.yml`: 可审查的 sidecar 部署定义；现有 compose 只在最终部署时备份后合并。

---

### Task 1: 固化已验证 OCR 核心

**Files:**
- Create: `services/invoice_ocr/invoice_ocr/{__init__,models,documents,engine,parser,pipeline,metrics}.py`
- Create: `services/invoice_ocr/tests/test_{models,documents,engine,parser,pipeline,metrics}.py`
- Create: `services/invoice_ocr/pyproject.toml`

**Interfaces:**
- Consumes: `D:/rayher/.codex-temp/invoice-ocr-poc/invoice_ocr` 及测试。
- Produces: `RecognitionResult.record_id: str | None` 和 `recognize_document(source: Path, work_root: Path, engine: OCREngine, record_id: str | None) -> RecognitionResult`；返回七字段、`project_names`、warnings、OCR lines、SHA-256 和耗时，不执行 Frappe 查重。

- [ ] **Step 1: 复制 POC 解析模块和测试**

```powershell
wsl.exe -e sh -lc "mkdir -p services/invoice_ocr/invoice_ocr services/invoice_ocr/tests && cp /tmp/wind/rayher/.codex-temp/invoice-ocr-poc/invoice_ocr/{__init__,models,documents,engine,parser,pipeline,metrics}.py services/invoice_ocr/invoice_ocr/ && cp /tmp/wind/rayher/.codex-temp/invoice-ocr-poc/tests/test_{models,documents,engine,parser,pipeline,metrics}.py services/invoice_ocr/tests/"
```

- [ ] **Step 2: 写失败测试，要求识别与查重解耦且文件名不参与字段**

```python
def test_recognize_document_returns_fields_without_duplicate_index(tmp_path, fake_engine, sample_image):
    result = recognize_document(sample_image, tmp_path, fake_engine, record_id="INV-1")
    assert result.record_id == "INV-1"
    assert result.fields.invoice_category == "电子发票（普通发票）"
    assert result.fields.project_name == "文具印章"
    assert result.duplicate.is_duplicate is False


def test_filename_is_not_parser_input(tmp_path, fake_engine, image_bytes):
    source = tmp_path / "电子发票_错误号码999999_10000元.png"
    source.write_bytes(image_bytes)
    result = recognize_document(source, tmp_path / "work", fake_engine)
    assert result.fields.invoice_number != "999999"
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest services/invoice_ocr/tests/test_pipeline.py -q`
Expected: FAIL，提示 `recognize_document` 不存在。

- [ ] **Step 4: 从现有 `recognize_file` 提取不含 DuplicateIndex 的核心**

```python
def recognize_document(source: Path, work_root: Path, engine: OCREngine, record_id: str | None = None) -> RecognitionResult:
    """Prepare, OCR, parse and reconcile one file; never perform business deduplication."""
    started = perf_counter()
    prepared = prepare_document(source, work_root / "rendered")
    ocr_lines = [line for image in prepared.page_images for line in engine.recognize(image)]
    ocr_outcome = parse_invoice(ocr_lines)
    embedded_lines = text_to_lines(prepared.embedded_text) if prepared.use_embedded_text else []
    embedded_outcome = parse_invoice(embedded_lines) if embedded_lines else ParseOutcome()
    outcome = reconcile_outcomes(ocr_outcome, embedded_outcome)
    return RecognitionResult(
        record_id=record_id,
        source_filename=source.name,
        file_sha256=prepared.source_sha256,
        fields=outcome.fields,
        field_confidence=outcome.field_confidence,
        warnings=outcome.warnings,
        processing_ms=_elapsed_ms(started),
        ocr_lines=[*ocr_lines, *embedded_lines],
        status="needs_confirmation",
    )
```

在 `RecognitionResult` 增加可选 `record_id`；保持 POC 的 PDF 渲染、图像规范化、标题原文、项目名称和金额解析；删除 sidecar 内持久 DuplicateIndex。

- [ ] **Step 5: 运行 OCR 单元测试并提交**

Run: `python -m pytest services/invoice_ocr/tests -q`
Expected: 全部 PASS，POC 原有解析测试无回退。

```bash
git add services/invoice_ocr
git commit -m "feat: productionize invoice OCR core"
```

### Task 2: 提供隔离 OCR HTTP sidecar

**Files:**
- Create: `services/invoice_ocr/invoice_ocr/api.py`
- Create: `services/invoice_ocr/tests/test_api.py`
- Create: `services/invoice_ocr/{requirements.txt,requirements-test.txt,Dockerfile,.dockerignore}`

**Interfaces:**
- Consumes: Task 1 `recognize_document`。
- Produces: `GET /health -> {status, engine}`；`POST /v1/recognize` multipart `file`, `record_id` -> `RecognitionResult` JSON。

- [ ] **Step 1: 写失败 HTTP 演示员工116测试**

```python
def test_recognize_endpoint_returns_seven_fields(client, override_engine, invoice_png):
    response = client.post("/v1/recognize", files={"file": ("invoice.png", invoice_png, "image/png")}, data={"record_id": "INV-1"})
    assert response.status_code == 200
    body = response.json()
    assert set(body["fields"]) >= {"invoice_category", "project_name", "issue_date", "invoice_number", "amount_before_tax", "tax_amount", "total_amount"}
    assert body["status"] == "needs_confirmation"


def test_rejects_more_than_ten_megabytes(client):
    response = client.post("/v1/recognize", files={"file": ("big.png", b"x" * (10 * 1024 * 1024 + 1), "image/png")})
    assert response.status_code == 413
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest services/invoice_ocr/tests/test_api.py -q`
Expected: FAIL，模块 `invoice_ocr.api` 不存在。

- [ ] **Step 3: 实现 FastAPI 接口和懒加载引擎**

```python
MAX_BYTES = 10 * 1024 * 1024
app = FastAPI(title="QIHENG Demo Invoice OCR", docs_url=None, redoc_url=None)

@lru_cache(maxsize=1)
def get_engine() -> OCREngine:
    return PaddleOCREngine()

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "engine": "paddleocr"}

@app.post("/v1/recognize")
async def recognize(file: UploadFile, record_id: str | None = Form(default=None)) -> dict:
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / Path(file.filename or "invoice.bin").name
        source.write_bytes(content)
        result = recognize_document(source, Path(tmp) / "work", get_engine(), record_id)
    return result.model_dump(mode="json")
```

不支持格式映射 415，损坏/密码 PDF 映射 422，超限映射 413，内部错误映射 500；响应不得含本机路径。

- [ ] **Step 4: 固定依赖并构建镜像**

`requirements.txt` 固定 PaddlePaddle 3.3.1、PaddleOCR 3.7.0、Pydantic 2.11.7、Pillow 11.3.0、PyMuPDF 1.26.4、NumPy 2.2.6、FastAPI 0.116.1、Uvicorn 0.35.0、python-multipart 0.0.20；`requirements-test.txt` 固定 pytest 8.4.1 和 httpx 0.28.1。Docker 使用 Python 3.11、非 root 用户，提供含测试依赖的 `test` stage 和不含测试依赖的 `runtime` stage；runtime 监听 8080 并健康检查 `/health`。

Run: `python -m pytest services/invoice_ocr/tests -q`
Expected: PASS。
Run: `docker build --target runtime -t rayher/invoice-ocr:0.1.0 services/invoice_ocr`
Expected: runtime 镜像构建成功。

- [ ] **Step 5: 离线测试并提交**

Run: `docker build --target test -t rayher/invoice-ocr-test:0.1.0 services/invoice_ocr`
Expected: test 镜像构建成功。
Run: `docker run --rm --network none rayher/invoice-ocr-test:0.1.0 python -m pytest -q`
Expected: PASS。

```bash
git add services/invoice_ocr
git commit -m "feat: add local invoice OCR sidecar"
```

### Task 3: 建立 Frappe 发票数据模型

**Files:**
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_invoice_import_batch/*`
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_invoice_record/*`
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_invoice_view_log/*`
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_expense_line/oa_approval_expense_line.json`
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_request/oa_approval_request.json`
- Modify: `rayher_hr_payroll/tests/test_doctype_json.py`

**Interfaces:**
- Produces: `batch_status`, `temporary_token`, `invoice_file`, `file_sha256`、七字段、`ocr_payload`, `field_warnings`, `recognition_status`, `duplicate_of`, `duplicate_reason`, `request`, `expense_line_key`, `confirmed_by`, `confirmed_on`；费用行 `line_key`, `invoice_difference_reason`；请求 `invoice_count`, `invoice_status`, `no_invoice_reason`。

- [ ] **Step 1: 写失败 DocType 元数据测试**

```python
def test_invoice_ocr_doctypes_define_auditable_records():
    record = load_doctype("oa_invoice_record")
    fields = fieldnames(record)
    assert {"invoice_category", "project_name", "issue_date", "invoice_number", "amount_before_tax", "tax_amount", "total_amount"}.issubset(fields)
    assert {"file_sha256", "ocr_payload", "recognition_status", "duplicate_of", "request", "expense_line_key", "confirmed_by", "confirmed_on"}.issubset(fields)
    assert record["track_changes"] == 1
```

同时断言批次、查看日志以及费用行/请求的新字段。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest rayher_hr_payroll/tests/test_doctype_json.py -q`
Expected: FAIL，找不到 `oa_invoice_record`。

- [ ] **Step 3: 创建 DocType JSON/Python**

金额使用 Currency；发票号码、SHA-256、`line_key` 使用 Data；OCR 原始值使用 Code/Long Text；文件使用 Attach 且由上传 API 强制私有；三个主 DocType 启用 `track_changes`。状态只允许“排队中、识别中、待确认、已确认、疑似重复、失败、已排除”。Employee 只能创建/读取本人记录，Department Manager/Accounts User/HR 按角色读取，仅 System Manager 可删除。

- [ ] **Step 4: 运行元数据测试并提交**

Run: `python -m pytest rayher_hr_payroll/tests/test_doctype_json.py -q`
Expected: PASS。

```bash
git add rayher_hr_payroll/rayher_hr_payroll/doctype rayher_hr_payroll/tests/test_doctype_json.py
git commit -m "feat: add invoice OCR doctypes"
```

### Task 4: 实现领域校验、查重键和权限

**Files:**
- Create: `rayher_hr_payroll/invoice_ocr/{__init__,domain,permissions}.py`
- Create: `rayher_hr_payroll/tests/test_invoice_ocr_domain.py`
- Modify: `rayher_hr_payroll/hooks.py`

**Interfaces:**
- Produces: `business_key(invoice_number, issue_date, total_amount) -> str | None`；`amount_difference(before_tax, tax, total) -> Decimal | None`；`submission_blockers(records, no_invoice_reason) -> list[str]`；`can_read_invoice(doc, user) -> bool`。

- [ ] **Step 1: 写领域失败测试**

```python
def test_business_key_requires_all_three_values():
    assert business_key("2632200005753891281", "2026-07-14", "35.98") == "2632200005753891281|2026-07-14|35.98"
    assert business_key("", "2026-07-14", "35.98") is None


def test_amount_difference_uses_two_cent_tolerance():
    assert amount_difference("35.62", "0.36", "35.98") is None
    assert amount_difference("35.62", "0.36", "36.10") == Decimal("0.12")


def test_unconfirmed_invoice_blocks_submission():
    assert submission_blockers([{"recognition_status": "待确认"}], "") == ["存在未确认发票"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest rayher_hr_payroll/tests/test_invoice_ocr_domain.py -q`
Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现纯函数和权限钩子**

金额统一使用 `Decimal(str(value)).quantize(Decimal("0.01"))`，禁止 float 参与最终金额。`hooks.py` 为三个新 DocType 注册 `permission_query_conditions` 和 `has_permission`；记录所有者、所属报销人、当前审批人和财务/系统角色按最小权限读取，普通用户不能读取他人未关联批次。

- [ ] **Step 4: 运行测试并提交**

Run: `python -m pytest rayher_hr_payroll/tests/test_invoice_ocr_domain.py rayher_hr_payroll/tests/test_doctype_json.py -q`
Expected: PASS。

```bash
git add rayher_hr_payroll/invoice_ocr rayher_hr_payroll/hooks.py rayher_hr_payroll/tests/test_invoice_ocr_domain.py
git commit -m "feat: enforce invoice OCR domain rules"
```

### Task 5: 实现 Frappe OCR 客户端、后台任务和 API

**Files:**
- Create: `rayher_hr_payroll/invoice_ocr/{client,service,jobs}.py`
- Create: `rayher_hr_payroll/api/invoice_entry.py`
- Create: `rayher_hr_payroll/tests/test_invoice_ocr_service.py`

**Interfaces:**
- Consumes: `site_config.invoice_ocr_url`，默认 `http://invoice-ocr:8080`；Task 2 `/v1/recognize`；Task 3 DocTypes；Task 4 规则。
- Produces API: `create_batch`, `register_file`, `get_batch`, `update_invoice`, `confirm_invoice`, `retry_invoice`, `exclude_invoice`, `link_invoice`, `resolve_duplicate`, `get_request_invoices`, `preview_invoice`；后台 `recognize_invoice(invoice_name: str)`。

- [ ] **Step 1: 写失败服务测试**

```python
def test_register_file_forces_private_and_queues_after_commit(frappe_stub):
    record = register_file(batch="BATCH-1", file_url="/private/files/a.pdf", original_filename="a.pdf", mime_type="application/pdf", file_size=1200)
    assert record.recognition_status == "排队中"
    frappe_stub.enqueue.assert_called_once_with("rayher_hr_payroll.invoice_ocr.jobs.recognize_invoice", invoice_name=record.name, queue="long", enqueue_after_commit=True)


def test_confirm_rejects_client_controlled_duplicate_state(frappe_stub):
    with pytest.raises(ValidationError, match="重复状态只能由服务端更新"):
        confirm_invoice("INV-1", {"recognition_status": "已确认", "duplicate_of": ""})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest rayher_hr_payroll/tests/test_invoice_ocr_service.py -q`
Expected: FAIL，服务模块不存在。

- [ ] **Step 3: 实现状态机和两层查重**

`register_file` 验证批次所有权、私有 URL、真实签名、大小和批次数量；用 Redis 锁 `invoice:file:<sha256>` 查找现存记录并设置 `duplicate_of`。`recognize_invoice` 只允许“排队中/失败”进入“识别中”，调用 sidecar 后保存原始 JSON、七字段候选和 warnings，再用 Redis 锁 `invoice:business:<key>` 执行业务查重。异常保存为“失败”和可读错误，不回滚同批其他记录。

- [ ] **Step 4: 实现白名单 API 和预览日志**

所有写接口只接收七字段和关联字段白名单；确认接口由服务端写 `confirmed_by/on`；财务解除疑似重复必须提供非空原因；预览先验证记录/报销权限，新增 `OA Invoice View Log`，再返回可内嵌预览的私有文件信息，不能返回磁盘路径。

- [ ] **Step 5: 运行测试并提交**

Run: `python -m pytest rayher_hr_payroll/tests/test_invoice_ocr_service.py rayher_hr_payroll/tests/test_invoice_ocr_domain.py -q`
Expected: PASS。

```bash
git add rayher_hr_payroll/invoice_ocr rayher_hr_payroll/api/invoice_entry.py rayher_hr_payroll/tests/test_invoice_ocr_service.py
git commit -m "feat: add invoice OCR workflow APIs"
```

### Task 6: 将发票校验接入报销单生命周期

**Files:**
- Modify: `rayher_hr_payroll/api/oa_entry.py:200-222,398-500,575-632`
- Modify: `rayher_hr_payroll/tests/test_oa_approval_routes.py`
- Create: `rayher_hr_payroll/tests/test_invoice_request_integration.py`

**Interfaces:**
- Consumes: Task 5 `attach_batch_to_request(batch_name, request_doc)` 和 `validate_request_invoices(request_doc, submitting: bool)`。
- Produces: `create_request(..., invoice_batch=None, no_invoice_reason=None)`；费用行保留 `line_key`, `invoice_difference_reason`；摘要返回 `invoice_count`, `invoice_status`, `invoice_search_text`。

- [ ] **Step 1: 写失败请求生命周期测试**

```python
def test_submit_blocks_unconfirmed_linked_invoice(request_doc, invoice_record):
    invoice_record.recognition_status = "待确认"
    with pytest.raises(ValidationError, match="未确认"):
        validate_request_invoices(request_doc, submitting=True)


def test_no_invoice_requires_reason_only_on_submit(draft_request):
    validate_request_invoices(draft_request, submitting=False)
    with pytest.raises(ValidationError, match="无票原因"):
        validate_request_invoices(draft_request, submitting=True)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest rayher_hr_payroll/tests/test_invoice_request_integration.py -q`
Expected: FAIL，集成函数不存在。

- [ ] **Step 3: 修改创建、草稿提交和序列化**

`_normalize_expense_lines` 为每行生成或保留 UUID `line_key`，保留差异原因；`create_request` 插入请求后在同一事务关联批次；`_submit_draft` 和直接提交都调用服务端校验。汇总搜索文本只包含确认后的发票类别、项目名称和号码。旧消费明细下推继续生成稳定键并兼容旧附件状态；新状态文案统一为“已确认”，不改写历史记录原值。

- [ ] **Step 4: 运行 OA 回归并提交**

Run: `python -m pytest rayher_hr_payroll/tests/test_invoice_request_integration.py rayher_hr_payroll/tests/test_oa_approval_routes.py rayher_hr_payroll/tests/test_doctype_json.py -q`
Expected: PASS。

```bash
git add rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/tests
git commit -m "feat: bind confirmed invoices to reimbursement requests"
```

### Task 7: 实现前端发票状态模块和独立组件

**Files:**
- Create: `frontend/src/lib/invoiceOcr.js`
- Create: `frontend/src/components/invoice/InvoiceRecognitionPanel.vue`
- Create: `frontend/src/components/invoice/InvoicePreviewDrawer.vue`
- Create: `frontend/tests/invoice-ocr.test.js`
- Create: `frontend/tests/invoice-ocr-source.test.js`

**Interfaces:**
- Produces: `newLineKey()`, `invoiceBlockers(invoices)`, `amountMismatch(invoice)`, `invoicesForLine(invoices, lineKey)`；组件 emits `batch-created`, `invoices-change`, `link-change`, `close`。

- [ ] **Step 1: 写失败前端纯函数测试**

```javascript
test('groups many invoices under one stable expense line', () => {
  const rows = invoicesForLine([{ name: 'I1', expense_line_key: 'L1' }, { name: 'I2', expense_line_key: 'L1' }], 'L1');
  assert.deepEqual(rows.map((row) => row.name), ['I1', 'I2']);
});

test('blocks unconfirmed and duplicate records', () => {
  assert.deepEqual(invoiceBlockers([{ recognition_status: '待确认' }, { recognition_status: '疑似重复' }]), ['存在未确认发票', '存在疑似重复发票']);
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && node --test tests/invoice-ocr.test.js`
Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现纯函数和 API 封装**

金额计算先把字符串转换为整数分；`newLineKey()` 使用 `crypto.randomUUID()`，无支持时用安全随机字节。上传向 `/api/method/upload_file` 发送 `is_private=1`, `doctype=OA Invoice Import Batch`, `docname=<batch>`，成功后调用 `register_file`，并发限制为 3。

- [ ] **Step 4: 实现识别面板和预览抽屉**

面板显示批次进度和一票一行七字段，状态轮询在所有记录进入终态后停止；低置信或缺失高亮；确认前可编辑、确认后锁定。抽屉只通过 `preview_invoice` 获取信息；PDF 内嵌，图片使用 `<img>`；上层覆盖当前用户和时间水印，不提供下载按钮。

- [ ] **Step 5: 运行测试、构建并提交**

Run: `cd frontend && node --test tests/invoice-ocr.test.js tests/invoice-ocr-source.test.js`
Expected: PASS。
Run: `cd frontend && yarn build`
Expected: Vite build 成功，无 unresolved import。

```bash
git add frontend/src/lib/invoiceOcr.js frontend/src/components/invoice frontend/tests
git commit -m "feat: add invoice recognition UI components"
```

### Task 8: 集成费用工作台、搜索、导出和逐行预览

**Files:**
- Modify: `frontend/src/components/ExpenseWorkbench.vue:57-63,154-163,280-343,472-486,632-638`
- Modify: `frontend/tests/oa-source.test.js`

**Interfaces:**
- Consumes: Task 7 组件/函数，Task 5 API，Task 6 请求参数和摘要。
- Produces: 新建表单 OCR 区；费用明细“查看发票（N）”；详情页预览；搜索和导出包含发票类别、项目名称、发票号码。

- [ ] **Step 1: 写失败工作台集成断言**

```javascript
test('expense form embeds invoice OCR and per-line preview', () => {
  assert.match(workbenchSource, /InvoiceRecognitionPanel/);
  assert.match(workbenchSource, /InvoicePreviewDrawer/);
  assert.match(workbenchSource, /查看发票/);
  assert.match(workbenchSource, /invoice_batch/);
  assert.match(workbenchSource, /no_invoice_reason/);
  assert.match(workbenchSource, /invoice_search_text/);
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && node --test tests/oa-source.test.js`
Expected: FAIL，缺少 OCR 组件。

- [ ] **Step 3: 集成新建表单**

`blankLine()` 创建稳定 `line_key`；基本信息后渲染 `InvoiceRecognitionPanel`；保存参数加入批次和无票原因；提交前前端显示即时 blocker，最终以服务端校验为准。删除明细时若有关联发票则阻止并提示先重新关联，不删除文件。

- [ ] **Step 4: 集成详情、搜索和导出**

费用明细末尾显示“查看发票（N）”；点击按请求和 `line_key` 拉取记录并打开抽屉。客户端搜索串加入 `row.invoice_search_text`；导出增加“发票类别、项目名称、发票号码”三列，多个值用“；”连接。

- [ ] **Step 5: 全量前端测试、构建并提交**

Run: `cd frontend && node --test tests/*.test.js`
Expected: 全部 PASS。
Run: `cd frontend && yarn build`
Expected: PASS，并生成新的 `rayher_hr_payroll/public/frontend` 资源。

```bash
git add frontend rayher_hr_payroll/public/frontend
git commit -m "feat: integrate invoice OCR into expense workbench"
```

### Task 9: 增加隔离部署、清理和验收脚本

**Files:**
- Create: `deploy/docker-compose.invoice-ocr.yml`
- Create: `rayher_hr_payroll/maintenance/invoice_ocr_cleanup.py`
- Create: `rayher_hr_payroll/tests/test_invoice_ocr_cleanup.py`
- Modify: `rayher_hr_payroll/hooks.py`
- Create: `docs/invoice-ocr-runbook.md`

**Interfaces:**
- Produces: `cleanup_orphan_invoice_batches(retention_days: int = 7, now=None)`；镜像 `rayher/invoice-ocr:0.1.0`；内部网络 `rayher-ocr-internal`；模型卷 `rayher-invoice-ocr-models`。

- [ ] **Step 1: 写失败孤立清理测试**

```python
def test_cleanup_deletes_only_expired_unconfirmed_unlinked_batches(repo):
    removed = cleanup_orphan_invoice_batches(retention_days=7, now="2026-07-20 12:00:00")
    assert removed == ["BATCH-EXPIRED"]
    assert repo.exists("BATCH-CONFIRMED")
    assert repo.exists("BATCH-LINKED")
```

- [ ] **Step 2: 实现清理和每日调度**

只删除超过 7 天且所有记录均未确认、未关联的批次及私有文件；逐条验证 `request` 和 `confirmed_on`；状态不一致时跳过并记录日志。在 `scheduler_events.daily` 注册。

- [ ] **Step 3: 编写 Compose 覆盖和操作手册**

sidecar 只接入 `internal: true` 的 `rayher-ocr-internal`，不声明 `ports`；bench 同时接入原网络和 OCR 内网；模型使用命名卷；健康检查调用 `/health`。手册写出模型首次联网预热、正式内网启动、健康检查、站点配置、备份、迁移、冒烟和回滚命令。

- [ ] **Step 4: 验证 Compose 和测试**

Run: `docker compose -f D:/rayher/rayher-compose.yml -f deploy/docker-compose.invoice-ocr.yml config --quiet`
Expected: exit 0。
Run: `python -m pytest rayher_hr_payroll/tests/test_invoice_ocr_cleanup.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add deploy docs/invoice-ocr-runbook.md rayher_hr_payroll/maintenance/invoice_ocr_cleanup.py rayher_hr_payroll/hooks.py rayher_hr_payroll/tests/test_invoice_ocr_cleanup.py
git commit -m "ops: add isolated invoice OCR deployment"
```

### Task 10: 隔离站点集成验证与 15 样本验收

**Files:**
- Modify only when defects are proven: Tasks 1-9 所属文件。
- Create: `docs/change-records/2026-07-20-invoice-ocr-acceptance.md`

**Interfaces:**
- Produces: 可重复的测试证据、字段准确率、失败清单和回滚验证；不接触正式业务记录。

- [ ] **Step 1: 建立独立测试站点和备份点**

在 Docker 卷内创建 `invoice-ocr-test.localhost`，安装当前功能分支 app；不得复用 `rayher.localhost` 数据库。记录当前容器、镜像、站点和 Git SHA。

- [ ] **Step 2: 运行完整回归**

Run: `bench --site invoice-ocr-test.localhost run-tests --app rayher_hr_payroll`
Expected: PASS。
Run: `cd frontend && node --test tests/*.test.js && yarn build`
Expected: PASS。

- [ ] **Step 3: 用 15 张样本执行真实 sidecar 批次**

样本目录只读挂载，文件名不得进入解析输入。生成字段级指标，Expected: 总准确率 `>= 0.95`；每个文件均明确成功或明确失败；所有成功记录为“待确认”。

- [ ] **Step 4: 执行集成场景**

验证批量 15 文件、完全重复、业务疑似重复、人工修正与确认、一明细多发票、明细重排不串票、金额差异说明、无票原因、草稿恢复、提交锁定、审批用户预览、越权拒绝、OCR 停机降级和旧消费明细下推。

- [ ] **Step 5: 记录结果并提交**

验收文档记录命令、时间、Git SHA、镜像 digest、通过/失败数、准确率和未通过项；不得复制发票敏感内容或样本文件到 Git。

```bash
git add docs/change-records/2026-07-20-invoice-ocr-acceptance.md
git commit -m "test: record invoice OCR acceptance"
```

### Task 11: 安全部署到现有平台并完成浏览器验收

**Files:**
- External: `D:/rayher/rayher-compose.yml`（先备份后最小合并）
- Runtime: `/workspace/development/frappe-bench/apps/rayher_hr_payroll`
- No source commit unless deployment uncovers a reproducible defect.

**Interfaces:**
- Consumes: Task 10 全绿 Git SHA 和镜像 digest。
- Produces: `http://203.0.113.88:8000/rayher/approval/purchase` 可直接使用 OCR；完整备份和可执行回滚点。

- [ ] **Step 1: 部署前只读核对与备份**

确认 live app 目标文件与基线差异；若 `git apply --check` 失败，停止并在隔离工作区合并，不覆盖用户改动。备份 MariaDB、`sites/rayher.localhost/private/files`、现有 compose 和将被替换的应用文件；验证备份可列出且大小非零。

- [ ] **Step 2: 启动内网 OCR 服务**

先以临时联网容器把官方 Paddle 模型预热到 `rayher-invoice-ocr-models`；随后停止临时容器，以 internal 网络配置启动正式 sidecar。确认容器无主机端口，并从 bench 内访问 `/health` 成功。

- [ ] **Step 3: 应用代码、配置和迁移**

只应用功能分支相对 `11c018f` 的受审差异；设置 `invoice_ocr_url=http://invoice-ocr:8080`；依次执行 `bench --site rayher.localhost migrate`、`bench build --app rayher_hr_payroll`、缓存清理和进程重启。任何命令失败立即停止，不继续写数据。

- [ ] **Step 4: 运行平台冒烟测试**

通过现有登录会话打开平台链接：批量上传样本、观察识别、修改并确认七项、关联费用明细、保存草稿、重复上传拦截、提交测试单、逐行预览正确文件。再检查 OA 看板、消费明细下推、审批流、费用统计和其他主要页面。

- [ ] **Step 5: 验证数据和安全边界**

确认测试记录可明确识别并可清理，历史记录数量不减少；私有文件不能匿名打开；普通用户不能查看他人未授权发票；sidecar 无外部端口；后台无持续异常队列。

- [ ] **Step 6: 完成或回滚**

全部通过则保留部署并向用户交付链接和测试证据。若关键步骤失败，停止 sidecar，恢复 compose/应用备份和数据库备份，验证原平台恢复；不得用 `git reset --hard`、不得删除整个站点或 Docker 数据卷。