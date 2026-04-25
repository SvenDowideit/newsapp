from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<title>newsagg</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg: #fff;
    --fg: #000;
    --meta: #555;
    --border: #ccc;
    --highlight: #000;
  }

  body {
    background: var(--bg);
    color: var(--fg);
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 18px;
    line-height: 1.55;
    height: 100dvh;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  /* ── Top bar ── */
  #topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 16px;
    border-bottom: 2px solid var(--fg);
    flex-shrink: 0;
    font-size: 14px;
  }
  #topbar .title { font-weight: bold; font-size: 16px; }
  #topbar .meta  { color: var(--meta); }

  /* ── Main content area ── */
  #stage {
    flex: 1;
    overflow: hidden;
    position: relative;
    display: flex;
    flex-direction: column;
  }

  /* ── Feed view ── */
  #feed-view {
    flex: 1;
    overflow-y: auto;
    padding: 0;
  }
  .feed-item {
    padding: 16px;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    user-select: none;
  }
  .feed-item:hover { background: #f5f5f5; }
  .feed-item .headline { font-size: 20px; font-weight: bold; margin-bottom: 6px; }
  .feed-item .summary  { color: #222; margin-bottom: 6px; }
  .feed-item .item-meta { font-size: 13px; color: var(--meta); }
  .breaking-badge {
    display: inline-block;
    background: #000;
    color: #fff;
    font-size: 11px;
    font-weight: bold;
    padding: 1px 5px;
    margin-right: 6px;
    vertical-align: middle;
  }
  .update-badge {
    display: inline-block;
    background: #444;
    color: #fff;
    font-size: 11px;
    font-weight: bold;
    padding: 1px 5px;
    margin-right: 6px;
    vertical-align: middle;
  }
  /* Interest bar: thin coloured strip */
  .interest-bar-wrap {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    vertical-align: middle;
    margin-left: 6px;
  }
  .interest-bar-track {
    width: 48px;
    height: 6px;
    background: #ddd;
    border: 1px solid #aaa;
    display: inline-block;
  }
  .interest-bar-fill {
    height: 100%;
    background: #000;
  }
  .interest-val { font-size: 11px; color: var(--meta); }

  /* ── Item (reading) view ── */
  #item-view {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  #item-content {
    flex: 1;
    overflow: hidden;
    padding: 20px 24px 8px;
    font-size: 19px;
    line-height: 1.6;
  }
  #item-content .item-headline {
    font-size: 24px;
    font-weight: bold;
    margin-bottom: 16px;
    line-height: 1.3;
  }
  #item-content .key-points { margin-top: 12px; }
  #item-content .key-points li { margin-left: 20px; margin-bottom: 4px; }
  #item-content .expanded-section {
    margin-top: 16px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }
  #item-content .source-links {
    margin-top: 12px;
    font-size: 13px;
    word-break: break-all;
    position: relative;
    z-index: 20;
  }
  #item-content .source-links a { color: var(--meta); }
  #item-content .item-meta-line {
    font-size: 13px;
    color: var(--meta);
    margin-top: 12px;
  }

  /* ── Bottom bar ── */
  #bottombar {
    border-top: 2px solid var(--fg);
    padding: 6px 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-shrink: 0;
    font-size: 13px;
    color: var(--meta);
    gap: 8px;
  }
  #bottombar .hint { font-size: 12px; }

  /* ── Interest buttons ── */
  .interest-btns { display: flex; gap: 6px; align-items: center; }
  .ibtn {
    border: 2px solid var(--fg);
    background: var(--bg);
    color: var(--fg);
    font-size: 20px;
    line-height: 1;
    width: 36px; height: 36px;
    cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    font-weight: bold;
    user-select: none;
  }
  .ibtn:active { background: var(--fg); color: var(--bg); }
  .ibtn-label { font-size: 11px; color: var(--meta); }

  /* ── Help overlay ── */
  #help-overlay {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.55);
    z-index: 150;
    align-items: center;
    justify-content: center;
  }
  #help-overlay.open { display: flex; }
  #help-box {
    background: #fff;
    border: 2px solid #000;
    padding: 24px 28px;
    max-width: 420px;
    width: 90%;
    font-size: 14px;
    line-height: 1.7;
  }
  #help-box h2 { font-size: 16px; margin-bottom: 12px; border-bottom: 1px solid #ccc; padding-bottom: 6px; }
  #help-box table { width: 100%; border-collapse: collapse; }
  #help-box td { padding: 2px 6px; }
  #help-box td:first-child { font-family: monospace; white-space: nowrap; color: #000; font-weight: bold; }
  #help-box .section { margin-top: 10px; font-weight: bold; font-size: 13px; color: #555; }
  #help-close { margin-top: 16px; display: block; text-align: center; cursor: pointer; font-size: 13px; color: #555; }

  /* ── Tap zones (invisible, cover left/right thirds) ── */
  #zone-left, #zone-right {
    position: absolute;
    top: 0; bottom: 0;
    width: 30%;
    z-index: 10;
    cursor: pointer;
  }
  #zone-left  { left: 0; }
  #zone-right { right: 0; }

  /* ── Context menu overlay ── */
  #menu-overlay {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.4);
    z-index: 100;
    align-items: flex-end;
  }
  #menu-overlay.open { display: flex; }
  #menu-box {
    background: #fff;
    width: 100%;
    border-top: 2px solid #000;
  }
  .menu-item {
    padding: 18px 20px;
    border-bottom: 1px solid var(--border);
    font-size: 18px;
    cursor: pointer;
  }
  .menu-item:hover { background: #f0f0f0; }
  .menu-item.danger { color: #c00; }

  /* ── Toast ── */
  #toast {
    position: fixed;
    bottom: 60px;
    left: 50%;
    transform: translateX(-50%);
    background: #000;
    color: #fff;
    padding: 8px 18px;
    font-size: 14px;
    border-radius: 3px;
    opacity: 0;
    transition: opacity 0.2s;
    pointer-events: none;
    z-index: 200;
  }
  #toast.show { opacity: 1; }

  /* ── Loading / empty ── */
  #loading { padding: 40px; text-align: center; color: var(--meta); }
</style>
</head>
<body>

<div id="topbar">
  <span class="title">newsagg</span>
  <span id="topbar-meta" class="meta"></span>
</div>

<div id="stage">
  <!-- Feed list -->
  <div id="feed-view">
    <div id="loading">Loading feed…</div>
  </div>

  <!-- Single item reading view (hidden initially) -->
  <div id="item-view" style="display:none">
    <div id="zone-left"  onclick="zoneLeft()"></div>
    <div id="zone-right" onclick="zoneRight()"></div>
    <div id="item-content"></div>
  </div>
</div>

<div id="bottombar">
  <span id="bottombar-left"></span>
  <span id="bottombar-hint" class="hint"></span>
  <div id="interest-btns" class="interest-btns" style="display:none">
    <span class="ibtn-label">interest</span>
    <button class="ibtn" id="ibtn-down" onclick="menuAction('interest_down')" title="Less like this (-)">−</button>
    <button class="ibtn" id="ibtn-up"   onclick="menuAction('interest_up')"   title="More like this (+)">+</button>
  </div>
  <button class="ibtn" style="font-size:15px;font-weight:normal;" onclick="openHelp()" title="Keyboard shortcuts (?)">?</button>
</div>

<!-- Context menu -->
<div id="menu-overlay" onclick="closeMenuIfOutside(event)">
  <div id="menu-box">
    <div class="menu-item" onclick="menuAction('save')">Save / bookmark</div>
    <div class="menu-item" onclick="menuAction('send')">Send link</div>
    <div class="menu-item" onclick="menuAction('interest_up')">More like this</div>
    <div class="menu-item" onclick="menuAction('interest_down')">Less like this</div>
    <div class="menu-item danger" onclick="menuAction('discard')">Discard</div>
    <div class="menu-item" onclick="closeMenu()">Cancel</div>
  </div>
</div>

<!-- Help overlay -->
<div id="help-overlay" onclick="closeHelpIfOutside(event)">
  <div id="help-box">
    <h2>Keyboard &amp; gesture reference</h2>
    <table>
      <tr><td colspan="2" class="section">Feed list</td></tr>
      <tr><td>↑ / k</td><td>Scroll up</td></tr>
      <tr><td>↓ / j</td><td>Scroll down</td></tr>
      <tr><td>→ / Enter</td><td>Open item</td></tr>
      <tr><td>R</td><td>Refresh feed</td></tr>
      <tr><td colspan="2" class="section">Reading an item</td></tr>
      <tr><td>→ / l</td><td>Next item</td></tr>
      <tr><td>← / h</td><td>Previous item</td></tr>
      <tr><td>↑ / k</td><td>Scroll up</td></tr>
      <tr><td>↓ / j</td><td>Scroll down</td></tr>
      <tr><td>E</td><td>Expand (full summary)</td></tr>
      <tr><td>D</td><td>Discard</td></tr>
      <tr><td>S</td><td>Save / bookmark</td></tr>
      <tr><td>+ / =</td><td>More like this ↑</td></tr>
      <tr><td>−</td><td>Less like this ↓</td></tr>
      <tr><td>M</td><td>Context menu</td></tr>
      <tr><td>Esc</td><td>Back to feed</td></tr>
      <tr><td colspan="2" class="section">Touch gestures (item view)</td></tr>
      <tr><td>Swipe ↑</td><td>Next item</td></tr>
      <tr><td>Swipe ↓</td><td>Previous item</td></tr>
      <tr><td>Swipe ←</td><td>Discard</td></tr>
      <tr><td>Swipe →</td><td>Expand</td></tr>
      <tr><td>Tap left edge</td><td>Previous item</td></tr>
      <tr><td>Tap right edge</td><td>Next item</td></tr>
      <tr><td>Long press</td><td>Context menu</td></tr>
    </table>
    <span id="help-close" onclick="closeHelp()">Close  [Esc / ?]</span>
  </div>
</div>

<div id="toast"></div>

<script>
// ── State ──────────────────────────────────────────────────────────────────
const API = '';  // same origin
let feed = [];
let cursor = 0;       // current item index in feed
let expanded = null;  // expanded item data
let itemReadStart = null;

// ── Boot ──────────────────────────────────────────────────────────────────
async function boot() {
  await loadFeed();
  showFeed();
}

async function loadFeed() {
  try {
    const r = await fetch(`${API}/feed?page_size=50&active=true`);
    const data = await r.json();
    feed = data.items || [];
    renderFeed();
  } catch(e) {
    document.getElementById('loading').textContent = 'Failed to load feed: ' + e.message;
  }
}

// ── Feed view ─────────────────────────────────────────────────────────────
function interestBarHtml(score) {
  const pct = Math.round((score || 0.5) * 100);
  return `<span class="interest-bar-wrap" title="Interest score ${pct}%">` +
    `<span class="interest-bar-track"><span class="interest-bar-fill" style="width:${pct}%"></span></span>` +
    `<span class="interest-val">${pct}%</span></span>`;
}

function renderFeed() {
  const el = document.getElementById('feed-view');
  if (!feed.length) { el.innerHTML = '<div id="loading">No items yet.</div>'; return; }
  el.innerHTML = feed.map((item, i) => `
    <div class="feed-item" onclick="openItem(${i})">
      <div class="headline">
        ${item.is_breaking ? '<span class="breaking-badge">BREAKING</span>' : ''}
        ${item.is_update   ? '<span class="update-badge">UPDATE</span>'   : ''}
        ${esc(item.headline)}
      </div>
      <div class="summary">${esc(item.summary)}</div>
      <div class="item-meta">
        ${esc((item.topics||[]).join(' · '))} &nbsp;·&nbsp; ${item.item_count} source${item.item_count>1?'s':''}
        ${interestBarHtml(item.interest_score)}
      </div>
    </div>`).join('');
}

function showFeed() {
  document.getElementById('feed-view').style.display = '';
  document.getElementById('item-view').style.display = 'none';
  document.getElementById('interest-btns').style.display = 'none';
  document.getElementById('topbar-meta').textContent = `${feed.length} items`;
  document.getElementById('bottombar-left').textContent = '';
  document.getElementById('bottombar-hint').textContent =
    '← → navigate · Enter open · R refresh · ? help';
  document.title = 'newsagg';
}

// ── Item view ─────────────────────────────────────────────────────────────
function openItem(i) {
  cursor = i;
  expanded = null;
  itemReadStart = Date.now();
  renderItem();
  document.getElementById('feed-view').style.display = 'none';
  document.getElementById('item-view').style.display = 'flex';
}

function renderItem() {
  const item = feed[cursor];
  if (!item) return;

  const src = (item.source_ids||[]).join(', ') || 'unknown';
  const topics = (item.topics||[]).join(' · ');

  let expandedHtml = '';
  if (expanded) {
    // Show non-redundant excerpt if available
    const excerptText = expanded.excerpt
      ? `<p>${esc(expanded.excerpt)}</p>`
      : `<p style="color:var(--meta);font-style:italic">No additional context available.</p>`;
    expandedHtml = `<div class="expanded-section">${excerptText}</div>`;
  }

  // Source links: prefer expanded urls (more complete), fall back to item's own
  const sourceUrls = (expanded && (expanded.source_urls||[]).length)
    ? expanded.source_urls : (item.source_urls||[]);
  const linksHtml = sourceUrls.length
    ? `<p class="source-links">${sourceUrls.map(u =>
        `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(u)}</a>`
      ).join('<br>')}</p>`
    : '';

  // Use full_summary (from a previous expand) as the body if available
  const bodyText = item.full_summary || item.summary;

  // Only show key_points from expanded response if they differ; otherwise use item's
  const kpSource = (expanded && (expanded.key_points||[]).length) ? expanded.key_points : (item.key_points||[]);
  let kpHtml = '';
  if (kpSource.length) {
    kpHtml = `<div class="key-points"><ul>${
      kpSource.map(p => `<li>${esc(p)}</li>`).join('')
    }</ul></div>`;
  }

  document.getElementById('item-content').innerHTML = `
    <div class="item-headline">
      ${item.is_breaking ? '<span class="breaking-badge">BREAKING</span>' : ''}
      ${item.is_update   ? '<span class="update-badge">UPDATE</span>'   : ''}
      ${esc(item.headline)}
    </div>
    <p>${esc(bodyText)}</p>
    ${kpHtml}
    ${expandedHtml}
    ${linksHtml}
    <div class="item-meta-line">
      ${esc(topics)} &nbsp;·&nbsp; ${src} &nbsp;·&nbsp; ${item.item_count} source${item.item_count>1?'s':''}
      ${interestBarHtml(item.interest_score)}
    </div>
  `;

  document.getElementById('topbar-meta').textContent =
    `${cursor + 1} / ${feed.length}`;
  document.getElementById('bottombar-left').textContent =
    '← prev · E expand · D discard · S save';
  document.getElementById('bottombar-hint').textContent = '? help';
  document.getElementById('interest-btns').style.display = 'flex';
  document.title = item.headline;
}

