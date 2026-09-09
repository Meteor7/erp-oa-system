import { frappeRequest } from 'frappe-ui';

const LOGIN_METHOD = '/api/method/frappe.auth.get_logged_user';
const CANONICAL_LOCAL_HOST = 'rayher.localhost';
let sessionCheck = null;
let redirecting = false;

function normalizedUser(value) {
  return String(value || '').trim().toLowerCase();
}

function currentTarget() {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`;
}

function loginUrl() {
  return `/login?redirect-to=${encodeURIComponent(currentTarget())}`;
}

function redirectToLogin() {
  if (redirecting) return;
  redirecting = true;
  window.location.replace(loginUrl());
}

export function enforceCanonicalLocalHost() {
  if (window.location.hostname !== 'localhost') return false;
  const target = new URL(window.location.href);
  target.hostname = CANONICAL_LOCAL_HOST;
  window.location.replace(target.toString());
  return true;
}

export async function verifyBrowserSession() {
  if (redirecting) return false;
  if (sessionCheck) return sessionCheck;

  sessionCheck = fetch(LOGIN_METHOD, {
    method: 'GET',
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      'X-Frappe-Site-Name': window.location.hostname,
    },
  })
    .then(async (response) => {
      if (response.status === 401 || response.status === 403) {
        redirectToLogin();
        return false;
      }
      if (!response.ok) return true;

      const payload = await response.json();
      const serverUser = normalizedUser(payload?.message);
      const pageUser = normalizedUser(window.user);
      if (!serverUser || serverUser === 'guest') {
        redirectToLogin();
        return false;
      }
      if (pageUser && serverUser !== pageUser) {
        redirecting = true;
        window.location.reload();
        return false;
      }
      return true;
    })
    .catch(() => true)
    .finally(() => {
      sessionCheck = null;
    });

  return sessionCheck;
}

export async function guardedFrappeRequest(options) {
  try {
    return await frappeRequest(options);
  } catch (error) {
    const status = Number(error?.response?.status || error?.status || 0);
    if (status === 401 || status === 403) await verifyBrowserSession();
    throw error;
  }
}

export function installSessionGuard() {
  const checkWhenActive = () => {
    if (document.visibilityState === 'visible') verifyBrowserSession();
  };
  window.addEventListener('focus', checkWhenActive);
  document.addEventListener('visibilitychange', checkWhenActive);
  window.setInterval(checkWhenActive, 30000);
}
