function cleanMessage(value) {
  return String(value || '').replace(/<[^>]*>/g, '').trim();
}

function parseServerMessages(raw) {
  if (!raw) return '';
  try {
    const items = typeof raw === 'string' ? JSON.parse(raw) : raw;
    if (!Array.isArray(items)) return '';
    for (const item of items) {
      let value = item;
      try { if (typeof value === 'string') value = JSON.parse(value); } catch { /* plain message */ }
      const message = cleanMessage(value?.message || value);
      if (message) return message;
    }
  } catch { return ''; }
  return '';
}

export function extractFrappeError(error, fallback = '操作失败') {
  const payload = error?.response?.data || error?.data || error || {};
  const serverMessage = parseServerMessages(payload._server_messages || error?._server_messages);
  if (serverMessage) return serverMessage;
  const messages = payload.messages || error?.messages;
  if (Array.isArray(messages) && messages.length) return cleanMessage(messages[0]) || fallback;
  const message = cleanMessage(payload.message || error?.message);
  if (message && !/\/api\/method\/.+ValidationError/i.test(message) && message !== 'ValidationError') return message;
  return fallback;
}