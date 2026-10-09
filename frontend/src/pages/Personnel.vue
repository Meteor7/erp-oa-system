<script setup>
import { ref, reactive, computed, watch, nextTick, onMounted, onBeforeUnmount } from "vue";
import { createResource } from "frappe-ui";
import RdPage from "../components/rd/RdPage.vue";
import RdKpi from "../components/rd/RdKpi.vue";
import RdIcon from "../components/rd/RdIcon.vue";
import { displayCompany, displayDepartment } from "../lib/displayBrand.js";
import { extractFrappeError } from "../lib/frappeError.js";
import { isHrSensitiveHidden } from "../lib/access.js";
import {
  ARCHIVE_STATUSES as ARCH, NO_RD_TYPE, RD_TYPES, SORT_OPTIONS,
  archiveTone, avatarText, decorateEmployees, defaultRdType, departmentGroupMap, departmentGroups, displayFieldValue, filterEmployees, genderLabel,
  isMaskedField, kpiCounts, lastModifiedText, missingSummary, pageSlice, rdTone, sortEmployees, supervisorLabel,
  todayIso, visibleTabs,
} from "../lib/personnelView.js";
import { exportSheetsWorkbook } from "../lib/tableExport.js";
import {
  IMPORT_MAX_ROWS, SENSITIVE_EXPORT_LABEL, buildEmployeeExportSheet, buildEmployeeTemplateSheets, buildImportPreview,
  canImportEmployees, canOfferSensitiveExport, describeChange, employeeExportFilename, importEmployeeWorkbookFile,
  importResultText, pickExportRows,
} from "../lib/personnelTransfer.js";

const GENDERS=[{v:"Male",l:"男"},{v:"Female",l:"女"}];
const EXPENSE_ACCOUNT_CATEGORIES=["研发费用","管理费用","销售费用","生产成本"];
const api="rayher_hr_payroll.api.personnel_entry.";
const rows=createResource({url:api+"list_employees",method:"GET",auto:true});
const saver=createResource({url:api+"save_employee"});
const remover=createResource({url:api+"delete_employee"});
const previewer=createResource({url:api+"preview_employee_import"});
const importer=createResource({url:api+"import_employees"});
const companies=createResource({url:api+"get_company_options",method:"GET",auto:true});
const depts=createResource({url:api+"get_dept_options",method:"GET",auto:true});
const designations=createResource({url:api+"get_designation_options",method:"GET",auto:true});
const employmentTypes=createResource({url:api+"get_employment_type_options",method:"GET",auto:true});
const householdOptions=createResource({url:api+"get_household_options",method:"GET",auto:true});

const blank=()=>({
  name:"",company:"",employee_number:"",employee_name:"",english_name:"",date_of_birth:"",
  id_type_cn:"身份证",id_card_number_cn:"",gender:"Male",date_of_joining:"",relieving_date:"",
  department:"",designation:"",reports_to:"",employment_type:"",
  labour_contract_start_date:"",probation_months:"",probation_end_date:"",
  first_contract_period_years:"",first_contract_end_date:"",contract_renewal_status:"",
  second_contract_period_years:"",second_contract_end_date:"",
  default_monthly_salary:"",salary_months:"",
  first_education_level:"",first_education_school:"",first_education_major:"",
  education_level_cn:"",degree_cn:"",education_completion_type:"",
  graduation_school:"",major_cn:"",cell_number:"",household_registration:"",
  bank_name:"",bank_ac_no:"",social_insurance_number:"",housing_fund_number:"",
  default_social_insurance_base:"",default_housing_fund_base:"",
  rd_personnel_type:"",expense_account_category:"",archive_status:"待完善"
});
// 只带表单里有的字段（列表还多返回 status、modified 等，不能原样提交）；值为 null 的保持 null，服务端按「未提供」处理
const formFromRow=row=>{
  const base=blank();
  for(const key of Object.keys(base))if(row&&Object.prototype.hasOwnProperty.call(row,key))base[key]=row[key];
  return base;
};
const form=reactive(blank());
const editing=ref(false);
const saving=ref(false);
const errMsg=ref("");
const successNote=ref("");
const companyFilter=ref("");
const departmentFilter=ref("");
const keyword=ref("");
const statusFilter=ref("active");
const rdFilter=ref("");
const archiveFilter=ref("");
const alertOnly=ref(false);
const sortMode=ref("default");
const currentPage=ref(1);
const PAGE_SIZE=20;
const today=todayIso();

const canDelete=typeof window!=="undefined"&&Array.isArray(window.roles)&&window.roles.some(r=>["System Manager","HR Manager"].includes(r));
const showHrSensitive=!isHrSensitiveHidden();
const sensitiveHidden=!showHrSensitive;
const tabs=visibleTabs({sensitiveHidden});
const canImport=canImportEmployees(typeof window!=="undefined"?window.roles:[]);

// ---------- 列表数据 ----------
const groupOf=computed(()=>departmentGroupMap(depts.data||[]));
const items=computed(()=>decorateEmployees(rows.data||[],{today,sensitiveHidden,groupOf:groupOf.value}));
const nameById=computed(()=>new Map((rows.data||[]).map(x=>[x.name,x.employee_name])));
const supervisorName=row=>supervisorLabel(row,nameById.value)||"-";
const companyItems=computed(()=>companyFilter.value?items.value.filter(x=>x.row.company===companyFilter.value):items.value);
const kpi=computed(()=>kpiCounts(companyItems.value,today));
const statusCounts=computed(()=>({
  active:companyItems.value.filter(x=>!x.left).length,
  left:companyItems.value.filter(x=>x.left).length,
}));
const loaded=computed(()=>Array.isArray(rows.data));
const groups=computed(()=>departmentGroups(items.value,depts.data||[],{company:companyFilter.value,status:statusFilter.value}));
const departmentOptions=computed(()=>groups.value.flatMap(group=>group.departments.map(item=>item.name)));
const allDepartmentCount=computed(()=>statusFilter.value==="left"?statusCounts.value.left:statusCounts.value.active);
const filteredItems=computed(()=>sortEmployees(filterEmployees(items.value,{
  company:companyFilter.value,department:departmentFilter.value,status:statusFilter.value,
  rdType:rdFilter.value,archive:archiveFilter.value,alertOnly:alertOnly.value,keyword:keyword.value,
}),sortMode.value));
const pageData=computed(()=>pageSlice(filteredItems.value,currentPage.value,PAGE_SIZE));
const pageCount=computed(()=>pageData.value.pageCount);
const pagedItems=computed(()=>pageData.value.items);
watch([companyFilter,departmentFilter,keyword,statusFilter,rdFilter,archiveFilter,alertOnly,sortMode],()=>{currentPage.value=1});
watch([companyFilter,statusFilter],()=>{
  if(departmentFilter.value&&!departmentOptions.value.includes(departmentFilter.value))departmentFilter.value="";
});
watch(pageCount,count=>{if(currentPage.value>count)currentPage.value=count});