// ── Tap zones (mirrors gesture map) ──────────────────────────────────────
function zoneLeft()  { prevItem(); }   // tap left  → prev item
function zoneRight() { nextItem(); }   // tap right → next item

// ── Navigation ────────────────────────────────────────────────────────────
function nextItem() {
  recordRead();
  if (cursor + 1 < feed.length) { cursor++; expanded = null; itemReadStart = Date.now(); renderItem(); }
  else { toast('End of feed'); }
}

function prevItem() {
  recordRead();
  if (cursor > 0) { cursor--; expanded = null; itemReadStart = Date.now(); renderItem(); }
  else { showFeed(); }
}

async function expandItem() {
  const item = feed[cursor];
  toast('Loading…');
  try {
    const r = await fetch(`${API}/items/${item.id}/expand`, {method:'POST'});
    expanded = await r.json();
    renderItem();
    toast('Expanded');
  } catch(e) { toast('Expand failed'); }
}

async function discardItem() {
  const item = feed[cursor];
  await post(`/items/${item.id}/discard`);
  feed.splice(cursor, 1);
  if (cursor >= feed.length) cursor = Math.max(0, feed.length - 1);
  if (!feed.length) { showFeed(); return; }
  expanded = null;
  itemReadStart = Date.now();
  renderItem();
  toast('Discarded');
}

