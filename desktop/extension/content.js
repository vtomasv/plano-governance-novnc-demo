(() => {
  'use strict';

  const AUTH_WINDOW_MS = 7000;
  const SEND_CONFIRM_MS = 2500;
  const RESPONSE_TIMEOUT_MS = 180000;
  let authorization = null;
  let checking = false;

  function provider() {
    const host = location.hostname.toLowerCase();
    if (host.includes('gemini') || host.includes('bard')) return 'gemini';
    if (host.includes('claude')) return 'claude';
    if (host.includes('grok') || host === 'x.com' || host.endsWith('.x.com')) return 'grok';
    return 'chatgpt';
  }

  function conversationId() {
    const key = `plano-conversation-${provider()}`;
    let value = sessionStorage.getItem(key);
    if (!value) {
      value = `${provider()}-${Date.now()}-${crypto.getRandomValues(new Uint32Array(1))[0].toString(16)}`;
      sessionStorage.setItem(key, value);
    }
    return value;
  }

  function composerText(node) {
    if (!node) return '';
    return String(node.value ?? node.innerText ?? node.textContent ?? '').trim();
  }

  function asComposer(node) {
    if (!(node instanceof Element)) return null;
    if (node.matches('textarea,[contenteditable="true"]')) return node;
    return node.closest('textarea,[contenteditable="true"]');
  }

  function composers() {
    const candidates = [
      document.activeElement,
      document.querySelector('textarea:focus'),
      document.querySelector('[contenteditable="true"]:focus'),
      ...Array.from(document.querySelectorAll('textarea,[contenteditable="true"]')).reverse(),
    ].map(asComposer).filter(Boolean);
    return candidates.filter((node, index, all) => all.indexOf(node) === index);
  }

  function findComposer() {
    return composers().find(node => composerText(node)) || composers()[0] || null;
  }

  function promptFromPage() {
    for (const node of composers()) {
      const text = composerText(node);
      if (text) return text;
    }
    return '';
  }

  function isComposer(node) {
    return Boolean(asComposer(node));
  }

  function isSendButton(node) {
    if (!(node instanceof Element)) return false;
    const button = node.closest('button,[role="button"]');
    if (!button || button.disabled || button.getAttribute('aria-disabled') === 'true') return false;
    const label = `${button.getAttribute('aria-label') || ''} ${button.getAttribute('data-testid') || ''} ${button.textContent || ''}`.toLowerCase();
    if (/send|enviar|submit|envoyer|senden|envoyer le message/.test(label)) return true;
    if (button.getAttribute('type') !== 'submit') return false;
    return Boolean(button.closest('form')?.querySelector('textarea,[contenteditable="true"]'));
  }

  function findSendButton(composer = findComposer()) {
    const form = composer?.closest('form');
    if (form) {
      const local = Array.from(form.querySelectorAll('button,[role="button"]')).find(isSendButton);
      if (local) return local;
    }
    return Array.from(document.querySelectorAll('button,[role="button"]')).find(isSendButton) || null;
  }

  function showBanner(message, allowed, persistent = false) {
    let banner = document.getElementById('plano-governance-banner');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'plano-governance-banner';
      Object.assign(banner.style, {
        position: 'fixed', zIndex: '2147483647', right: '18px', top: '18px', maxWidth: '460px',
        padding: '14px 16px', borderRadius: '12px', color: '#fff', fontFamily: 'system-ui,sans-serif',
        fontSize: '14px', lineHeight: '1.4', boxShadow: '0 18px 50px rgba(0,0,0,.35)',
        border: '1px solid rgba(255,255,255,.24)', whiteSpace: 'pre-wrap',
      });
      document.documentElement.appendChild(banner);
    }
    banner.style.background = allowed ? '#12653f' : '#7d2030';
    banner.textContent = message;
    clearTimeout(banner.__timer);
    if (!persistent) banner.__timer = setTimeout(() => banner.remove(), allowed ? 3500 : 10000);
  }

  function isAuthorized(prompt) {
    return Boolean(authorization && Date.now() < authorization.expiresAt && (!prompt || authorization.prompt === prompt));
  }

  async function sendAgent(type, payload) {
    try {
      return await chrome.runtime.sendMessage({type, ...payload});
    } catch (error) {
      return {ok: false, allowed: false, message: error.message, errorType: error.name || 'RuntimeError'};
    }
  }

  async function check(prompt) {
    if (checking) return {allowed: false, message: 'Plano ya está evaluando esta solicitud.'};
    checking = true;
    showBanner('Plano está inspeccionando el prompt…', true, true);
    try {
      return await sendAgent('PLANO_POLICY_CHECK', {
        prompt,
        provider: provider(),
        conversation_id: conversationId(),
        target_host: location.hostname,
        target_path: location.pathname,
      });
    } finally {
      checking = false;
    }
  }

  function userMessageExists(prompt) {
    const needle = prompt.trim().slice(0, 180);
    if (!needle) return false;
    const selectors = '[data-message-author-role="user"],[data-author="user"],[data-testid*="user-message"],.user-query';
    return Array.from(document.querySelectorAll(selectors)).some(node => (node.innerText || node.textContent || '').includes(needle));
  }

  function sendConfirmed(prompt, composer) {
    const current = composerText(composer);
    return !current || current !== prompt || userMessageExists(prompt);
  }

  function dispatchEnter(composer) {
    if (!composer) return;
    for (const type of ['keydown', 'keypress', 'keyup']) {
      composer.dispatchEvent(new KeyboardEvent(type, {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true}));
    }
  }

  function replay(trigger, composer) {
    const button = trigger?.button?.isConnected ? trigger.button : findSendButton(composer);
    const form = composer?.closest('form') || button?.closest('form');
    if (trigger?.kind === 'submit' && form?.requestSubmit) {
      form.requestSubmit(button?.getAttribute('type') === 'submit' ? button : undefined);
      return;
    }
    if (button) {
      button.click();
      return;
    }
    if (form?.requestSubmit) {
      form.requestSubmit();
      return;
    }
    dispatchEnter(composer);
  }

  function responseNodes() {
    const selectors = [
      '[data-message-author-role="assistant"]',
      '[data-author="assistant"]',
      '[data-testid*="assistant-message"]',
      '[data-testid*="bot-message"]',
      '.model-response-text',
      'message-content',
      '.response-container-content',
      '.font-claude-response',
    ];
    return Array.from(document.querySelectorAll(selectors.join(','))).filter(node => {
      const style = getComputedStyle(node);
      return style.display !== 'none' && style.visibility !== 'hidden';
    });
  }

  function latestResponse() {
    const values = responseNodes().map(node => String(node.innerText || node.textContent || '').trim()).filter(Boolean);
    return values.at(-1) || '';
  }

  function observeResponse(auditId, baseline, startedAt) {
    let last = '';
    let stableTicks = 0;
    let completed = false;
    const finish = async text => {
      if (completed) return;
      completed = true;
      observer.disconnect();
      clearInterval(poll);
      clearTimeout(timeout);
      await sendAgent('PLANO_WEB_RESULT', {
        audit_id: auditId,
        provider: provider(),
        response_text: text.slice(0, 50000),
        duration_ms: Date.now() - startedAt,
        finish_reason: 'dom-stable',
      });
      showBanner('Respuesta recibida y auditada por Plano.', true);
    };
    const inspect = () => {
      const text = latestResponse();
      if (!text || text === baseline) return;
      if (text === last) stableTicks += 1;
      else { last = text; stableTicks = 0; }
      if (stableTicks >= 3 && Date.now() - startedAt > 1800) finish(text);
    };
    const observer = new MutationObserver(inspect);
    observer.observe(document.documentElement, {subtree: true, childList: true, characterData: true});
    const poll = setInterval(inspect, 750);
    const timeout = setTimeout(async () => {
      if (completed) return;
      completed = true;
      observer.disconnect(); clearInterval(poll);
      await sendAgent('PLANO_WEB_ERROR', {
        audit_id: auditId,
        error_type: 'provider_response_timeout',
        error_message: 'El proveedor web no produjo una respuesta visible dentro del tiempo esperado.',
        duration_ms: Date.now() - startedAt,
      });
      showBanner('El proveedor no produjo una respuesta visible. El evento quedó registrado para diagnóstico.', false);
    }, RESPONSE_TIMEOUT_MS);
  }

  async function authorizeAndSend(trigger) {
    const composer = findComposer();
    const prompt = composerText(composer) || promptFromPage();
    if (!prompt) {
      showBanner('No se encontró texto para evaluar; envío detenido en modo cerrado.', false);
      return;
    }
    const baseline = latestResponse();
    const decision = await check(prompt);
    if (!decision?.allowed) {
      showBanner(decision?.message || 'Solicitud bloqueada por Plano.', false);
      return;
    }

    const startedAt = Date.now();
    authorization = {prompt, auditId: decision.audit_id, expiresAt: Date.now() + AUTH_WINDOW_MS};
    showBanner('Solicitud permitida por Plano. Enviando al proveedor…', true, true);
    replay(trigger, composer);

    await new Promise(resolve => setTimeout(resolve, SEND_CONFIRM_MS));
    if (!sendConfirmed(prompt, composer)) {
      replay({kind: trigger?.kind === 'click' ? 'submit' : 'click', button: findSendButton(composer)}, composer);
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    if (!sendConfirmed(prompt, composer)) {
      authorization = null;
      await sendAgent('PLANO_WEB_ERROR', {
        audit_id: decision.audit_id,
        error_type: 'provider_send_not_confirmed',
        error_message: 'La aplicación web no confirmó el envío después de la autorización.',
        duration_ms: Date.now() - startedAt,
      });
      showBanner('Plano permitió el prompt, pero el sitio no confirmó el envío. El texto permanece en el compositor para reintentar.', false);
      return;
    }

    showBanner('Prompt autorizado y entregado al proveedor. Esperando respuesta…', true);
    observeResponse(decision.audit_id, baseline, startedAt);
    setTimeout(() => {
      if (authorization?.auditId === decision.audit_id) authorization = null;
    }, AUTH_WINDOW_MS);
  }

  document.addEventListener('click', event => {
    if (!isSendButton(event.target)) return;
    const prompt = promptFromPage();
    if (isAuthorized(prompt)) return;
    event.preventDefault(); event.stopPropagation(); event.stopImmediatePropagation();
    authorizeAndSend({kind: 'click', button: event.target.closest('button,[role="button"]')});
  }, true);

  document.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing || !isComposer(event.target)) return;
    const prompt = promptFromPage();
    if (isAuthorized(prompt)) return;
    event.preventDefault(); event.stopPropagation(); event.stopImmediatePropagation();
    authorizeAndSend({kind: 'keydown'});
  }, true);

  document.addEventListener('submit', event => {
    const prompt = promptFromPage();
    if (isAuthorized(prompt)) return;
    event.preventDefault(); event.stopPropagation(); event.stopImmediatePropagation();
    authorizeAndSend({kind: 'submit', button: event.submitter});
  }, true);
})();