const formDepartmentOptions=computed(()=>(depts.data||[]).filter(x=>x.company===form.company));
function clearDepartmentIfOutsideCompany(){
  if(form.department&&!formDepartmentOptions.value.some(x=>x.name===form.department))form.department="";
}
// 新增员工时，选了部门就按部门带出研发人员类型（研发部门→全时研发，其他→非研发）；
// 只覆盖空值和上一次自动带出的值，HR 自己选的不动。已有员工不带。服务端保存时也会按同样规则补。
const autoRdType=ref("");
watch(()=>form.department,department=>{
  if(!editing.value||form.name)return;
  if(form.rd_personnel_type&&form.rd_personnel_type!==autoRdType.value)return;
  const meta=(depts.data||[]).find(x=>x.name===department);
  autoRdType.value=defaultRdType(meta?.group_name);
  form.rd_personnel_type=autoRdType.value;
});

// ---------- 抽屉里的字段 ----------
// type 决定编辑控件；查看页的显示规则在 viewCell()。virtual：只在查看里显示的派生项。
const SECTIONS={
  basic:[{title:"",fields:[
    {key:"company",label:"所属单位",type:"company",required:true,empty:"请选择"},
    {key:"employee_number",label:"员工号"},
    {key:"employee_name",label:"姓名",required:true},
    {key:"english_name",label:"英文名"},
    {key:"gender",label:"性别",type:"gender"},
    {key:"date_of_birth",label:"出生日期",type:"date"},
    {key:"cell_number",label:"联系电话"},
    {key:"household_registration",label:"户口信息",type:"household",placeholder:"例如：深圳、非深农村、湖北省襄阳市"},
  ]}],
  job:[
    {title:"任职",fields:[
      {key:"_status",label:"状态",virtual:true},
      {key:"_seniority",label:"司龄",virtual:true},
      {key:"date_of_joining",label:"入职时间",type:"date"},
      {key:"relieving_date",label:"离职时间",type:"date",hint:"离职日当天仍算在职，第二天起算已离职"},
      {key:"department",label:"部门",type:"department",empty:"未设置"},
      {key:"designation",label:"职位",type:"select",options:"designations",empty:"未设置"},
      {key:"reports_to",label:"直属主管",type:"select",options:"bosses",empty:"未设置"},
      {key:"employment_type",label:"合同类型",type:"select",options:"employmentTypes",empty:"未设置"},
      {key:"rd_personnel_type",label:"研发人员类型",type:"select",options:"rd",empty:"未设置"},
      {key:"expense_account_category",label:"费用科目",type:"select",options:"expense",empty:"未设置"},
      {key:"archive_status",label:"归档状态",type:"select",options:"archive"},
    ]},
    {title:"劳动合同",fields:[
      {key:"labour_contract_start_date",label:"劳动合同开始日期",type:"date"},
      {key:"probation_months",label:"试用期（月）",type:"number",min:0,step:1},
      {key:"probation_end_date",label:"试用期到期日",type:"date"},
      {key:"first_contract_period_years",label:"第一次合同期限（年）",type:"number",min:0,step:0.5},
      {key:"first_contract_end_date",label:"第一次劳动合同到期日",type:"date"},
      {key:"contract_renewal_status",label:"劳动合同续签情况"},
      {key:"second_contract_period_years",label:"第二次合同期限（年）",type:"number",min:0,step:0.5},
      {key:"second_contract_end_date",label:"第二次劳动合同到期日",type:"date"},
    ]},
  ],
  edu:[{title:"",fields:[
    {key:"first_education_level",label:"第一学历"},
    {key:"first_education_school",label:"第一学历学校"},
    {key:"first_education_major",label:"第一学历专业"},
    {key:"education_level_cn",label:"最高学历"},
    {key:"degree_cn",label:"学位"},
    {key:"education_completion_type",label:"学历完成形式"},
    {key:"graduation_school",label:"最高学历学校"},
    {key:"major_cn",label:"最高学历专业"},
  ]}],
  pay:[{title:"",fields:[
    {key:"default_monthly_salary",label:"工资",type:"number",min:0,step:0.01,right:true},
    {key:"salary_months",label:"薪资月数",type:"number",min:0,step:1,right:true},
    {key:"default_social_insurance_base",label:"社保基数",type:"number",min:0,step:0.01,right:true},
    {key:"default_housing_fund_base",label:"公积金基数",type:"number",min:0,step:0.01,right:true},
    {key:"social_insurance_number",label:"社保电脑号"},
    {key:"housing_fund_number",label:"公积金账号"},
  ]}],
  id:[{title:"",fields:[
    {key:"id_type_cn",label:"证件类型"},
    {key:"id_card_number_cn",label:"身份证号"},
    {key:"bank_name",label:"工资卡银行开户行及支行"},
    {key:"bank_ac_no",label:"工资卡银行账号"},
  ]}],
};

function optionsFor(field){
  switch(field.options||field.type){
    case "company":return (companies.data||[]).map(x=>({value:x.name,label:x.display_name||displayCompany(x.company_name||x.name)}));
    case "gender":return GENDERS.map(g=>({value:g.v,label:g.l}));
    case "department":{
      const list=formDepartmentOptions.value.map(x=>({value:x.name,label:displayDepartment(x.department_name||x.name)}));
      if(form.department&&!list.some(x=>x.value===form.department))list.unshift({value:form.department,label:displayDepartment(form.department)});
      return list;
    }
    case "designations":return (designations.data||[]).map(x=>({value:x,label:x}));
    case "employmentTypes":return (employmentTypes.data||[]).map(x=>({value:x,label:x}));
    case "bosses":return (rows.data||[]).filter(x=>x.name!==form.name).map(x=>({value:x.name,label:x.employee_name}));
    case "rd":return RD_TYPES.map(x=>({value:x,label:x}));
    case "expense":return EXPENSE_ACCOUNT_CATEGORIES.map(x=>({value:x,label:x}));
    case "archive":return ARCH.map(x=>({value:x,label:x}));
    default:return [];
  }
}
function emptyLabel(field){
  if(field.type==="department"&&!form.company)return "请先选择所属单位";
  return field.empty;
}

// ---------- 抽屉状态 ----------
const drawerOpen=ref(false);
const drawerName=ref("");
const drawerTab=ref("basic");
const reveal=reactive({});
const discardAsk=ref(false);
const askDelete=ref(false);
const snapshot=ref("");
const dialogEl=ref(null);
let openerSelector="";
let noteTimer=null;

const current=computed(()=>drawerName.value?items.value.find(x=>x.row.name===drawerName.value)||null:null);
const isNew=computed(()=>editing.value&&!form.name);
const isDirty=computed(()=>editing.value&&JSON.stringify(form)!==snapshot.value);
const drawerTitle=computed(()=>isNew.value?"新增员工":editing.value?"编辑员工":"员工详情");
const activeSections=computed(()=>SECTIONS[drawerTab.value]||[]);
const activeTabLocked=computed(()=>!!tabs.find(t=>t.key===drawerTab.value)?.locked);
const headName=computed(()=>isNew.value?(form.employee_name||"新员工"):(current.value?.row.employee_name||form.employee_name||""));
const headExtra=computed(()=>[current.value?.row.english_name,current.value?.row.employee_number].filter(Boolean).join(" · "));
const headTags=computed(()=>{
  const item=current.value;
  if(!item)return [];
  const list=[{text:item.left?"已离职":"在职",tone:item.left?"":"ok"}];
  if(item.rdType)list.push({text:item.rdType,tone:rdTone(item.rdType)});
  list.push({text:"档案"+item.archive,tone:archiveTone(item.archive)});
  for(const r of item.reminders)if(r.key!=="left"&&r.key!=="missing")list.push({text:r.text,tone:r.tone});
  return list;
});
const modifiedText=computed(()=>current.value?lastModifiedText(current.value.row):"");
const tabLabel=key=>tabs.find(t=>t.key===key)?.label||"";

