<script setup>
// 采购申请的物料明细编辑：每行一个物料，编号可以搜物料库，也可以按分类逐级选（至少到三级，后面的流水号交给 PMC 补）。
// 绑定了目录里的物料后，名称、规格、品牌等自动带出、不能改（灰底）。PMC 补录时每行可以查重复 / 绑定已有物料。
import { reactive, watch } from 'vue';
import {
  applyCategory, applyMaterial, blankLine, categoryChildren, categoryDepth, categoryHasChildren, clearMaterial,
  directMaterials, lineCodeText,
} from '../../lib/procurementView.js';
import { apiGet } from './procData.js';

const props = defineProps({
  lines: { type: Array, required: true },
  categories: { type: Array, default: () => [] },
  mode: { type: String, default: 'new' },
  suggestions: { type: Object, default: () => ({}) },
});
const emit = defineEmits(['suggest', 'error']);

const BLANK = Object.freeze({ query: '', matches: [], open: false, cat: false, path: [], parent: '', more: false });
const ui = reactive({});
const catMaterials = reactive({});
const catLoading = reactive({});
const timers = {};

const S = (line) => ui[line._uid] || BLANK;

function initialQuery(line) {
  return line.material_code ? `${line.material_code} ${line.item_name || ''}`.trim() : (line.category_code || '');
}

function ensure() {
  for (const line of props.lines) {
    if (!ui[line._uid]) ui[line._uid] = { query: initialQuery(line), matches: [], open: false, cat: false, path: [], parent: '', more: false, token: 0 };
  }
}
watch(() => props.lines.map((line) => line._uid), ensure, { immediate: true });

// 长的物料名称、规格要完整看到（目录里带出来的值经常很长），输入框随内容长高。
function grow(el) {
  el.style.height = 'auto';
  el.style.height = `${Math.max(34, el.scrollHeight + 2)}px`;
}
const vAutoGrow = { mounted: grow, updated: grow };

function removeLine(index) {
  if (props.lines.length > 1) props.lines.splice(index, 1);
}

function addLineBelow() {
  props.lines.push(blankLine());
  ensure();
}
defineExpose({ addLine: addLineBelow });

// ---------------------------------------------------------------- 搜物料库
function onType(line) {
  const state = ui[line._uid];
  state.cat = false;
  clearTimeout(timers[line._uid]);
  timers[line._uid] = setTimeout(() => search(line), 200);
}

async function search(line) {
  const state = ui[line._uid];
  const query = String(state.query || '').trim();
  state.open = Boolean(query);
  if (!query) { state.matches = []; return; }
  const token = (state.token = (state.token || 0) + 1);
  try {
    const rows = await apiGet('procurement_materials.list_materials', { query, limit: 10 });
    if (token === state.token) state.matches = rows || [];
  } catch (error) {
    state.matches = [];
    emit('error', error);
  }
}

function pickMaterial(line, item) {
  const state = ui[line._uid];
  applyMaterial(line, item);
  state.query = `${line.material_code} ${line.item_name || ''}`.trim();
  state.matches = [];
  state.open = false;
  closePicker(line);
}

function pickFirst(line) {
  const state = ui[line._uid];
  if (state.matches[0]) pickMaterial(line, state.matches[0]);
}

// 改为新增物料：不绑定目录里的编号，名称等资料自己填，编号交给 PMC 补。
function unbind(line) {
  const state = ui[line._uid];
  clearMaterial(line);
  state.query = line.category_code || '';
  closePicker(line);
}

// ---------------------------------------------------------------- 按分类逐级选
function openPicker(line) {
  const state = ui[line._uid];
  state.cat = true;
  state.open = false;
  state.parent = state.path[state.path.length - 1] || '';
  loadCatMaterials(state.parent);
}

function closePicker(line) {
  const state = ui[line._uid];
  state.cat = false;
  state.parent = '';
  state.path = [];
}

function children(line) {
  return categoryChildren(props.categories, S(line).parent);
}

function hasChildren(item) {
  return categoryHasChildren(props.categories, item);
}

function pathLabels(line) {
  return S(line).path.map((code) => props.categories.find((item) => item.category_code === code)?.category_name || code).join(' / ');
}

async function loadCatMaterials(code) {
  if (!code || catMaterials[code] || catLoading[code]) return;
  catLoading[code] = true;
  try {
    // 接口可能把整棵子树都返回，只留这个分类自己名下的；旧接口不认 category_code 时按编号前缀再查一次。
    let rows = directMaterials((await apiGet('procurement_materials.list_materials', { category_code: code, limit: 500 })) || [], code);
    if (!rows.length) rows = directMaterials((await apiGet('procurement_materials.list_materials', { query: `${code}.`, limit: 500 })) || [], code);
    catMaterials[code] = rows;
  } catch (error) {
    catMaterials[code] = [];
    emit('error', error);
  } finally {
    catLoading[code] = false;
  }
}

