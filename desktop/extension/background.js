const POLICY_URL = 'http://governed-agent:10600/api/policy-check';

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== 'PLANO_POLICY_CHECK') return false;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  fetch(POLICY_URL, {
    method: 'POST',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify({prompt: String(message.prompt || ''), provider: String(message.provider || 'chatgpt')}),
    signal: controller.signal,
  })
    .then(async response => {
      const data = await response.json();
      sendResponse({ok: true, ...data});
    })
    .catch(error => {
      sendResponse({
        ok: false,
        allowed: false,
        message: `Plano no está disponible; la política falla en modo cerrado. ${error.message}`,
      });
    })
    .finally(() => clearTimeout(timeout));

  return true;
});