function resetReveal(){for(const key of Object.keys(reveal))delete reveal[key]}
function setTab(key){drawerTab.value=key;resetReveal()}
function flashSuccess(text){
  successNote.value=text;
  clearTimeout(noteTimer);
  noteTimer=setTimeout(()=>{successNote.value=""},5000);
}
function focusDrawer(){
  nextTick(()=>{
    const el=dialogEl.value;
    if(!el)return;
    const first=editing.value?el.querySelector(".pd-body input, .pd-body select"):null;
    (first||el).focus({preventScroll:true});
  });
}
function openDrawer(selector){
  openerSelector=selector;
  drawerOpen.value=true;
  discardAsk.value=false;askDelete.value=false;
  errMsg.value="";successNote.value="";resetReveal();
  focusDrawer();
}
function openView(item){
  drawerName.value=item.row.name;editing.value=false;drawerTab.value="basic";
  openDrawer(`[data-emp="${String(item.row.name).replace(/["\\]/g,"\\$&")}"]`);
}
function startEdit(){
  const row=current.value?.row;
  if(!row)return;
  Object.assign(form,blank(),formFromRow(row));
  snapshot.value=JSON.stringify(form);
  editing.value=true;errMsg.value="";successNote.value="";discardAsk.value=false;askDelete.value=false;resetReveal();
  focusDrawer();
}
function newEmp(){
  Object.assign(form,blank());
  snapshot.value=JSON.stringify(form);
  drawerName.value="";editing.value=true;drawerTab.value="basic";
  openDrawer("[data-new-emp]");
}
function forceClose(){
  drawerOpen.value=false;editing.value=false;discardAsk.value=false;askDelete.value=false;errMsg.value="";resetReveal();
  const selector=openerSelector;
  nextTick(()=>{
    (document.querySelector(selector)||document.querySelector("[data-pl-search]"))?.focus({preventScroll:true});
  });
}
function requestClose(){
  if(saving.value||remover.loading)return;
  if(isDirty.value){discardAsk.value=true;askDelete.value=false;return}
  forceClose();
}
function cancelEdit(){
  if(saving.value)return;
  if(isDirty.value){discardAsk.value=true;askDelete.value=false;return}
  discard();
}
function discard(){
  discardAsk.value=false;askDelete.value=false;errMsg.value="";
  if(!form.name){forceClose();return}
  editing.value=false;
  focusDrawer();
}

async function save(){
  errMsg.value="";
  if(!form.employee_name||!form.company){
    errMsg.value="请填写姓名并选择所属单位";
    drawerTab.value="basic";
    return;
  }
  saving.value=true;
  try{
    const result=await saver.submit({...form});
    const savedName=result?.name||form.name;
    await rows.reload();
    editing.value=false;discardAsk.value=false;askDelete.value=false;
    if(savedName&&items.value.some(x=>x.row.name===savedName)){
      drawerName.value=savedName;
      resetReveal();
      flashSuccess("已保存，档案已更新");
      focusDrawer();
    }else forceClose();
  }
  catch(e){errMsg.value=extractFrappeError(e,"保存失败")}
  finally{saving.value=false}
}
async function del(){
  const name=form.name;
  if(!name)return;
  errMsg.value="";
  try{await remover.submit({name});await rows.reload();forceClose()}
  catch(e){askDelete.value=false;errMsg.value=extractFrappeError(e,"删除失败")}
}

// ---------- 查看页的取值 ----------
const ZERO_IS_EMPTY=["default_monthly_salary","default_social_insurance_base","default_housing_fund_base","salary_months"];
function viewCell(item,field){
  const row=item.row;
  const key=field.key;
  let text="";
  if(key==="_status")text=item.left?"已离职":"在职";
  else if(key==="_seniority")text=item.seniority;
  else{
    const value=row[key];
    const empty=value===null||value===undefined||String(value).trim()===""
      ||(ZERO_IS_EMPTY.includes(key)&&Number(value||0)<=0);
    if(!empty){
      if(key==="company")text=displayCompany(value);
      else if(key==="gender")text=genderLabel(value);
      else if(key==="department")text=displayDepartment(value);
      else if(key==="reports_to")text=supervisorName(row);
      else if(key==="salary_months")text=value+"薪";
      else if(key==="probation_months")text=value+" 个月";
      else if(key==="first_contract_period_years"||key==="second_contract_period_years")text=value+" 年";
      else text=displayFieldValue(key,value,{reveal:!!reveal[key]});
    }
  }
  return {text,blank:!text,masked:!!text&&isMaskedField(key),shown:!!reveal[key]};
}
function toggleReveal(key){reveal[key]=!reveal[key]}

// ---------- Excel 导入 / 导出 ----------
const transferNote=ref(null);
const importMenuOpen=ref(false);
const exportMenuOpen=ref(false);
const importWrap=ref(null);
const exportWrap=ref(null);
const importBtn=ref(null);
const exportBtn=ref(null);
const fileInput=ref(null);
const previewEl=ref(null);
const importState=ref(null);
const exporting=ref(false);
const includeSensitive=ref(false);
let transferTimer=null;
let importToken=0;

const sensitiveOffer=computed(()=>canOfferSensitiveExport({sensitiveHidden,rows:rows.data||[]}));
const exportActiveCount=computed(()=>pickExportRows("active",{all:items.value,company:companyFilter.value}).length);
const importBusy=computed(()=>importState.value?.stage==="checking"||importState.value?.stage==="importing");
const importPreview=computed(()=>importState.value?.preview||null);

function setNote(tone,text){
  transferNote.value={tone,text};
  clearTimeout(transferTimer);
  if(tone==="ok")transferTimer=setTimeout(()=>{transferNote.value=null},8000);
}
function closeMenus(refocus){
  const wasImport=importMenuOpen.value,wasExport=exportMenuOpen.value;
  importMenuOpen.value=false;exportMenuOpen.value=false;
  if(refocus)(wasImport?importBtn.value:wasExport?exportBtn.value:null)?.focus();
}
function toggleImportMenu(){
  const open=!importMenuOpen.value;
  closeMenus();importMenuOpen.value=open;
  if(open)nextTick(()=>importWrap.value?.querySelector('[role="menuitem"]')?.focus());
}
function toggleExportMenu(){
  const open=!exportMenuOpen.value;
  closeMenus();exportMenuOpen.value=open;
  if(open)nextTick(()=>exportWrap.value?.querySelector('[role="menuitem"]')?.focus());
}
function onPointerDown(event){
  if(importMenuOpen.value&&importWrap.value&&!importWrap.value.contains(event.target))importMenuOpen.value=false;
  if(exportMenuOpen.value&&exportWrap.value&&!exportWrap.value.contains(event.target))exportMenuOpen.value=false;
}