// ── Help overlay ─────────────────────────────────────────────────────────
function openHelp() {
  document.getElementById('help-overlay').classList.add('open');
}
function closeHelp() {
  document.getElementById('help-overlay').classList.remove('open');
}
function closeHelpIfOutside(e) {
  if (e.target === document.getElementById('help-overlay')) closeHelp();
}

// ── Context menu ──────────────────────────────────────────────────────────
function openMenu() {
  document.getElementById('menu-overlay').classList.add('open');
}
function closeMenu() {
  document.getElementById('menu-overlay').classList.remove('open');
}
function closeMenuIfOutside(e) {
  if (e.target === document.getElementById('menu-overlay')) closeMenu();
}

async function menuAction(action) {
  closeMenu();
  const item = feed[cursor];
  switch(action) {
    case 'save':
      await post(`/items/${item.id}/save`);
      toast('Saved');
      break;
    case 'send':
      const url = item.canonical_url || window.location.href;
      if (navigator.share) { navigator.share({title: item.headline, url}); }
      else { await navigator.clipboard.writeText(url); toast('Link copied'); }
      break;
    case 'interest_up':
      await post(`/items/${item.id}/interest`, {direction:'up'});
      toast('More like this ✓');
      break;
    case 'interest_down':
      await post(`/items/${item.id}/interest`, {direction:'down'});
      toast('Less like this ✓');
      break;
    case 'discard':
      discardItem();
      break;
  }
}