async function chooseCategory(line, item) {
  const state = ui[line._uid];
  const code = String(item?.category_code || '').trim();
  if (!code) return;
  // 一到三级就先把分类记下来：只选到这一级、不再往下选也能提交，流水号由 PMC 补。
  if (categoryDepth(code) >= 3) applyCategory(line, item);
  state.path = [...state.path, code];
  state.parent = code;
  state.query = `${code} ${item.category_name || ''}`.trim();
  await loadCatMaterials(code);
  if (!hasChildren(item) && !(catMaterials[code] || []).length) {
    applyCategory(line, item);
    closePicker(line);
  }
}

function back(line) {
  const state = ui[line._uid];
  state.path = state.path.slice(0, -1);
  state.parent = state.path[state.path.length - 1] || '';
  loadCatMaterials(state.parent);
}

function canConfirm(line) {
  return !line.material_code && categoryDepth(S(line).parent) >= 3;
}

function confirmCategory(line) {
  const state = ui[line._uid];
  const item = props.categories.find((candidate) => candidate.category_code === state.parent);
  if (item) { applyCategory(line, item); state.query = state.parent; }
  closePicker(line);
}

// ---------------------------------------------------------------- PMC 查重复建议
function candidates(suggestion) {
  const dup = suggestion?.duplicates || {};
  return [...(dup.identity || []), ...(dup.spec || []), ...(dup.spec_format || [])]
    .filter((item, index, all) => all.findIndex((other) => other.material_code === item.material_code) === index).slice(0, 3);
}

function useSuggestedCategory(line, suggestion) {
  const item = props.categories.find((candidate) => candidate.category_code === suggestion?.suggested_category?.category_code)
    || { category_code: suggestion.suggested_category.category_code, full_path: suggestion.suggested_category.category_path };
  applyCategory(line, item);
  ui[line._uid].query = item.category_code;
}

const names = (rows) => (rows || []).map((item) => item.material_code).join('、');
</script>