async function downloadTemplate(){
  closeMenus();
  try{
    await exportSheetsWorkbook({filename:"员工信息导入模板.xlsx",sheets:buildEmployeeTemplateSheets()});
    setNote("ok","已下载导入模板：员工信息导入模板.xlsx");
  }catch(e){setNote("bad",e?.message||"模板下载失败")}
}
function chooseFile(){
  closeMenus();
  if(importBusy.value)return;
  fileInput.value?.click();
}
function focusPreview(){
  nextTick(()=>{
    const el=previewEl.value;
    if(!el)return;
    el.scrollIntoView?.({block:"nearest"});
    el.focus({preventScroll:true});
  });
}
// 选好文件：先在浏览器里解析，再交给后端做只读检查；预览确认前不会写任何数据
async function onFile(event){
  const file=event.target.files?.[0];
  event.target.value="";
  if(!file||!canImport)return;
  transferNote.value=null;
  const token=++importToken;
  importState.value={token,fileName:file.name,stage:"checking",parsed:null,preview:null,error:""};
  focusPreview();
  try{
    const parsed=await importEmployeeWorkbookFile(file);
    if(token!==importToken)return;
    if(parsed.errors.length){importState.value=null;setNote("bad",parsed.errors.join("；"));return}
    importState.value={...importState.value,parsed};
    const response=await previewer.submit({rows:JSON.stringify(parsed.rows)});
    if(token!==importToken)return;
    importState.value={...importState.value,stage:"ready",preview:buildImportPreview(parsed,response)};
    focusPreview();
  }catch(e){
    if(token!==importToken)return;
    importState.value=null;
    setNote("bad",extractFrappeError(e,"Excel 读取或检查失败，请确认是员工信息模板"));
  }
}
function cancelImport(){
  if(importState.value?.stage==="importing")return;
  importToken+=1;importState.value=null;
}
// 确认后服务端会把文件重新检查一遍再整批写入（不使用预览结果）；失败会全部撤销
async function confirmImport(){
  const state=importState.value;
  if(!state||state.stage!=="ready"||!state.preview?.canConfirm)return;
  const token=state.token;
  importState.value={...state,stage:"importing",error:""};
  try{
    const result=await importer.submit({rows:JSON.stringify(state.parsed.rows)});
    if(token!==importToken)return;
    importState.value=null;
    await Promise.all([rows.reload(),depts.reload()]);
    setNote("ok",importResultText(result));
  }catch(e){
    if(token!==importToken)return;
    importState.value={...state,stage:"ready",error:extractFrappeError(e,"导入失败，本次没有写入任何数据")};
  }
}
async function doExport(mode){
  closeMenus();
  if(exporting.value)return;
  const list=pickExportRows(mode,{filtered:filteredItems.value,all:items.value,company:companyFilter.value});
  if(!list.length){setNote("bad","没有可导出的员工");return}
  const withSensitive=sensitiveOffer.value&&includeSensitive.value;
  exporting.value=true;
  try{
    const sheet=buildEmployeeExportSheet({rows:list,includeSensitive:withSensitive,sensitiveHidden,nameById:nameById.value});
    const filename=employeeExportFilename(today,withSensitive);
    await exportSheetsWorkbook({filename,sheets:[sheet]});
    setNote("ok",`已导出 ${list.length} 人：${filename}${withSensitive?"。文件含敏感信息，请妥善保管。":""}`);
  }catch(e){setNote("bad",e?.message||"导出失败")}
  finally{exporting.value=false;includeSensitive.value=false}
}

// ---------- 键盘 ----------
function onKeydown(event){
  if(event.key==="Escape"&&(importMenuOpen.value||exportMenuOpen.value)){event.preventDefault();closeMenus(true);return}
  if(event.key==="Escape"&&!drawerOpen.value&&importState.value&&!importBusy.value){event.preventDefault();cancelImport();return}
  if(!drawerOpen.value)return;
  if(event.key==="Escape"){
    if(saving.value||remover.loading)return;
    event.preventDefault();
    if(discardAsk.value){discardAsk.value=false;return}
    if(askDelete.value){askDelete.value=false;return}
    requestClose();
    return;
  }
  if(event.key!=="Tab"||!dialogEl.value)return;
  const focusables=[...dialogEl.value.querySelectorAll("button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])")]
    .filter(el=>el.offsetParent!==null||el===document.activeElement);
  if(!focusables.length)return;
  const first=focusables[0],last=focusables[focusables.length-1];
  const active=document.activeElement;
  if(event.shiftKey&&(active===first||active===dialogEl.value)){event.preventDefault();last.focus()}
  else if(!event.shiftKey&&active===last){event.preventDefault();first.focus()}
  else if(!dialogEl.value.contains(active)){event.preventDefault();first.focus()}
}
function onTabKey(event){
  const keys=tabs.map(t=>t.key);
  const index=keys.indexOf(drawerTab.value);
  let next=index;
  if(event.key==="ArrowRight")next=(index+1)%keys.length;
  else if(event.key==="ArrowLeft")next=(index-1+keys.length)%keys.length;
  else if(event.key==="Home")next=0;
  else if(event.key==="End")next=keys.length-1;
  else return;
  event.preventDefault();
  setTab(keys[next]);
  nextTick(()=>dialogEl.value?.querySelector(`[data-tab="${keys[next]}"]`)?.focus());
}
onMounted(()=>{window.addEventListener("keydown",onKeydown);document.addEventListener("mousedown",onPointerDown)});
onBeforeUnmount(()=>{
  window.removeEventListener("keydown",onKeydown);document.removeEventListener("mousedown",onPointerDown);
  clearTimeout(noteTimer);clearTimeout(transferTimer);importToken+=1;
});
</script>

<template>
<RdPage title="员工信息管理" subtitle="档案、合同、研发人员类型都在这里；点一行看详情，需要时再编辑。" crumb="人事中心">
<template #ctl>
<div v-if="canImport" ref="importWrap" class="pi-menuwrap">
<button ref="importBtn" type="button" class="btn" data-import-btn aria-haspopup="menu" :aria-expanded="importMenuOpen" :disabled="importBusy" @click="toggleImportMenu"><RdIcon name="upload"/>导入 ▾</button>
<div v-if="importMenuOpen" class="pi-menu" role="menu" aria-label="导入">
<button type="button" role="menuitem" class="pi-mi" data-import-template @click="downloadTemplate"><b>下载导入模板</b><span>带表头和示例行，另附填写说明</span></button>
<button type="button" role="menuitem" class="pi-mi" data-import-choose @click="chooseFile"><b>选择 Excel 文件…</b><span>先看预览，确认后才写入；一次最多 {{IMPORT_MAX_ROWS}} 行</span></button>
</div>
<input ref="fileInput" type="file" accept=".xlsx,.xls" class="pi-file" aria-label="选择员工信息 Excel 文件" tabindex="-1" @change="onFile"/>
</div>
<div ref="exportWrap" class="pi-menuwrap">
<button ref="exportBtn" type="button" class="btn" data-export-btn aria-haspopup="menu" :aria-expanded="exportMenuOpen" :disabled="!loaded||exporting" @click="toggleExportMenu"><RdIcon name="download"/>{{exporting?'导出中…':'导出 ▾'}}</button>
<div v-if="exportMenuOpen" class="pi-menu" role="menu" aria-label="导出">
<button type="button" role="menuitem" class="pi-mi" data-export-current @click="doExport('current')"><b>导出当前筛选结果</b><span>列表上现在筛出的 {{filteredItems.length}} 人（不受分页影响）</span></button>
<button type="button" role="menuitem" class="pi-mi" data-export-active @click="doExport('active')"><b>导出全部在职</b><span>{{exportActiveCount}} 人{{companyFilter?'（当前所属公司）':''}}，不受部门等筛选影响</span></button>
<template v-if="sensitiveOffer">
<div class="pi-sep" role="separator"></div>
<label class="pi-check"><input v-model="includeSensitive" type="checkbox" data-export-sensitive/><span>{{SENSITIVE_EXPORT_LABEL}}<small>勾选后文件名带“含敏感信息”，请妥善保管</small></span></label>
</template>
</div>
</div>
<button type="button" class="btn pri" data-new-emp @click="newEmp"><RdIcon name="plus"/>新增员工</button>
</template>

