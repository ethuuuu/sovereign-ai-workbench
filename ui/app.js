// Sovereign AI Workbench - single page, no build step.
// An npm install that cannot reach a registry is a failure mode we do not
// want to own on an air-gapped machine an hour before a demo.

const $ = (id) => document.getElementById(id);
let sessionId = null;
let attachments = [];

async function boot() {
  const session = await fetch('/api/session', { method: 'POST' }).then((r) => r.json());
  sessionId = session.session_id;
  await refreshModels();
  await refreshEgress();
  setInterval(refreshEgress, 4000);
}

async function refreshModels() {
  try {
    const data = await fetch('/api/models').then((r) => r.json());
    $('endpoint').textContent = data.endpoint;
    const loaded = data.models.filter((m) => m.available);
    $('models').textContent = loaded.length
      ? loaded.map((m) => m.id).join(', ')
      : (data.reachable ? 'none loaded' : 'endpoint unreachable');
  } catch {
    $('endpoint').textContent = 'unreachable';
  }
}

async function refreshEgress() {
  try {
    const data = await fetch('/api/egress').then((r) => r.json());
    $('egress').textContent = data.external_calls;
    $('egress-stat').classList.toggle('breached', data.external_calls > 0);
  } catch { /* the panel is informational; never break the page over it */ }
}

function bubble(cls, html) {
  const node = document.createElement('div');
  node.className = `msg ${cls}`;
  node.innerHTML = html;
  $('log').appendChild(node);
  $('log').scrollTop = $('log').scrollHeight;
  return node;
}

function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
}

function traceEvent(cls, label, bodyHtml) {
  const empty = $('trace').querySelector('.empty');
  if (empty) empty.remove();
  const node = document.createElement('div');
  node.className = `ev ${cls}`;
  const time = new Date().toLocaleTimeString();
  node.innerHTML = `<div class="h"><span>${escapeHtml(label)}</span><span>${time}</span></div>
                    <div class="b">${bodyHtml}</div>`;
  $('trace').appendChild(node);
  $('trace').scrollTop = $('trace').scrollHeight;
}

function render(event) {
  switch (event.kind) {
    case 'classify':
      traceEvent('', 'classify',
        `<strong>${escapeHtml(event.task_type)}</strong><br>${escapeHtml(event.reason)}`);
      break;
    case 'route':
      traceEvent('route', 'route',
        `<strong>${escapeHtml(event.model)}</strong><br>${escapeHtml(event.reason)}`);
      break;
    case 'plan': {
      const items = (event.steps || [])
        .map((s) => `<li>${escapeHtml(s.action)} <em>(${escapeHtml(s.tool)})</em></li>`)
        .join('');
      traceEvent('plan', 'plan', `<ol>${items}</ol>`);
      break;
    }
    case 'tool':
      traceEvent('tool', `step ${event.step} · ${event.tool}`,
        `<details><summary>arguments and result</summary>
         <pre>${escapeHtml(JSON.stringify(event.args, null, 2))}</pre>
         <pre>${escapeHtml(event.preview)}</pre></details>`);
      break;
    case 'compress':
      traceEvent('', 'context compressed', `history reduced to ${event.messages} messages`);
      break;
    case 'verify':
      traceEvent(`verify${event.passed ? '' : ' failed'}`, 'verify',
        `${event.passed ? 'PASSED' : 'FAILED'} — ${escapeHtml(event.detail)}`);
      break;
    case 'budget_exhausted':
      traceEvent('verify failed', 'budget', `stopped after ${event.steps} steps`);
      break;
    case 'answer':
      answerBubble(event);
      break;
    case 'error':
      bubble('error', `<pre>${escapeHtml(event.message)}</pre>`);
      break;
    default:
      break;
  }
}

function answerBubble(event) {
  const verified = event.verified
    ? '<span class="badge ok">verified</span>'
    : '<span class="badge no">unverified</span>';
  const files = (event.files || [])
    .map((f) => `<a href="/api/download/${sessionId}/${encodeURIComponent(f)}" download>${escapeHtml(f)}</a>`)
    .join('');
  bubble('assistant', `
    <pre>${escapeHtml(event.text)}</pre>
    ${files ? `<div class="files">${files}</div>` : ''}
    <div class="meta">
      <span class="badge">${escapeHtml(event.model)}</span>
      <span class="badge">${escapeHtml(event.task_type)}</span>
      <span>${event.steps} steps</span>
      ${verified}
      <span>${escapeHtml(event.verification)}</span>
    </div>`);
}

async function send(text) {
  bubble('user', `<pre>${escapeHtml(text)}</pre>`);
  $('send').disabled = true;

  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text, session_id: sessionId, attachments }),
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop();
    for (const part of parts) {
      if (!part.startsWith('data: ')) continue;
      let event;
      try { event = JSON.parse(part.slice(6)); } catch { continue; }
      if (event.kind === 'session') { sessionId = event.session_id; continue; }
      render(event);
    }
  }

  attachments = [];
  $('attached').textContent = '';
  $('send').disabled = false;
  refreshEgress();
}

$('composer').addEventListener('submit', (e) => {
  e.preventDefault();
  const text = $('input').value.trim();
  if (!text) return;
  $('input').value = '';
  $('input').style.height = 'auto';
  send(text);
});

$('input').addEventListener('input', (e) => {
  e.target.style.height = 'auto';
  e.target.style.height = `${Math.min(e.target.scrollHeight, 180)}px`;
});

$('input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    $('composer').requestSubmit();
  }
});

$('file').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  const result = await fetch(`/api/upload?session_id=${sessionId}`, {
    method: 'POST', body: form,
  }).then((r) => r.json());
  attachments.push(result.path);
  $('attached').textContent = `attached: ${attachments.map((p) => p.split('/').pop()).join(', ')}`;
  e.target.value = '';
});

boot();
