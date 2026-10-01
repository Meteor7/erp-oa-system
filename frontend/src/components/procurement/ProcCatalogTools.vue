<script setup>
// 物料目录维护：新增分类、新增正式物料。只给 PMC / 采购（canMaintainProcurementCatalog），后端同样校验。
import { reactive, ref } from 'vue';
import { categoryDepth } from '../../lib/procurementView.js';
import { apiPost, errText } from './procData.js';
import { useProc } from './context.js';

const emit = defineEmits(['category-saved']);
const ctx = useProc();
const saving = ref(false);
const category = reactive({ category_code: '', category_name: '', parent_category: '', full_path: '' });
const material = reactive({ material_code: '', category_code: '', material_name: '', specification: '', product_desc: '', brand: '', unit: '个', category_path: '', material_attr: '外购' });

async function saveCategory() {
  if (!category.category_code.trim() || !category.category_name.trim()) { ctx.flash('', '请填写分类编码和名称'); return; }
  saving.value = true;
  ctx.flash();
  try {
    await apiPost('procurement_materials.save_category', { ...category });
    ctx.flash(`分类 ${category.category_code} 已保存`);
    Object.assign(category, { category_code: '', category_name: '', parent_category: '', full_path: '' });
    emit('category-saved');
  } catch (error) {
    ctx.flash('', errText(error, '分类保存失败'));
  } finally {
    saving.value = false;
  }
}

async function saveMaterial() {
  const required = ['material_code', 'category_code', 'material_name', 'specification', 'product_desc', 'brand', 'unit'];
  if (required.some((field) => !String(material[field] || '').trim())) { ctx.flash('', '请完整填写物料编号、物料编号层级及物料资料'); return; }
  if (categoryDepth(material.category_code) < 3) { ctx.flash('', '物料编号至少需要三级'); return; }
  saving.value = true;
  ctx.flash();
  try {
    await apiPost('procurement_materials.save_material', { ...material });
    ctx.flash(`物料 ${material.material_code} 已保存`);
    Object.assign(material, { material_code: '', category_code: '', material_name: '', specification: '', product_desc: '', brand: '', unit: '个', category_path: '', material_attr: '外购' });
  } catch (error) {
    ctx.flash('', errText(error, '物料保存失败'));
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="pr-catalog">
    <form class="pr-catalog-form" @submit.prevent="saveCategory">
      <h4>新增或修改分类</h4>
      <div class="form">
        <div class="f"><label>分类编码</label><input v-model="category.category_code" placeholder="例如 1.ELC.3.3" /></div>
        <div class="f"><label>分类名称</label><input v-model="category.category_name" /></div>
        <div class="f"><label>父级编码</label><input v-model="category.parent_category" /></div>
        <div class="f"><label>完整路径</label><input v-model="category.full_path" /></div>
      </div>
      <div class="actions"><button type="submit" class="btn" :disabled="saving">保存分类</button></div>
    </form>
    <form class="pr-catalog-form" @submit.prevent="saveMaterial">
      <h4>新增或修改正式物料</h4>
      <div class="form">
        <div class="f"><label>物料编号</label><input v-model="material.material_code" placeholder="例如 1.ELC.3.3.01.001" /></div>
        <div class="f"><label>物料编号层级</label><input v-model="material.category_code" placeholder="例如 1.ELC.3" /></div>
        <div class="f"><label>物料名称</label><input v-model="material.material_name" /></div>
        <div class="f"><label>规格型号</label><input v-model="material.specification" /></div>
        <div class="f"><label>商品品牌</label><input v-model="material.brand" /></div>
        <div class="f"><label>计量单位</label><input v-model="material.unit" /></div>
        <div class="f s2"><label>产品描述</label><textarea v-model="material.product_desc" rows="2"></textarea></div>
      </div>
      <div class="actions"><button type="submit" class="btn" :disabled="saving">保存物料</button></div>
    </form>
  </div>
</template>