<div class="kpis">
<RdKpi label="在职员工" :value="loaded?kpi.active:'-'" :sub="loaded?`研发 ${kpi.rd} · 其他 ${kpi.other}${kpi.rdGap?` · 研发部门未设类型 ${kpi.rdGap}`:''}`:''" :tone="loaded&&kpi.rdGap?'warn':''"/>
<RdKpi label="本月入职" :value="loaded?kpi.joinedThisMonth:'-'" :sub="loaded?`试用期中 ${kpi.onProbation} 人`:''"/>
<RdKpi label="本月离职" :value="loaded?kpi.leftThisMonth:'-'" :sub="loaded?(kpi.leftPending?`已生效 ${kpi.leftEffective} · 待生效 ${kpi.leftPending}`:'按离职时间统计'):''"/>
<RdKpi label="档案待完善 / 待确认" :value="loaded?kpi.fileOpen:'-'" :sub="loaded?`待完善 ${kpi.filePending} · 待确认 ${kpi.fileConfirm}`:''" :tone="loaded&&kpi.fileOpen?'warn':''"/>
<RdKpi label="60 天内合同或试用期到期" :value="loaded?kpi.expiring:'-'" :sub="loaded?`试用期 ${kpi.expiringProbation} · 合同 ${kpi.expiringContract}`:''" :tone="loaded&&kpi.expiring?'warn':''"/>
</div>

<div v-if="transferNote" class="note" :class="transferNote.tone" :role="transferNote.tone==='bad'?'alert':'status'"><RdIcon :name="transferNote.tone==='bad'?'alert':'check'"/><span class="grow">{{transferNote.text}}</span><button type="button" class="btn sm" @click="transferNote=null">知道了</button></div>

<section v-if="importState" ref="previewEl" class="pi-preview" :class="{bad:importPreview&&importPreview.error>0}" role="region" aria-label="Excel 导入预览" tabindex="-1">
<div class="pi-head"><RdIcon name="upload"/><b>员工信息导入预览</b><span class="muted pi-file-name">{{importState.fileName}}</span></div>
<p v-if="importState.stage==='checking'" class="muted" role="status">正在读取并检查文件…</p>
<template v-else-if="importPreview">
<p class="pi-sum" role="status">共 <b class="num">{{importPreview.total}}</b> 行
· 新增 <b class="num">{{importPreview.create}}</b>
· 更新 <b class="num">{{importPreview.update}}</b>
· 无变化 <b class="num">{{importPreview.unchanged}}</b>
· 有问题 <b class="num" :class="{'pi-bad':importPreview.error}">{{importPreview.error}}</b></p>
<p v-if="importPreview.sensitiveIgnored" class="pi-line">当前账号没有敏感信息权限：文件里的工资、证件号、银行卡、社保公积金等列会被忽略，不会写入。</p>
<p v-if="importPreview.unknownHeaders.length" class="pi-line">有 {{importPreview.unknownHeaders.length}} 列没有识别，已忽略：{{importPreview.unknownHeaders.join('、')}}</p>
<div v-if="importPreview.problems.length" class="pi-block">
<div class="pi-block-t pi-bad">有问题的行（有问题的行不会单独导入，请先在 Excel 里改好，再重新选择文件）</div>
<table class="pi-tbl" aria-label="有问题的行"><thead><tr><th scope="col">行号</th><th scope="col">员工</th><th scope="col">问题</th></tr></thead><tbody>
<tr v-for="item in importPreview.problemsShown" :key="'e'+item.row"><td class="num nw">第 {{item.row}} 行</td><td class="nw">{{item.employee_number||'-'}} {{item.employee_name}}</td><td>{{item.errors.join('；')}}</td></tr>
<tr v-if="importPreview.problemsMore"><td colspan="3" class="muted">还有 {{importPreview.problemsMore}} 条有问题的行</td></tr>
</tbody></table>
</div>
<div v-if="importPreview.updates.length" class="pi-block">
<div class="pi-block-t">将更新的员工（旧值 → 新值，敏感内容已遮挡）</div>
<table class="pi-tbl" aria-label="将更新的员工"><thead><tr><th scope="col">行号</th><th scope="col">员工</th><th scope="col">变化</th></tr></thead><tbody>
<tr v-for="item in importPreview.updatesShown" :key="'u'+item.row"><td class="num nw">第 {{item.row}} 行</td><td class="nw">{{item.employee_number}} {{item.employee_name}}</td><td><div v-for="change in item.changes" :key="change.field">{{describeChange(change)}}</div></td></tr>
<tr v-if="importPreview.updatesMore"><td colspan="3" class="muted">还有 {{importPreview.updatesMore}} 人也会更新</td></tr>
</tbody></table>
</div>
<div v-if="importPreview.warned.length" class="pi-block">
<div class="pi-block-t">提醒（不影响导入）</div>
<ul class="pi-warns"><li v-for="item in importPreview.warnedShown" :key="'w'+item.row">第 {{item.row}} 行 {{item.employee_name||item.employee_number}}：{{item.warnings.join('；')}}</li><li v-if="importPreview.warnedMore" class="muted">还有 {{importPreview.warnedMore}} 行有提醒</li></ul>
</div>
<p v-if="!importPreview.error&&!importPreview.create&&!importPreview.update" class="pi-line">文件里的内容和系统里现有的一致，没有需要导入的变化。</p>
<div v-if="importState.error" class="note bad" role="alert"><RdIcon name="alert"/><span class="grow">{{importState.error}}</span></div>
</template>
<div class="pi-act"><button type="button" class="btn sm pri" data-import-confirm :disabled="importState.stage!=='ready'||!importPreview||!importPreview.canConfirm" @click="confirmImport">{{importState.stage==='importing'?'导入中…':'确认导入'}}</button><button type="button" class="btn sm" data-import-cancel :disabled="importState.stage==='importing'" @click="cancelImport">取消</button></div>
</section>

<div v-if="rows.error" class="note bad" role="alert"><RdIcon name="alert"/><span class="grow">员工列表加载失败，请稍后重试。</span><button type="button" class="btn sm" @click="rows.reload()">重试</button></div>