// ── Record read event ─────────────────────────────────────────────────────
function recordRead() {
  const item = feed[cursor];
  if (!item || !itemReadStart) return;
  const dur = Math.round((Date.now() - itemReadStart) / 1000);
  if (dur < 2) return;
  post(`/items/${item.id}/read`, {duration_seconds: dur, fully_read: false});
  itemReadStart = null;
}

// ── Touch / swipe ─────────────────────────────────────────────────────────
let touchStart = null;
document.addEventListener('touchstart', e => {
  touchStart = {x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now()};
}, {passive: true});

document.addEventListener('touchend', e => {
  if (!touchStart) return;
  const dx = e.changedTouches[0].clientX - touchStart.x;
  const dy = e.changedTouches[0].clientY - touchStart.y;
  const dur = Date.now() - touchStart.t;
  touchStart = null;
  if (document.getElementById('item-view').style.display === 'none') return;

  const adx = Math.abs(dx), ady = Math.abs(dy);
  if (adx < 15 && ady < 15 && dur > 600) { openMenu(); return; }  // long press
  if (adx > 60 && adx > ady) {
    if (dx < 0) discardItem();   // swipe left → discard
    else expandItem();            // swipe right → expand
  } else if (ady > 60 && ady > adx) {
    if (dy < 0) nextItem();      // swipe up → next
    else prevItem();              // swipe down → prev
  }
}, {passive: true});

