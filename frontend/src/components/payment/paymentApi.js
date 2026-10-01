// 采购付款页面用到的接口地址和文件上传。接口本身用 frappe-ui 的 createResource 调用。
import { extractFrappeError } from '../../lib/frappeError.js';

export const PROCUREMENT_API = 'rayher_hr_payroll.api.procurement_chain.';
export const OA_API = 'rayher_hr_payroll.api.oa_entry.';
export const PAYMENT_REQUEST_TYPE = '采购付款';

export function errorText(error, fallback) { return extractFrappeError(error, fallback); }

// 私有上传，返回 file_ref（File 文档名）；之后由登记接口把它挂到记录上。
export async function uploadEvidence(file) {
  const body = new FormData();
  body.append('file', file);
  body.append('is_private', '1');
  const response = await fetch('/api/method/upload_file', {
    method: 'POST', body, credentials: 'same-origin', headers: { 'X-Frappe-CSRF-Token': window.csrf_token || '' },
  });
  const data = await response.json();
  if (!response.ok || data.exc) throw new Error((typeof data.message === 'string' && data.message) || '上传失败');
  return { name: data.message.name, filename: data.message.file_name || file.name };
}