<div class="pl-layout">
<aside class="card pl-dept" aria-label="部门">
<div class="pl-dept-co"><label for="pl-company" class="muted">所属公司</label>
<select id="pl-company" v-model="companyFilter" class="field"><option value="">全部公司</option><option v-for="x in companies.data||[]" :key="x.name" :value="x.name">{{x.display_name||displayCompany(x.name)}}</option></select></div>
<button type="button" class="sd" :class="{on:!departmentFilter}" :aria-pressed="!departmentFilter" @click="departmentFilter=''"><span>全部部门</span><small>{{allDepartmentCount}}</small></button>
<template v-for="group in groups" :key="group.name">
<div class="sg"><span>{{group.name}}</span><small>{{group.total}} 人<template v-if="statusFilter==='active'&&group.name==='研发'&&group.fill"> · 填工时 {{group.fill}}</template></small></div>
<button v-for="department in group.departments" :key="group.name+department.name" type="button" class="sd" :class="{on:departmentFilter===department.name}" :aria-pressed="departmentFilter===department.name" @click="departmentFilter=department.name"><span>{{department.name}}</span><small>{{department.employee_count}}</small></button>
</template>
</aside>

<section class="card pl-main" aria-label="员工列表">
<div class="pl-tool">
<label class="input pl-search"><RdIcon name="search"/><input v-model="keyword" data-pl-search placeholder="搜索姓名、员工号、部门、职位" aria-label="搜索员工"/></label>
<select v-model="rdFilter" class="field pl-sel" aria-label="研发人员类型"><option value="">全部研发类型</option><option v-for="x in RD_TYPES" :key="x" :value="x">{{x}}</option><option :value="NO_RD_TYPE">未设置</option></select>
<select v-model="sortMode" class="field pl-sel" aria-label="排序"><option v-for="x in SORT_OPTIONS" :key="x.value" :value="x.value">{{x.label}}</option></select>
</div>
<div class="pl-tool">
<div class="chips" role="group" aria-label="在职状态">
<button type="button" class="chip" :aria-pressed="statusFilter==='active'" @click="statusFilter='active'">在职<small>{{statusCounts.active}}</small></button>
<button type="button" class="chip" :aria-pressed="statusFilter==='left'" @click="statusFilter='left'">已离职<small>{{statusCounts.left}}</small></button>
</div>
<span class="muted">档案：</span>
<div class="chips" role="group" aria-label="档案状态">
<button type="button" class="chip" :aria-pressed="!archiveFilter" @click="archiveFilter=''">全部</button>
<button v-for="x in ARCH" :key="x" type="button" class="chip" :aria-pressed="archiveFilter===x" @click="archiveFilter=x">{{x}}</button>
</div>
<button type="button" class="chip" :aria-pressed="alertOnly" @click="alertOnly=!alertOnly"><RdIcon name="bell"/> 只看有提醒</button>
</div>

<div v-if="rows.loading&&!loaded" class="bd muted">加载中…</div>
<div v-else class="tbl pl-tbl" tabindex="0" aria-label="员工表格，可左右滚动">
<table class="pl-table" aria-label="员工列表">
<thead><tr>
<th class="c1" scope="col">员工</th><th scope="col">员工号</th><th scope="col">部门 · 岗位</th><th scope="col">直属主管</th><th scope="col">入职 · 司龄</th><th scope="col">研发类型</th><th scope="col">档案</th><th scope="col">提醒</th>
</tr></thead>
<tbody>
<tr v-for="item in pagedItems" :key="item.key" class="pl-row" :class="{'pl-left':item.left}" @click="openView(item)">
<td class="c1"><button type="button" class="pl-who" :data-emp="item.row.name" :aria-label="`查看 ${item.row.employee_name} 的档案`" @click.stop="openView(item)"><span class="av" aria-hidden="true">{{avatarText(item.row.employee_name)}}</span><span class="pl-who-t"><b>{{item.row.employee_name}}</b><span class="muted">{{item.row.english_name||' '}}</span></span></button></td>
<td class="num nw muted">{{item.row.employee_number||'-'}}</td>
<td><div>{{item.department||'-'}}</div><div class="muted">{{item.row.designation||'-'}}</div></td>
<td class="nw">{{supervisorName(item.row)}}</td>
<td class="num nw"><div>{{item.row.date_of_joining||'-'}}</div><div class="muted">{{item.seniority||' '}}</div></td>
<td class="nw"><span v-if="item.rdType" class="tag" :class="rdTone(item.rdType)">{{item.rdType}}</span><span v-else class="muted">未设置</span></td>
<td class="nw"><span class="tag" :class="archiveTone(item.archive)">{{item.archive}}</span></td>
<td class="nw"><div class="pl-alerts">
<span v-for="r in item.reminders.slice(0,2)" :key="r.key" class="tag" :class="r.tone" :title="r.key==='missing'?missingSummary(item.progress.missing,8):r.text">{{r.text}}</span>
<span v-if="item.reminders.length>2" class="muted" :title="item.reminders.slice(2).map(r=>r.text).join('、')">+{{item.reminders.length-2}}</span>
</div></td>
</tr>
<tr v-if="!pagedItems.length"><td colspan="8" class="muted pl-empty">没有符合条件的员工</td></tr>
</tbody></table>
</div>
<div class="pl-foot">
<span class="muted">共 {{filteredItems.length}} 人，第 {{pageData.page}} / {{pageCount}} 页 · 薪资、证件号、银行卡等敏感信息不在列表里显示</span>
<div class="row"><button type="button" class="btn sm" :disabled="pageData.page<=1" @click="currentPage--">上一页</button><button type="button" class="btn sm" :disabled="pageData.page>=pageCount" @click="currentPage++">下一页</button></div>
</div>
</section>
</div>

<Teleport to="body">
<div v-if="drawerOpen" class="rd">
<div class="rd-drawer-bg" @click="requestClose"></div>
<aside ref="dialogEl" class="pd-drawer" role="dialog" aria-modal="true" :aria-label="drawerTitle+' '+headName" tabindex="-1">
<header class="pd-head">
<span class="pd-av" aria-hidden="true">{{isNew?'＋':avatarText(headName)}}</span>
<div class="pd-title">
<div class="pd-name"><b>{{headName}}</b><span v-if="headExtra" class="muted"> {{headExtra}}</span></div>
<div class="chips pd-tags">
<span v-if="isNew" class="tag brand">新增员工</span>
<template v-else>
<span v-if="editing" class="tag brand">编辑中</span>
<span v-for="t in headTags" :key="t.text" class="tag" :class="t.tone">{{t.text}}</span>
</template>
</div>
</div>
<button v-if="!editing&&current" type="button" class="btn pri" @click="startEdit"><RdIcon name="edit"/>编辑</button>
<button type="button" class="btn quiet sm" aria-label="关闭" @click="requestClose"><RdIcon name="x"/></button>
</header>

<div v-if="!editing&&current" class="pd-comp" :class="{full:current.progress.pct>=100}">
<div class="between row"><b>档案完整度 {{current.progress.pct}}%</b><span class="muted">{{missingSummary(current.progress.missing)}}</span></div>
<div class="meter" role="progressbar" aria-label="档案完整度" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="current.progress.pct"><i :style="{width:current.progress.pct+'%',background:current.progress.pct>=100?'var(--rd-ok)':'var(--rd-brand)'}"></i></div>
<div v-if="current.progress.missing.length" class="chips pd-miss"><button v-for="m in current.progress.missing" :key="m.key" type="button" class="pd-missbtn" :title="'到「'+tabLabel(m.tab)+'」页查看'" @click="setTab(m.tab)">{{m.label}}</button></div>
</div>

