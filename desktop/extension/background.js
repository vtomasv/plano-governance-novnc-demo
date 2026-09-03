'use strict';

const AGENT_BASE_URL = 'http://governed-agent:10600';
const ROUTES = {
  PLANO_POLICY_CHECK: {path: '/api/policy-check', timeout: 30000},
  PLANO_WEB_RESULT: {path: '/api/web-result', timeout: 10000},
  PLANO_WEB_ERROR: {path: '/api/web-error', timeout: 10000},
};

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const route = ROUTES[message?.type];
  if (!route) return false;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), route.timeout);
  const payload = {...message};
  delete payload.type;

  fetch(`${AGENT_BASE_URL}${route.path}`, {
    method: 'POST',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify(payload),
    signal: controller.signal,
  })
    .then(async response => {
      let data;
      try { data = await response.json(); }
      catch { data = {message: await response.text()}; }
      sendResponse({ok: response.ok, httpStatus: response.status, ...data});
    })
    .catch(error => {
      sendResponse({
        ok: false,
        allowed: false,
        message: `Plano no está disponible; la política falla en modo cerrado. ${error.message}`,
        errorType: error.name || 'FetchError',
      });
    })
    .finally(() => clearTimeout(timeout));

  return true;
});
