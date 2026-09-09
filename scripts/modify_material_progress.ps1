$path = 'frontend/src/pages/MaterialProgress.vue'
$text = Get-Content -Path $path -Raw -Encoding utf8
$anchor = "const stageStatuses = ['OA审批中', '采购确认中', 'PO处理中', '供应商制作中', '到货验收中', '付款中', '已关闭'];"
if (-not $text.Contains('const primaryFields = new Set')) {
  $insert = @"
const primaryFields = new Set(['source_request', 'material_serial', 'material_code', 'item_name', 'specification', 'project', 'quantity', 'pr_available_quantity', 'pr_create_quantity', 'pr_quantity', 'progress_override', 'status_detail', 'expected_delivery_date', 'pr_numbers', 'po_numbers', 'supplier']);
const showAllColumns = ref(false);
const displayColumns = computed(() => showAllColumns.value ? columns : columns.filter((column) => primaryFields.has(column.field)));
"@
  $text = $text.Replace($anchor, $insert + $anchor)
}
if (-not $text.Contains('function selectionLabel(row)')) {
  $newFn = @"
function canEditField(field) { return editableFields.has(field); }
function selectionLabel(row) {
  if (Number(row.pr_eligible)) return '可提 PR';
  if (row.progress_status === 'OA审批中') return '待审批';
  if (row.progress_status === '已关闭') return '已关闭';
  return '已提完';
}
"@
  $text = $text.Replace('function canEditField(field) { return editableFields.has(field); }', $newFn.TrimEnd("`r", "`n"))
}
$oldMeta = '<div class="flex flex-wrap items-center gap-2 text-sm"><span class="font-semibold text-gray-900">共 {{ rows.length }} 项物料</span><span v-for="item in statusOptions.filter((value) => !stageStatuses.includes(value) && counts[value])" :key="item" class="rounded px-2 py-1 text-xs font-medium" :class="badgeClass(item)">{{ item }} {{ counts[item] }}</span></div>'
if ($text.Contains($oldMeta)) {
  $newMeta = @"
<div class="board-meta"><div class="flex flex-wrap items-center gap-2 text-sm"><span class="font-semibold text-gray-900">共 {{ rows.length }} 项物料</span><span v-for="item in statusOptions.filter((value) => !stageStatuses.includes(value) && counts[value])" :key="item" class="rounded px-2 py-1 text-xs font-medium" :class="badgeClass(item)">{{ item }} {{ counts[item] }}</span></div><div class="board-legend"><span class="legend-item legend-selectable"><i></i>可提 PR</span><span class="legend-item legend-locked"><i></i>不可选</span><span class="legend-item legend-editable"><i></i>可编辑</span><button type="button" class="view-toggle" @click="showAllColumns = !showAllColumns"><FeatherIcon :name="showAllColumns ? 'chevron-left' : 'columns'" class="h-3.5 w-3.5" />{{ showAllColumns ? '收起扩展字段' : '显示全部字段' }}</button></div></div>
"@
  $text = $text.Replace($oldMeta, $newMeta.Trim())
}
$text = $text.Replace(':colspan="columns.length + 2"', ':colspan="displayColumns.length + 2"')
$text = $text.Replace('min-w-[4110px]', 'min-w-[1900px]')
$text = $text.Replace('<col v-for="column in columns"', '<col v-for="column in displayColumns"')
$text = $text.Replace('<th class="w-11 border-b border-r border-gray-200 px-2 py-2 text-center"><input type="checkbox" title="全选可提 PR 物料" @change="toggleAllPrRows" /></th>', '<th class="selection-header border-b border-r border-gray-200 px-2 py-2 text-center"><input type="checkbox" title="全选可提 PR 物料" @change="toggleAllPrRows" /><span>选择</span></th>')
$text = $text.Replace('<th v-for="column in columns"', '<th v-for="column in displayColumns"')
$text = $text.Replace('<td v-for="(column, columnIndex) in columns"', '<td v-for="(column, columnIndex) in displayColumns"')
$selectStart = $text.IndexOf('<td class="border-b border-r border-gray-200 px-2 py-2 text-center"><input type="checkbox"')
if ($selectStart -ge 0) {
  $selectEnd = $text.IndexOf('</td>', $selectStart) + 5
  $newSelect = @"
<td class="selection-cell border-b border-r border-gray-200 px-2 py-2 text-center"><input type="checkbox" :checked="selectedForPr.has(row.name)" :disabled="!Number(row.pr_eligible)" :title="Number(row.pr_eligible) ? '选择生成 PR' : '需求审批未完成或已全部提 PR'" @change="togglePrRow(row, `$event.target.checked)" /><span class="selection-badge" :class="Number(row.pr_eligible) ? 'is-selectable' : 'is-locked'">{{ selectionLabel(row) }}</span></td>
"@
  $text = $text.Substring(0, $selectStart) + $newSelect.Trim() + $text.Substring($selectEnd)
}
$classStart = $text.IndexOf(':class="[column.field ===')
$classEnd = $text.IndexOf(' :contenteditable', $classStart)
if ($classStart -ge 0 -and $classEnd -gt $classStart) {
  $newClass = @"
:class="[column.field === 'progress_override' ? badgeClass(row.progress_status) : '', row.record_status === '已取消' ? 'text-gray-400' : '', canEditField(column.field) ? 'is-editable' : 'is-readonly']"
"@
  $text = $text.Substring(0, $classStart) + $newClass.Trim() + $text.Substring($classEnd)
}
$css = @"
.board-meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.board-legend { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; color: #64748b; font-size: 12px; }
.legend-item { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.legend-item i { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }
.legend-selectable i { background: #0f766e; }
.legend-locked i { background: #cbd5e1; }
.legend-editable i { background: #fef3c7; border: 1px solid #f59e0b; }
.view-toggle { display: inline-flex; align-items: center; gap: 5px; border: 1px solid #cbd5e1; background: #fff; color: #334155; padding: 5px 9px; font-size: 12px; }
.view-toggle:hover { background: #f8fafc; border-color: #94a3b8; }
.selection-header { width: 86px; min-width: 86px; }
.selection-header span { display: block; margin-top: 3px; font-size: 10px; color: #64748b; font-weight: 600; }
.selection-cell { width: 86px; min-width: 86px; background: #f8fafc; }
.selection-cell input { width: 15px; height: 15px; vertical-align: middle; accent-color: #0f766e; }
.selection-badge { display: block; margin: 5px auto 0; width: max-content; max-width: 72px; border-radius: 999px; padding: 2px 6px; font-size: 10px; line-height: 1.2; font-weight: 700; }
.selection-badge.is-selectable { background: #ccfbf1; color: #0f766e; }
.selection-badge.is-locked { background: #e2e8f0; color: #64748b; }
.material-progress-shell .progress-grid tbody td.is-editable { background: #fffbeb; box-shadow: inset 0 0 0 1px rgba(245,158,11,.10); }
.material-progress-shell .progress-grid tbody td.is-editable:hover { background: #fef3c7; }
.material-progress-shell .progress-grid tbody td.is-readonly { color: #475569; }
.material-progress-shell .progress-grid tbody td[data-progress-field='progress_override'] { font-weight: 700; }
@media (max-width: 900px) { .board-legend { width: 100%; } .view-toggle { margin-left: auto; } }
"@
$pos = $text.IndexOf('</style>')
if ($pos -lt 0) { throw 'style marker not found' }
if (-not $text.Contains('.board-meta {')) { $text = $text.Substring(0, $pos) + $css + $text.Substring($pos) }
Set-Content -Path $path -Value $text -Encoding utf8 -NoNewline
Write-Output 'material progress updated'