<div class="pd-tabs" role="tablist" aria-label="员工资料分类">
<button v-for="t in tabs" :key="t.key" type="button" role="tab" class="pd-tab" :data-tab="t.key" :aria-selected="drawerTab===t.key" :tabindex="drawerTab===t.key?0:-1" @click="setTab(t.key)" @keydown="onTabKey">{{t.label}}<RdIcon v-if="t.locked" name="lock"/></button>
</div>

<div class="pd-body" role="tabpanel">
<div v-if="successNote" class="note ok" role="status"><RdIcon name="check"/><span class="grow">{{successNote}}</span></div>
<div v-if="errMsg" class="note bad" role="alert"><RdIcon name="alert"/><span class="grow">{{errMsg}}</span></div>

<template v-if="!editing&&current">
<section v-for="(section,si) in activeSections" :key="si" class="pd-sec">
<h3 v-if="section.title" class="pd-sec-t">{{section.title}}</h3>
<div class="pd-kv">
<div v-for="field in section.fields" :key="field.key" class="pd-item">
<div class="k">{{field.label}}</div>
<div class="v" :class="{miss:viewCell(current,field).blank}">
<template v-if="viewCell(current,field).blank">未填写</template>
<template v-else>
<span class="num">{{viewCell(current,field).text}}</span>
<button v-if="viewCell(current,field).masked" type="button" class="btn sm" :aria-label="(viewCell(current,field).shown?'隐藏':'显示')+field.label" :aria-pressed="viewCell(current,field).shown" @click="toggleReveal(field.key)">{{viewCell(current,field).shown?'隐藏':'显示'}}</button>
</template>
</div>
</div>
</div>
</section>
<p v-if="activeTabLocked" class="muted pd-lock"><RdIcon name="lock"/> 含敏感信息，默认遮挡，点“显示”才显示明文；切换页签后自动重新遮挡。</p>
</template>

<template v-else-if="editing">
<section v-for="(section,si) in activeSections" :key="si" class="pd-sec">
<h3 v-if="section.title" class="pd-sec-t">{{section.title}}</h3>
<div class="pd-grid">
<template v-for="field in section.fields" :key="field.key">
<div v-if="!field.virtual" class="f">
<label :for="'pf-'+field.key">{{field.label}} <b v-if="field.required">*</b></label>
<select v-if="field.type==='company'" :id="'pf-'+field.key" v-model="form.company" class="field" @change="clearDepartmentIfOutsideCompany"><option v-if="field.empty" value="">{{emptyLabel(field)}}</option><option v-for="o in optionsFor(field)" :key="o.value" :value="o.value">{{o.label}}</option></select>
<select v-else-if="field.type==='gender'||field.type==='department'||field.type==='select'" :id="'pf-'+field.key" v-model="form[field.key]" class="field"><option v-if="field.empty" value="">{{emptyLabel(field)}}</option><option v-for="o in optionsFor(field)" :key="o.value" :value="o.value">{{o.label}}</option></select>
<template v-else-if="field.type==='household'"><input :id="'pf-'+field.key" v-model="form[field.key]" class="field" list="household-options" :placeholder="field.placeholder"/><datalist id="household-options"><option v-for="x in householdOptions.data||[]" :key="x" :value="x"/></datalist></template>
<input v-else-if="field.type==='date'" :id="'pf-'+field.key" v-model="form[field.key]" type="date" class="field"/>
<input v-else-if="field.type==='number'" :id="'pf-'+field.key" v-model="form[field.key]" type="number" :min="field.min" :step="field.step" class="field" :class="{'pd-right':field.right}"/>
<input v-else :id="'pf-'+field.key" v-model="form[field.key]" class="field"/>
<div v-if="field.hint" class="muted pd-hint">{{field.hint}}</div>
</div>
</template>
</div>
</section>
</template>
</div>

<footer class="pd-foot">
<template v-if="editing">
<div class="pd-foot-l">
<template v-if="discardAsk"><span class="muted">放弃未保存的修改？</span><button type="button" class="btn sm bad" @click="discard">放弃</button><button type="button" class="btn sm quiet" @click="discardAsk=false">继续编辑</button></template>
<template v-else-if="askDelete"><span class="muted">删除后无法恢复，确认删除“{{form.employee_name}}”？</span><button type="button" class="btn sm bad" :disabled="remover.loading" @click="del">确认删除</button><button type="button" class="btn sm quiet" @click="askDelete=false">返回</button></template>
<button v-else-if="canDelete&&form.name" type="button" class="btn quiet bad" @click="askDelete=true"><RdIcon name="trash"/>删除</button>
</div>
<div class="row pd-foot-r"><button type="button" class="btn" :disabled="saving" @click="cancelEdit">取消</button><button type="button" class="btn pri" :disabled="saving" @click="save">{{saving?'保存中…':'保存'}}</button></div>
</template>
<template v-else>
<span class="muted">{{modifiedText}}</span>
<button type="button" class="btn" @click="requestClose">关闭</button>
</template>
</footer>
</aside>
</div>
</Teleport>
</RdPage>
</template>

<style scoped>
.rd .pl-layout { display: grid; grid-template-columns: 224px minmax(0, 1fr); gap: 14px; align-items: start; }
.rd .pl-dept { padding: 6px 0 10px; position: sticky; top: 10px; max-height: calc(100vh - 24px); overflow: auto; margin-bottom: 0; }
.rd .pl-dept-co { padding: 10px 14px 8px; display: grid; gap: 4px; }
.rd .sd { display: flex; justify-content: space-between; align-items: center; gap: 8px; width: 100%; border: 0; border-left: 3px solid transparent; background: none; text-align: left; padding: 7px 14px; font-size: 13px; color: var(--rd-ink2); }
.rd .sd:hover { background: var(--rd-surface2); }
.rd .sd.on { background: var(--rd-brand-soft); border-left-color: var(--rd-brand); color: var(--rd-brand-d); font-weight: 600; }
.rd .sd small { color: var(--rd-ink3); font-weight: 400; font-variant-numeric: tabular-nums; }
.rd .sg { display: flex; justify-content: space-between; padding: 10px 14px 3px; font-size: 11.5px; color: var(--rd-ink3); }
.rd .pl-main { margin-bottom: 0; overflow: hidden; }
.rd .pl-tool { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 11px 16px; border-bottom: 1px solid var(--rd-line); }
.rd .pl-search { width: 280px; max-width: 100%; }
.rd .pl-sel { width: auto; min-width: 130px; }
.rd .chip svg.ic { width: 13px; height: 13px; vertical-align: -2px; }
.rd .pl-tbl { max-height: 68vh; }
.rd .pl-table { min-width: 1000px; }
.rd .pl-table th.c1, .rd .pl-table td.c1 { position: sticky; left: 0; border-right: 1px solid var(--rd-line); min-width: 190px; }
.rd .pl-table td.c1 { z-index: 1; background: var(--rd-surface); }
.rd .pl-table th.c1 { z-index: 4; background: var(--rd-surface2); }
.rd .pl-table tbody tr:hover td.c1 { background: var(--rd-surface2); }
.rd .pl-row { cursor: pointer; }
.rd .pl-left td { color: var(--rd-ink3); }
.rd .pl-who { display: flex; align-items: center; gap: 10px; border: 0; background: none; padding: 0; text-align: left; color: inherit; border-radius: 8px; }
.rd .pl-who-t { display: grid; line-height: 1.35; }
.rd .pl-who-t b { font-weight: 600; color: var(--rd-ink); }
.rd .pl-left .pl-who-t b { color: var(--rd-ink2); }
.rd .pl-alerts { display: flex; gap: 5px; align-items: center; }
.rd .pl-empty { text-align: center; padding: 36px; }
.rd .pl-foot { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; padding: 10px 16px; border-top: 1px solid var(--rd-line); }
.rd .tbl:focus-visible { outline-offset: -2px; }