// ── Keyboard ─────────────────────────────────────────────────────────────
document.addEventListener('keydown', e => {
  const inFeed = document.getElementById('feed-view').style.display !== 'none';
  const inItem = document.getElementById('item-view').style.display !== 'none';

  if (e.key === 'Escape') {
    if (document.getElementById('help-overlay').classList.contains('open')) { closeHelp(); return; }
    if (document.getElementById('menu-overlay').classList.contains('open')) { closeMenu(); return; }
    if (inItem) { recordRead(); showFeed(); return; }
  }

  if (e.key === '?' || e.key === '/') { openHelp(); return; }

  if (inFeed) {
    if (e.key === 'ArrowDown' || e.key === 'j') {
      const el = document.getElementById('feed-view');
      el.scrollTop += 80;
    } else if (e.key === 'ArrowUp' || e.key === 'k') {
      const el = document.getElementById('feed-view');
      el.scrollTop -= 80;
    } else if (e.key === 'Enter' || e.key === 'ArrowRight') {
      openItem(cursor);
    } else if (e.key === 'r' || e.key === 'R') {
      loadFeed();
    }
    return;
  }

  if (inItem) {
    switch(e.key) {
      case 'ArrowRight': case 'l': nextItem(); break;
      case 'ArrowLeft':  case 'h': prevItem(); break;
      case 'ArrowDown':  case 'j':
        document.getElementById('item-content').scrollTop += 80; break;
      case 'ArrowUp':    case 'k':
        document.getElementById('item-content').scrollTop -= 80; break;
      case 'e': case 'E': expandItem(); break;
      case 'd': case 'D': discardItem(); break;
      case 'm': case 'M': openMenu(); break;
      case 's': case 'S': menuAction('save'); break;
      case '+': case '=': menuAction('interest_up'); break;
      case '-': case '_': menuAction('interest_down'); break;
    }
  }
});

// ── Helpers ───────────────────────────────────────────────────────────────
function esc(s) {
  return String(s||'')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function post(path, body) {
  return fetch(API + path, {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: body ? JSON.stringify(body) : '',
  });
}

let toastTimer = null;
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2000);
}

// ── SSE live updates ──────────────────────────────────────────────────────
function connectSSE() {
  const es = new EventSource('/feed/live');
  es.onmessage = e => {
    if (e.data === 'ping') return;
    try {
      const ev = JSON.parse(e.data);
      if (ev.type === 'breaking') toast('Breaking: ' + (ev.topic || 'new story'));
    } catch(_) {}
  };
  es.onerror = () => setTimeout(connectSSE, 5000);
}

boot();
connectSSE();
</script>
</body>
</html>
"""


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def webui():
    return HTMLResponse(_HTML)