<template>
  <div class="pr-lines">
    <div class="pr-scroll">
      <div class="pr-lines-inner">
        <div class="pr-row pr-lhead"><span>#</span><span>物料编号</span><span>物料名称 *</span><span>规格型号 *</span><span>品牌 *</span><span>数量 *</span><span>单位 *</span><span></span></div>
        <div v-for="(line, index) in lines" :key="line._uid" class="pr-line">
          <div class="pr-row">
            <span class="muted pr-no">{{ index + 1 }}</span>
            <div class="pr-code">
              <div class="pr-code-box">
                <input
                  v-model="S(line).query" :class="{ bound: line.material_code, pending: !line.material_code && line.category_code }"
                  placeholder="搜索物料编号或名称" aria-label="物料编号" title="至少选择到三级；没有下一级时可停在当前级，由 PMC 后续补全"
                  @input="onType(line)" @focus="search(line)" @keydown.enter.prevent="pickFirst(line)"
                />
                <button type="button" class="pr-drop" :aria-expanded="S(line).cat" aria-label="按分类逐级选择物料编号" @click="S(line).cat ? closePicker(line) : openPicker(line)">{{ S(line).cat ? '▴' : '▾' }}</button>
              </div>
              <div v-if="line.category_code" class="pr-code-note">
                <span>{{ line.material_code ? '已绑定物料编号' : '待 PMC 完善：' }}<span class="num">{{ lineCodeText(line) }}</span></span>
                <button v-if="line.material_code" type="button" class="link" @click="unbind(line)">改为新增物料</button>
                <button v-if="mode === 'pmc' && !line.material_code" type="button" class="link" @click="emit('suggest', line)">查重复</button>
              </div>
            </div>
            <textarea v-model="line.item_name" v-auto-grow rows="1" :readonly="Boolean(line.material_code)" :class="{ locked: line.material_code }" aria-label="物料名称"></textarea>
            <textarea v-model="line.specification" v-auto-grow rows="1" :readonly="Boolean(line.material_code)" :class="{ locked: line.material_code }" aria-label="规格型号"></textarea>
            <textarea v-model="line.brand" v-auto-grow rows="1" :readonly="Boolean(line.material_code)" :class="{ locked: line.material_code }" aria-label="商品品牌"></textarea>
            <input v-model.number="line.quantity" type="number" min="0.0001" step="0.0001" class="r" aria-label="数量" />
            <input v-model="line.unit" aria-label="计量单位" />
            <span class="pr-row-actions">
              <button type="button" class="link" :aria-expanded="S(line).more" @click="S(line).more = !S(line).more">{{ S(line).more ? '收起' : '更多' }}</button>
              <button type="button" class="pr-x" :disabled="lines.length < 2" aria-label="删除这一行" @click="removeLine(index)">×</button>
            </span>
          </div>

          <div v-if="S(line).cat" class="pr-picker">
            <div v-if="line.material_code" class="pr-picker-note">已选物料编号 <button type="button" class="link" @click="unbind(line)">不绑定物料编号，交由 PMC 补充</button></div>
            <div class="pr-crumbs">
              <button v-if="S(line).path.length" type="button" class="btn sm" @click="back(line)">返回</button>
              <span>{{ S(line).path.length ? pathLabels(line) : '选择一级分类' }}</span>
              <button type="button" class="link pr-right" @click="closePicker(line)">收起</button>
            </div>
            <div class="pr-picker-list">
              <button v-for="item in children(line)" :key="item.category_code" type="button" class="pr-pick" @click="chooseCategory(line, item)">
                <span><span class="num muted">{{ item.category_code }}</span> {{ item.category_name }}</span>
                <span v-if="hasChildren(item)" class="muted">›</span>
              </button>
              <template v-if="(catMaterials[S(line).parent] || []).length">
                <p class="muted pr-picker-title">选择物料编号</p>
                <button v-for="item in catMaterials[S(line).parent]" :key="item.material_code" type="button" class="pr-pick" @click="pickMaterial(line, item)">
                  <span><span class="num muted">{{ item.material_code }}</span> <b>{{ item.material_name }}</b><span class="muted pr-pick-sub">{{ item.specification || '-' }} · {{ item.brand || '-' }} · {{ item.unit || '-' }}</span></span>
                </button>
              </template>
              <p v-if="!children(line).length && !(catMaterials[S(line).parent] || []).length" class="muted pr-picker-empty">{{ catLoading[S(line).parent] ? '正在读取…' : '暂无下级分类或物料' }}</p>
            </div>
            <div v-if="canConfirm(line)" class="pr-picker-confirm"><button type="button" class="btn pri sm" @click="confirmCategory(line)">确认当前物料编号，交由 PMC 后续完善</button></div>
          </div>
          <div v-else-if="S(line).open && S(line).matches.length" class="pr-picker">
            <button v-for="item in S(line).matches" :key="item.material_code" type="button" class="pr-pick" @click="pickMaterial(line, item)">
              <span><span class="num muted">{{ item.material_code }}</span> <b>{{ item.material_name }}</b><span class="muted pr-pick-sub">{{ item.specification || item.category_path }}</span></span>
            </button>
            <div class="muted pr-picker-foot">找不到？只选到三级分类也可以提交，用右边的 ▾ 按分类选，不绑定编号交给 PMC 补充。</div>
          </div>

          <div v-if="suggestions[line._uid]" class="pr-suggest">
            <b>{{ suggestions[line._uid].risk_assessment?.level }}</b>
            <span>{{ suggestions[line._uid].risk_assessment?.action }}</span>
            <span v-if="suggestions[line._uid].duplicates?.identity?.length" class="err-text">名称、规格型号、品牌完全一致：{{ names(suggestions[line._uid].duplicates.identity) }}，建议绑定已有物料。</span>
            <span v-else-if="suggestions[line._uid].duplicates?.spec?.length" class="err-text">规格型号命中：{{ names(suggestions[line._uid].duplicates.spec) }}，建议先核对后再新增。</span>
            <span v-if="suggestions[line._uid].duplicates?.spec_format?.length">规格型号只是分隔符 / 书写格式不同：{{ names(suggestions[line._uid].duplicates.spec_format) }}，请人工确认是否同一型号。</span>
            <span v-if="suggestions[line._uid].duplicates?.name?.length" class="muted">仅名称相同：{{ names(suggestions[line._uid].duplicates.name) }}，请继续核对规格、品牌和用途。</span>
            <button v-for="item in candidates(suggestions[line._uid])" :key="item.material_code" type="button" class="link" @click="pickMaterial(line, item)">绑定 {{ item.material_code }}</button>
            <span v-if="suggestions[line._uid].suggested_category" class="muted">
              分类建议：{{ suggestions[line._uid].suggested_category.category_code }}（{{ suggestions[line._uid].suggested_category.category_path || '分类路径待补充' }}，置信度 {{ suggestions[line._uid].suggested_category.confidence }}%）
              <button type="button" class="link" @click="useSuggestedCategory(line, suggestions[line._uid])">采用</button>
            </span>
          </div>

          <div v-if="S(line).more" class="pr-more">
            <label><span>产品描述</span><textarea v-model="line.product_desc" v-auto-grow rows="1" :readonly="Boolean(line.material_code)" :class="{ locked: line.material_code }"></textarea></label>
            <label><span>Product name</span><textarea v-model="line.product_name" v-auto-grow rows="1" :readonly="Boolean(line.material_code)" :class="{ locked: line.material_code }" :placeholder="line.material_code ? '物料库未填写' : 'Product name'"></textarea></label>
            <label><span>Product description</span><textarea v-model="line.product_desc_en" v-auto-grow rows="1" :readonly="Boolean(line.material_code)" :class="{ locked: line.material_code }" :placeholder="line.material_code ? '物料库未填写' : 'Product description'"></textarea></label>
            <label><span>Brand</span><textarea v-model="line.brand_en" v-auto-grow rows="1" :readonly="Boolean(line.material_code)" :class="{ locked: line.material_code }" :placeholder="line.material_code ? '物料库未填写' : 'Brand'"></textarea></label>
            <label><span>备注</span><textarea v-model="line.remarks" v-auto-grow rows="1"></textarea></label>
          </div>
        </div>
      </div>
    </div>
    <div class="muted pr-lines-note">绑定了物料编号的行，名称、规格等自动带出、不能改（灰底）。单价在询价后录入，这里不再占一列。每行点"更多"填产品描述、英文名称 / 描述 / 品牌、备注。</div>
  </div>
</template>
