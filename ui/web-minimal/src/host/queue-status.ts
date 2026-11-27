// 排队态可见：把 /api/sessions/{id}/status 的 queue_depth / waiting_since
// 变成用户看得见的一行字。
//
// 之前的问题：Agent 忙时前端只知道「在思考」，多条消息压在同一会话里时
// 用户看到的是「没反应」，误以为卡死。这里不改轮询协议，只消费已有字段：
//   queue_depth > 0  → 还有几条没被消费
//   waiting_since    → 这一轮已经跑了多久
//
// 轮询节奏按状态自适应（忙 1 s / 闲 2.5 s），页面不可见时直接不发请求：
// 后台标签页不该为了一行状态字每 2 秒叫醒一次。
import { HOST, groupState } from './state.js';

const POLL_BUSY_MS = 1000;
const POLL_IDLE_MS = 2500;
const STYLE_ID = 'wm-status-style';
const BADGE_ID = 'wm-queue-badge';

let timer: number | null = null;
let inFlight = false;
let inited = false;
let lastKey = '';
let lastCaps = '';

/** 状态胶囊与轻提示共用一份内联样式：Canvas / CanvasText 是系统色，明暗主题都成立。 */
function ensureStyle(): void {
  if (HOST.document.getElementById(STYLE_ID)) return;
  const st = HOST.document.createElement('style');
  st.id = STYLE_ID;
  st.textContent = [
    '.wm-queue-badge{position:fixed;left:50%;bottom:10px;transform:translateX(-50%);z-index:60;',
    'display:none;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;',
    'font:12px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;background:Canvas;color:CanvasText;',
    'border:1px solid color-mix(in srgb,CanvasText 18%,Canvas);box-shadow:0 2px 10px rgba(0,0,0,.12);',
    'pointer-events:none;white-space:nowrap}',
    '.wm-queue-badge[data-on="1"]{display:inline-flex}',
    '.wm-queue-dot{width:6px;height:6px;border-radius:50%;background:#f59e0b}',
    '.wm-toast{position:fixed;left:50%;bottom:48px;transform:translateX(-50%);z-index:61;',
    'max-width:min(560px,86vw);padding:8px 14px;border-radius:10px;',
    'font:13px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;background:Canvas;color:CanvasText;',
    'border:1px solid color-mix(in srgb,CanvasText 18%,Canvas);box-shadow:0 6px 24px rgba(0,0,0,.16);',
    'pointer-events:none}',
  ].join('');
  HOST.document.head.appendChild(st);
}

/** 轻提示：不抢焦点、不阻塞输入，到点自己消失。 */
export function toast(message: string, ms = 3200): void {
  try {
    ensureStyle();
    const el = HOST.document.createElement('div');
    el.className = 'wm-toast';
    el.textContent = message;
    HOST.document.body.appendChild(el);
    HOST.setTimeout(function () {
      try { el.remove(); } catch (_) {}
    }, ms);
  } catch (_) { /* 提示失败不影响主流程 */ }
}

function badge(): HTMLElement | null {
  const doc = HOST.document;
  let el = doc.getElementById(BADGE_ID);
  if (el) return el;
  el = doc.createElement('div');
  el.id = BADGE_ID;
  el.className = 'wm-queue-badge';
  const dot = doc.createElement('span');
  dot.className = 'wm-queue-dot';
  const text = doc.createElement('span');
  text.id = BADGE_ID + '-text';
  el.appendChild(dot);
  el.appendChild(text);
  doc.body.appendChild(el);
  return el;
}

function render(status: Record<string, unknown> | null): void {
  const el = badge();
  if (!el) return;
  const busy = !!(status && status.is_thinking);
  if (!busy) {
    if (lastKey !== '') { el.setAttribute('data-on', '0'); lastKey = ''; }
    return;
  }
  // 能力域与会话绑定、与忙闲无关：挂到 data-caps 上（会话级工具集对调试与后续 UI 可见）
  const capsRaw = status && status.capabilities;
  const caps = Array.isArray(capsRaw) ? capsRaw.slice(0, 8).join(',') : '';
  if (caps && caps !== lastCaps) { lastCaps = caps; el.setAttribute('data-caps', caps); }
  const queued = Number(status && status.queue_depth ? status.queue_depth : 0);
  const sinceRaw = status && status.waiting_since;
  const since = typeof sinceRaw === 'number' ? Math.max(0, Math.round(Date.now() / 1000 - sinceRaw)) : null;
  let text = '处理中';
  if (since !== null && since >= 1) text += ' ' + since + 's';
  if (queued > 0) text = '排队 ' + queued + ' 条 · ' + text;
  const key = text;
  if (key === lastKey) return;
  lastKey = key;
  const label = HOST.document.getElementById(BADGE_ID + '-text');
  if (label) label.textContent = text;
  el.setAttribute('data-on', '1');
}

function schedule(ms: number): void {
  timer = HOST.setTimeout(function () { void tick(); }, ms);
}

async function tick(): Promise<void> {
  timer = null;
  if (inFlight) { schedule(POLL_IDLE_MS); return; }
  // 页面不可见：不发请求，也不清掉已有显示（回来时 visibilitychange 会立刻补一次）
  if (HOST.document.hidden) { schedule(POLL_IDLE_MS); return; }
  const sid = groupState.activeSessionId;
  if (!sid) { render(null); schedule(POLL_IDLE_MS); return; }

  inFlight = true;
  let busy = false;
  try {
    const r = await HOST.fetch('/api/sessions/' + encodeURIComponent(sid) + '/status');
    if (!r.ok) {
      render(null);
    } else {
      const data = (await r.json()) as Record<string, unknown>;
      render(data);
      busy = !!(data && data.is_thinking);
    }
  } catch (_) {
    render(null);
  } finally {
    inFlight = false;
    schedule(busy ? POLL_BUSY_MS : POLL_IDLE_MS);
  }
}

/** 启动轮询：boot 末尾调一次即可，重复调用不会叠加定时器或监听。 */
export function initQueueStatus(): void {
  ensureStyle();
  if (inited) return;
  inited = true;
  HOST.document.addEventListener('visibilitychange', function () {
    if (HOST.document.hidden) return;
    if (timer !== null) { HOST.clearTimeout(timer); timer = null; }
    void tick();
  });
  void tick();
}
