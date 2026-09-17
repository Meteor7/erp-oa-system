import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../src/pages/OAApprovals.vue', import.meta.url), 'utf8');
const implementation = source.slice(source.indexOf('async function refreshAttendance('), source.indexOf('async function withdrawAttendance('));
function fixture() {
  const requests = [];
  const context = vm.createContext({
    isLeave: {value:true}, currentRequestType: {value:'请假申请'},
    leaveForm: {from_date:'2026-09-21',to_date:'2026-10-09',attendance_days:[]},
    attendanceOptions: {fetch: () => new Promise(resolve => requests.push(resolve))},
    attendanceBalance:{value:null},annualBalance:{value:null},leaveTypes:{value:[]},
    errMsg:{value:''},serverMessage: error => String(error),T:{loadFailed:'failed'},
  });
  vm.runInContext('let attendanceVersion = 0; let attendanceDaysLoading = false;'+implementation, context);
  return {context,requests,call: replace => vm.runInContext(`refreshAttendance(${replace})`,context)};
}
const result = hours => ({balance:{available_hours:8},annual_balance:{available_hours:80},leave_types:['事假','年假'],days:[{work_date:'2026-09-21',hours}]});
test('polling cannot cancel a pending date-grid update', async () => {
  const {context,requests,call}=fixture();
  const dateChange=call(true);
  await call(false);
  assert.equal(requests.length,1);
  requests[0](result(8)); await dateChange;
  assert.equal(context.leaveForm.attendance_days[0].hours,8);
  context.leaveForm.attendance_days[0].hours=4;
  const poll=call(false);requests[1](result(8));await poll;
  assert.equal(context.leaveForm.attendance_days[0].hours,4);
});
test('stale date responses do not overwrite newer dates or unlock a pending update', async () => {
  const {context,requests,call}=fixture();
  const older=call(true); const newer=call(true);
  requests[0](result(8));await older;
  await call(false);assert.equal(requests.length,2);
  requests[1](result(4));await newer;
  assert.equal(context.leaveForm.attendance_days[0].hours,4);
});
