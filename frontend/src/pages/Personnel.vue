<script setup>
import { ref, reactive, computed } from "vue";
import { Card, Button, Badge, createResource } from "frappe-ui";

const RD_TYPES = ["全时研发", "非全时研发", "研发辅助", "非研发"];
const ARCH = ["待完善", "待确认", "已归档"];
const GENDERS = [{ v: "Male", l: "男" }, { v: "Female", l: "女" }];

const rows = createResource({ url: "rayher_hr_payroll.api.personnel_entry.list_employees", method: "GET", auto: true });
const saver = createResource({ url: "rayher_hr_payroll.api.personnel_entry.save_employee" });
const remover = createResource({ url: "rayher_hr_payroll.api.personnel_entry.delete_employee" });
const depts = createResource({ url: "rayher_hr_payroll.api.personnel_entry.get_dept_options", method: "GET", auto: true });

const blank = () => ({ name: "", employee_name: "", id_card_number_cn: "", gender: "Male",
  date_of_joining: "", rd_personnel_type: "", archive_status: "待完善", department: "",
  rd_mock_base: "", rd_mock_social: "", rd_mock_fund: "", rd_mock_tax: "" });
const form = reactive(blank());
const editing = ref(false);
const saving = ref(false);
const errMsg = ref("");

const fmt = (n) => (n || 0).toLocaleString("zh-CN");
const archTheme = (s) => (s === "已归档" ? "green" : s === "待确认" ? "orange" : "gray");
const genderLabel = (v) => (v === "Female" ? "女" : v === "Male" ? "男" : v || "—");

function newEmp() { Object.assign(form, blank()); editing.value = true; errMsg.value = ""; }
function edit(r) { Object.assign(form, blank(), r); editing.value = true; errMsg.value = ""; }
function cancel() { editing.value = false; }

async function save() {
  errMsg.value = "";
  if (!form.employee_name) { errMsg.value = "请填写姓名"; return; }
  saving.value = true;
  try {
    await saver.submit({ ...form,
      rd_mock_base: Number(form.rd_mock_base || 0), rd_mock_social: Number(form.rd_mock_social || 0),
      rd_mock_fund: Number(form.rd_mock_fund || 0), rd_mock_tax: Number(form.rd_mock_tax || 0) });
    editing.value = false; rows.reload();
  } catch (e) { errMsg.value = (e && e.message) || "保存失败"; }
  finally { saving.value = false; }
}
const canDelete = typeof window !== "undefined" && Array.isArray(window.roles) && window.roles.some((r) => ["System Manager", "HR Manager"].includes(r));
async function del(n) { try { await remover.submit({ name: n }); rows.reload(); } catch (e) { errMsg.value = (e && e.message) || "删除失败"; } }
</script>

<template>
  <div class="space-y-4">
    <Card title="人事信息管理" subtitle="录入员工信息，信息齐全且归档后研发人员自动进入台账">
      <template #actions><Button variant="solid" @click="newEmp">+ 新增员工</Button></template>

      <div v-if="editing" class="p-4 bg-gray-50 rounded-lg mb-4 space-y-3">
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">姓名 *</label><input v-model="form.employee_name" class="border border-gray-300 rounded px-3 py-2 text-sm" /></div>
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">身份证号</label><input v-model="form.id_card_number_cn" class="border border-gray-300 rounded px-3 py-2 text-sm" /></div>
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">性别</label><select v-model="form.gender" class="border border-gray-300 rounded px-3 py-2 text-sm"><option v-for="g in GENDERS" :key="g.v" :value="g.v">{{ g.l }}</option></select></div>
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">入职日期</label><input v-model="form.date_of_joining" type="date" class="border border-gray-300 rounded px-3 py-2 text-sm" /></div>
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">研发人员类型</label><select v-model="form.rd_personnel_type" class="border border-gray-300 rounded px-3 py-2 text-sm"><option v-for="t in RD_TYPES" :key="t" :value="t">{{ t || "（非研发）" }}</option></select></div>
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">归档状态</label><select v-model="form.archive_status" class="border border-gray-300 rounded px-3 py-2 text-sm"><option v-for="a in ARCH" :key="a" :value="a">{{ a }}</option></select></div>
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">部门（归档必填）</label><select v-model="form.department" class="border border-gray-300 rounded px-3 py-2 text-sm"><option value="">（未设置）</option><option v-for="x in (depts.data || [])" :key="x.name" :value="x.name">{{ x.department_name || x.name }}</option></select></div>
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">应发工资</label><input v-model="form.rd_mock_base" type="number" class="border border-gray-300 rounded px-3 py-2 text-sm" /></div>
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">社保</label><input v-model="form.rd_mock_social" type="number" class="border border-gray-300 rounded px-3 py-2 text-sm" /></div>
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">公积金</label><input v-model="form.rd_mock_fund" type="number" class="border border-gray-300 rounded px-3 py-2 text-sm" /></div>
          <div class="flex flex-col"><label class="text-xs text-gray-500 mb-1">个税</label><input v-model="form.rd_mock_tax" type="number" class="border border-gray-300 rounded px-3 py-2 text-sm" /></div>
        </div>
        <p v-if="errMsg" class="text-red-600 text-xs">{{ errMsg }}</p>
        <div class="flex gap-2"><Button variant="solid" :loading="saving" @click="save">保存</Button><Button variant="subtle" @click="cancel">取消</Button></div>
        <p class="text-xs text-gray-400">归档状态设为「已归档」时，系统会校验信息是否齐全（身份证≥15位、入职、应发&gt;0 等）。</p>
      </div>

      <div v-if="rows.loading" class="text-gray-500 text-sm py-4">加载中…</div>
      <table v-else class="w-full text-sm">
        <thead class="text-gray-500 border-b"><tr>
          <th class="text-left px-3 py-2">姓名</th><th class="text-left px-3 py-2">性别</th>
          <th class="text-left px-3 py-2">入职</th><th class="text-left px-3 py-2">研发类型</th>
          <th class="text-right px-3 py-2">应发</th><th class="text-left px-3 py-2">归档</th><th class="text-right px-3 py-2">操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="e in rows.data || []" :key="e.name" class="border-b last:border-0 hover:bg-gray-50">
            <td class="px-3 py-2">{{ e.employee_name }}</td>
            <td class="px-3 py-2">{{ genderLabel(e.gender) }}</td>
            <td class="px-3 py-2">{{ e.date_of_joining || "—" }}</td>
            <td class="px-3 py-2">{{ e.rd_personnel_type || "—" }}</td>
            <td class="text-right px-3 py-2 tabular-nums">{{ fmt(e.rd_mock_base) }}</td>
            <td class="px-3 py-2"><Badge :theme="archTheme(e.archive_status)">{{ e.archive_status || "—" }}</Badge></td>
            <td class="text-right px-3 py-2 whitespace-nowrap">
              <button @click="edit(e)" class="text-blue-600 hover:underline text-xs mr-2">编辑</button>
              <button v-if="canDelete" @click="del(e.name)" class="text-red-600 hover:underline text-xs">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="text-xs text-gray-400 mt-3">共 {{ (rows.data || []).length }} 人</p>
    </Card>
  </div>
</template>
