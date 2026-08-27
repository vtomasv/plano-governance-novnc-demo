(() => {
  'use strict';

  let bypassOnce = false;
  let checking = false;

  function provider() {
    if (location.hostname.includes('claude')) return 'claude';
    if (location.hostname.includes('grok')) return 'grok';
    return 'chatgpt';
  }

  function promptFromPage() {
    const active = document.activeElement;
    const candidates = [
      active,
      document.querySelector('textarea:focus'),
      document.querySelector('[contenteditable="true"]:focus'),
      ...Array.from(document.querySelectorAll('textarea,[contenteditable="true"]')).reverse(),
    ].filter(Boolean);
    for (const node of candidates) {
      const text = node.value ?? node.innerText ?? node.textContent ?? '';
      if (String(text).trim()) return String(text).trim();
    }
    return '';
  }

  function isComposer(node) {
    if (!(node instanceof Element)) return false;
    return node.matches('textarea,[contenteditable="true"]') || Boolean(node.closest('textarea,[contenteditable="true"]'));
  }

  function isSendButton(node) {
    if (!(node instanceof Element)) return false;
    const button = node.closest('button,[role="button"]');
    if (!button) return false;
    const label = `${button.getAttribute('aria-label') || ''} ${button.getAttribute('data-testid') || ''} ${button.textContent || ''}`.toLowerCase();
    return button.type === 'submit' || /send|enviar|submit|envoyer|senden/.test(label);
  }

  function findSendButton() {
    const buttons = Array.from(document.querySelectorAll('button,[role="button"]'));
    return buttons.find(isSendButton) || document.querySelector('form button[type="submit"]');
  }

  function showBanner(message, allowed) {
    let banner = document.getElementById('plano-governance-banner');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'plano-governance-banner';
      Object.assign(banner.style, {
        position:'fixed', zIndex:'2147483647', right:'18px', top:'18px', maxWidth:'440px',
        padding:'14px 16px', borderRadius:'12px', color:'#fff', fontFamily:'system-ui,sans-serif',
        fontSize:'14px', lineHeight:'1.4', boxShadow:'0 18px 50px rgba(0,0,0,.35)',
        border:'1px solid rgba(255,255,255,.24)'
      });
      document.documentElement.appendChild(banner);
    }
    banner.style.background = allowed ? '#12653f' : '#7d2030';
    banner.textContent = message;
    clearTimeout(banner.__timer);
    banner.__timer = setTimeout(() => banner.remove(), allowed ? 2500 : 8000);
  }

  async function check(prompt) {
    if (checking) return {allowed:false, message:'Plano ya está evaluando una solicitud.'};
    checking = true;
    showBanner('Plano está inspeccionando el prompt…', true);
    try {
      return await chrome.runtime.sendMessage({type:'PLANO_POLICY_CHECK', prompt, provider:provider()});
    } finally {
      checking = false;
    }
  }

  async function authorizeAndSend(trigger) {
    const prompt = promptFromPage();
    if (!prompt) {
      showBanner('No se encontró texto para evaluar; envío detenido en modo cerrado.', false);
      return;
    }
    const decision = await check(prompt);
    if (!decision?.allowed) {
      showBanner(decision?.message || 'Solicitud bloqueada por Plano.', false);
      return;
    }
    showBanner('Solicitud permitida por Plano.', true);
    bypassOnce = true;
    const button = trigger?.button || findSendButton();
    if (button) {
      button.click();
      return;
    }
    const target = document.activeElement;
    if (target) {
      target.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', bubbles:true, cancelable:true}));
    }
  }

  document.addEventListener('click', event => {
    if (!isSendButton(event.target)) return;
    if (bypassOnce) { bypassOnce = false; return; }
    event.preventDefault(); event.stopPropagation(); event.stopImmediatePropagation();
    authorizeAndSend({button:event.target.closest('button,[role="button"]')});
  }, true);

  document.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing || !isComposer(event.target)) return;
    if (bypassOnce) { bypassOnce = false; return; }
    event.preventDefault(); event.stopPropagation(); event.stopImmediatePropagation();
    authorizeAndSend({});
  }, true);

  document.addEventListener('submit', event => {
    if (bypassOnce) { bypassOnce = false; return; }
    event.preventDefault(); event.stopPropagation(); event.stopImmediatePropagation();
    authorizeAndSend({button:event.submitter});
  }, true);
})();