.rd .pi-menuwrap { position: relative; display: inline-flex; }
.rd .pi-menu { position: absolute; top: calc(100% + 4px); right: 0; z-index: 20; width: min(310px, 86vw); background: var(--rd-surface); border: 1px solid var(--rd-line2); border-radius: 10px; box-shadow: 0 10px 28px rgba(20, 24, 40, .16); padding: 6px; display: flex; flex-direction: column; }
.rd .pi-mi { display: flex; flex-direction: column; align-items: flex-start; gap: 1px; text-align: left; border: 0; background: none; padding: 8px 10px; border-radius: 6px; font-size: 13px; white-space: normal; }
.rd .pi-mi:hover, .rd .pi-mi:focus-visible { background: var(--rd-surface2); }
.rd .pi-mi span { font-size: 12px; color: var(--rd-ink3); }
.rd .pi-sep { height: 1px; margin: 4px 6px; background: var(--rd-line); }
.rd .pi-check { display: flex; gap: 8px; align-items: flex-start; padding: 8px 10px; font-size: 12.5px; line-height: 1.45; cursor: pointer; }
.rd .pi-check input { margin-top: 3px; }
.rd .pi-check small { display: block; color: var(--rd-ink3); font-size: 11.5px; }
.rd .pi-file { display: none; }
.rd .pi-preview { margin-bottom: 12px; padding: 12px 16px; border-radius: 10px; border: 1px solid var(--rd-line2); background: var(--rd-surface); font-size: 13px; display: flex; flex-direction: column; gap: 8px; }
.rd .pi-preview:focus { outline: 0; }
.rd .pi-preview.bad { border-color: #F3C9C4; background: var(--rd-bad-soft); }
.rd .pi-preview p { margin: 0; }
.rd .pi-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rd .pi-file-name { font-size: 12px; overflow-wrap: anywhere; }
.rd .pi-sum b { font-weight: 650; }
.rd .pi-bad { color: var(--rd-bad); }
.rd .pi-line { color: var(--rd-ink2); }
.rd .pi-block { display: grid; gap: 4px; }
.rd .pi-block-t { font-size: 12.5px; font-weight: 600; }
.rd .pi-tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; background: var(--rd-surface); border: 1px solid var(--rd-line); border-radius: 8px; display: block; max-height: 240px; overflow: auto; }
.rd .pi-tbl th, .rd .pi-tbl td { text-align: left; padding: 5px 10px; border-bottom: 1px solid var(--rd-line); vertical-align: top; }
.rd .pi-tbl th { position: sticky; top: 0; background: var(--rd-surface2); font-weight: 600; color: var(--rd-ink2); }
.rd .pi-warns { margin: 0; padding-left: 18px; list-style: disc; color: var(--rd-ink2); }
.rd .pi-act { display: flex; gap: 8px; margin-top: 2px; }

.rd .pd-drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(600px, 100%); background: #fff; z-index: 61; box-shadow: -12px 0 40px rgba(14, 18, 26, .2); display: flex; flex-direction: column; color: var(--rd-ink); font-size: 14px; }
.rd .pd-drawer:focus { outline: 0; }
.rd .pd-head { padding: 16px 20px; display: flex; gap: 12px; align-items: center; border-bottom: 1px solid var(--rd-line); }
.rd .pd-av { width: 48px; height: 48px; border-radius: 50%; background: var(--rd-surface2); border: 1px solid var(--rd-line); color: var(--rd-ink2); display: grid; place-items: center; font-size: 15px; font-weight: 600; flex: none; }
.rd .pd-title { flex: 1; min-width: 0; }
.rd .pd-name { font-size: 18px; font-weight: 700; line-height: 1.35; overflow-wrap: anywhere; }
.rd .pd-name .muted { font-weight: 400; }
.rd .pd-tags { margin-top: 4px; }
.rd .pd-comp { padding: 12px 20px; background: var(--rd-warn-soft); border-bottom: 1px solid #E8C48A; font-size: 13px; display: grid; gap: 6px; }
.rd .pd-comp.full { background: var(--rd-ok-soft); border-bottom-color: var(--rd-line); }
.rd .pd-miss { gap: 5px; }
.rd .pd-missbtn { border: 1px solid #E8C48A; background: #fff; color: var(--rd-warn); border-radius: 6px; padding: 0 8px; font-size: 12px; height: 22px; }
.rd .pd-missbtn:hover { border-color: var(--rd-warn); }
.rd .pd-tabs { display: flex; gap: 2px; padding: 0 20px; border-bottom: 1px solid var(--rd-line); overflow-x: auto; }
.rd .pd-tab { display: inline-flex; align-items: center; gap: 4px; border: 0; border-bottom: 2px solid transparent; background: none; padding: 10px 11px; font-size: 13px; color: var(--rd-ink3); white-space: nowrap; }
.rd .pd-tab svg.ic { width: 12px; height: 12px; }
.rd .pd-tab[aria-selected="true"] { color: var(--rd-brand-d); border-bottom-color: var(--rd-brand); font-weight: 600; }
.rd .pd-body { flex: 1; overflow: auto; padding: 16px 20px; display: grid; gap: 14px; align-content: start; }
.rd .pd-body .note { margin: 0; }
.rd .pd-sec { display: grid; gap: 10px; }
.rd .pd-sec + .pd-sec { border-top: 1px solid var(--rd-line); padding-top: 14px; }
.rd .pd-sec-t { margin: 0; font-size: 13px; font-weight: 600; }
.rd .pd-kv { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 24px; }
.rd .pd-item { min-width: 0; }
.rd .pd-item .k { font-size: 12px; color: var(--rd-ink3); }
.rd .pd-item .v { margin-top: 1px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; overflow-wrap: anywhere; }
.rd .pd-item .v.miss { color: var(--rd-bad); }
.rd .pd-lock { margin: 0; display: flex; gap: 6px; align-items: center; }
.rd .pd-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.rd .pd-right { text-align: right; }
.rd .pd-hint { margin-top: 3px; }
.rd .pd-foot { padding: 12px 20px; border-top: 1px solid var(--rd-line); display: flex; gap: 10px; justify-content: space-between; align-items: center; flex-wrap: wrap; }
.rd .pd-foot-l { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; min-width: 0; }

@media (max-width: 900px) {
  .rd .pl-layout { grid-template-columns: minmax(0, 1fr); }
  .rd .pl-dept { position: static; max-height: 240px; }
  .rd .pl-search { width: 100%; }
}
@media (max-width: 640px) {
  .rd .pd-kv, .rd .pd-grid { grid-template-columns: minmax(0, 1fr); }
  .rd .pd-head, .rd .pd-body, .rd .pd-foot, .rd .pd-tabs, .rd .pd-comp { padding-left: 14px; padding-right: 14px; }
}
</style>
