from __future__ import annotations

import struct
import zlib

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

router = APIRouter()


# ---------------------------------------------------------------------------
# Icon generation — solid black PNG, no external dependencies
# ---------------------------------------------------------------------------

def _solid_png(size: int) -> bytes:
    """Generate a minimal solid-black PNG of the given size using only stdlib."""
    # Each row: filter byte (0 = None) + RGB pixels
    row = b'\x00' + b'\x00\x00\x00' * size
    raw = row * size

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', crc)

    ihdr = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)
    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', ihdr)
        + chunk(b'IDAT', zlib.compress(raw))
        + chunk(b'IEND', b'')
    )


_PNG_192 = _solid_png(192)
_PNG_512 = _solid_png(512)


# ---------------------------------------------------------------------------
# SVG icon (used in manifest; also fine for <link rel="icon">)
# ---------------------------------------------------------------------------

_SVG_ICON = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192">
  <rect width="192" height="192" fill="#000"/>
  <text x="96" y="148" font-family="Georgia,serif" font-size="130"
        fill="#fff" text-anchor="middle">n</text>
</svg>"""


# ---------------------------------------------------------------------------
# Web App Manifest
# ---------------------------------------------------------------------------

_MANIFEST = """\
{
  "name": "newsagg",
  "short_name": "newsagg",
  "description": "Personal news aggregator",
  "start_url": "/",
  "display": "standalone",
  "orientation": "portrait-primary",
  "background_color": "#ffffff",
  "theme_color": "#000000",
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any" },
    { "src": "/icon.svg",     "sizes": "any",      "type": "image/svg+xml", "purpose": "any maskable" }
  ]
}"""


# ---------------------------------------------------------------------------
# Service worker — cache-first for app shell, network-first for API
# ---------------------------------------------------------------------------

_SW_JS = """\
const CACHE = 'newsagg-v1';
const SHELL = ['/', '/interests', '/stats'];
const ITEM_RE = /^\/item\/\d+$/;

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // API calls: network-first, no caching
  if (url.pathname.startsWith('/feed') || url.pathname.startsWith('/items') ||
      url.pathname.startsWith('/sources') || url.pathname.startsWith('/topics')) {
    e.respondWith(fetch(e.request).catch(() => new Response('', {status: 503})));
    return;
  }
  // Item permalink: serve app shell from cache
  if (ITEM_RE.test(url.pathname)) {
    e.respondWith(
      caches.match('/').then(cached => cached || fetch('/'))
    );
    return;
  }
  // App shell: cache-first, update in background
  e.respondWith(
    caches.match(e.request).then(cached => {
      const fresh = fetch(e.request).then(r => {
        if (r.ok) caches.open(CACHE).then(c => c.put(e.request, r.clone()));
        return r;
      });
      return cached || fresh;
    })
  );
});
"""


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, user-scalable=no">
<title>newsagg</title>

<!-- PWA: Android / Chrome -->
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#000000">
<meta name="mobile-web-app-capable" content="yes">

<!-- PWA: iOS / Safari -->
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="newsagg">
<link rel="apple-touch-icon" href="/icon-192.png">

<!-- Favicon -->
<link rel="icon" type="image/svg+xml" href="/icon.svg">

<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg: #fff;
    --fg: #000;
    --meta: #555;
    --border: #ccc;
    --highlight: #000;
    /* safe-area insets for notched phones */
    --sat: env(safe-area-inset-top, 0px);
    --sab: env(safe-area-inset-bottom, 0px);
    --sal: env(safe-area-inset-left, 0px);
    --sar: env(safe-area-inset-right, 0px);
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
    /* push content below the status bar on iOS standalone */
    padding-top: var(--sat);
    padding-left: var(--sal);
    padding-right: var(--sar);
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
  .age-badge {
    display: inline-block;
    float: right;
    background: #e8e8e8;
    color: #555;
    font-size: 11px;
    font-weight: normal;
    padding: 1px 6px;
    margin-left: 8px;
    vertical-align: middle;
  }
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
  #item-content .src-row { display: inline-flex; align-items: center; gap: 4px; }
  #item-content .src-ibtn {
    border: 1px solid var(--border); background: none; cursor: pointer;
    border-radius: 3px; width: 20px; height: 20px; font-size: 13px;
    line-height: 1; color: var(--meta); padding: 0;
  }
  #item-content .src-ibtn:hover { background: #f0f0f0; }
  #item-content .item-meta-line {
    font-size: 13px;
    color: var(--meta);
    margin-top: 12px;
  }

  /* ── Bottom bar ── */
  #bottombar {
    border-top: 2px solid var(--fg);
    padding: 6px 16px;
    /* lift above home indicator on iOS */
    padding-bottom: calc(6px + var(--sab));
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
    padding-bottom: var(--sab);
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
    bottom: calc(60px + var(--sab));
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
    <div class="menu-item" onclick="location.href='/interests'">Manage interests…</div>
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
let feedTotal = 0;
let cursor = 0;       // current item index in feed
let expanded = null;  // expanded item data
let itemReadStart = null;

// ── Service worker registration ───────────────────────────────────────────
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

// ── Boot ──────────────────────────────────────────────────────────────────
async function boot() {
  await Promise.all([loadFeed(), loadWeights()]);
  // If loaded directly on /item/<id>, open that item
  const m = location.pathname.match(/^\/item\/(\d+)$/);
  if (m) {
    const targetId = parseInt(m[1]);
    let idx = feed.findIndex(f => f.id === targetId);
    if (idx < 0) {
      // Item not in current feed (e.g. already read) — fetch it directly
      try {
        const item = await fetch(`/items/${targetId}`).then(r => r.ok ? r.json() : null);
        if (item) { feed.unshift(item); idx = 0; }
      } catch(_) {}
    }
    if (idx >= 0) { openItem(idx, true); return; }
  }
  showFeed(true);
}

async function loadFeed() {
  try {
    const r = await fetch(`${API}/feed?page_size=50&active=true`);
    const data = await r.json();
    feed = data.items || [];
    feedTotal = data.total || feed.length;
    renderFeed();
  } catch(e) {
    document.getElementById('loading').textContent = 'Failed to load feed: ' + e.message;
  }
}

// ── Feed view ─────────────────────────────────────────────────────────────
function timeAgo(isoStr) {
  if (!isoStr) return '';
  const secs = Math.floor((Date.now() - new Date(isoStr)) / 1000);
  if (secs < 60)  return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs/60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs/3600)}h ago`;
  return `${Math.floor(secs/86400)}d ago`;
}

function srcSummary(item) {
  const labels = item.source_labels || [];
  if (labels.length > 0 && labels.length <= 4) return esc(labels.join(', '));
  if (item.item_count > 1) return `${item.item_count} sources`;
  return esc(labels[0] || 'unknown');
}

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
        <span class="age-badge">${timeAgo(item.latest_seen_at)}</span>
        ${esc(item.headline)}
      </div>
      <div class="summary">${esc(item.summary)}</div>
      <div class="item-meta">
        ${esc((item.topics||[]).join(' · '))} &nbsp;·&nbsp; ${srcSummary(item)}
        ${interestBarHtml(item.interest_score)}
      </div>
    </div>`).join('');
}

function showFeed(replace) {
  document.getElementById('feed-view').style.display = '';
  document.getElementById('item-view').style.display = 'none';
  document.getElementById('interest-btns').style.display = 'none';
  document.getElementById('topbar-meta').textContent =
    feed.length === feedTotal ? `${feed.length} items` : `${feed.length} of ${feedTotal} items`;
  document.getElementById('bottombar-left').textContent = '';
  document.getElementById('bottombar-hint').textContent =
    '← → navigate · Enter open · R refresh · ? help';
  document.title = 'newsagg';
  if (replace) history.replaceState({view:'feed'}, '', '/');
  else history.pushState({view:'feed'}, '', '/');
}

// ── Item view ─────────────────────────────────────────────────────────────
function openItem(i, replace) {
  cursor = i;
  expanded = null;
  itemReadStart = Date.now();
  renderItem();
  document.getElementById('feed-view').style.display = 'none';
  document.getElementById('item-view').style.display = 'flex';
  const item = feed[cursor];
  if (item) {
    post(`/items/${item.id}/read`, {duration_seconds: 0, fully_read: false});
    if (replace) history.replaceState({view:'item', id:item.id}, '', `/item/${item.id}`);
    else history.pushState({view:'item', id:item.id}, '', `/item/${item.id}`);
  }
}

function renderItem() {
  const item = feed[cursor];
  if (!item) return;

  const topicsHtml = (item.topics||[]).map(t => {
    const w = _topicWeights[t];
    const score = w !== undefined ? ` <span style="color:var(--meta);font-size:11px">(${Math.round(w*100)}%)</span>` : '';
    return esc(t) + score;
  }).join(' · ');

  const srcLabels = item.source_labels || [];
  const srcIds = item.source_ids || [];
  const srcPubs = item.source_published_ats || [];

  let expandedHtml = '';
  if (expanded) {
    const excerptText = expanded.excerpt
      ? `<p>${esc(expanded.excerpt)}</p>`
      : `<p style="color:var(--meta);font-style:italic">No additional context available.</p>`;
    expandedHtml = `<div class="expanded-section">${excerptText}</div>`;
  }

  const sourceUrls = (expanded && (expanded.source_urls||[]).length)
    ? expanded.source_urls : (item.source_urls||[]);
  const linksHtml = sourceUrls.length
    ? `<p class="source-links">${sourceUrls.map((u, i) => {
        const label = srcLabels[i] || u;
        const sid = srcIds[i] || '';
        const srcW = sid && _sourceWeights[sid] !== undefined
          ? ` <span style="color:var(--meta);font-size:11px">(${Math.round(_sourceWeights[sid]*100)}%)</span>` : '';
        const pub = srcPubs[i] ? ` <span style="color:var(--meta);font-size:11px">${timeAgo(srcPubs[i])}</span>` : '';
        return `<span class="src-row">` +
          `<a href="${esc(u)}" target="_blank" rel="noopener" onclick="onLinkClick(${item.id})">${esc(label)}</a>${srcW}${pub}` +
          (sid ? ` <button class="src-ibtn" title="Less interest in this source" onclick="adjustSourceInterest('${esc(sid)}',-1)">−</button>` +
                 `<button class="src-ibtn" title="More interest in this source" onclick="adjustSourceInterest('${esc(sid)}',1)">+</button>` : '') +
          `</span>`;
      }).join('<br>')}</p>`
    : '';

  const bodyText = item.full_summary || item.summary;
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
      <span class="age-badge">${timeAgo(item.latest_seen_at)}</span>
      ${esc(item.headline)}
    </div>
    <p>${esc(bodyText)}</p>
    ${kpHtml}
    ${expandedHtml}
    ${linksHtml}
    <div class="item-meta-line">
      ${topicsHtml} &nbsp;·&nbsp; ${srcSummary(item)}
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

// ── Tap zones ─────────────────────────────────────────────────────────────
function zoneLeft()  { prevItem(); }
function zoneRight() { nextItem(); }

// ── Navigation ────────────────────────────────────────────────────────────
function nextItem() {
  recordRead();
  if (cursor + 1 < feed.length) {
    cursor++; expanded = null; itemReadStart = Date.now(); renderItem();
    const item = feed[cursor];
    if (item) history.replaceState({view:'item', id:item.id}, '', `/item/${item.id}`);
  } else { toast('End of feed'); }
}

function prevItem() {
  recordRead();
  if (cursor > 0) {
    cursor--; expanded = null; itemReadStart = Date.now(); renderItem();
    const item = feed[cursor];
    if (item) history.replaceState({view:'item', id:item.id}, '', `/item/${item.id}`);
  } else { showFeed(); }
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

// tracks clusters that got a link-click interest boost this session
const _linkBoosted = new Set();
const _sourceWeights = {};  // cache: source_id -> current weight
const _topicWeights = {};   // cache: topic -> current weight

async function loadWeights() {
  try {
    const [tr, sr] = await Promise.all([
      fetch('/topics').then(r => r.json()),
      fetch('/topics/sources').then(r => r.json()),
    ]);
    tr.forEach(t => { _topicWeights[t.topic] = t.weight; });
    sr.forEach(s => { _sourceWeights[s.id] = s.weight; });
  } catch(e) {}
}

function onLinkClick(clusterId) {
  if (_linkBoosted.has(clusterId)) return;
  _linkBoosted.add(clusterId);
  post(`/items/${clusterId}/interest`, {direction:'up'});
}

async function adjustSourceInterest(sourceId, direction) {
  const current = _sourceWeights[sourceId] ?? 0.5;
  const next = Math.max(0, Math.min(1, current + direction * 0.1));
  _sourceWeights[sourceId] = next;
  try {
    await fetch(`/topics/sources/${encodeURIComponent(sourceId)}/interest`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({weight: next}),
    });
    toast(direction > 0 ? 'Source boosted' : 'Source reduced');
    renderItem();
  } catch(e) { toast('Failed to update source interest'); }
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
      const permalink = `${location.origin}/item/${item.id}`;
      if (navigator.share) { navigator.share({title: item.headline, url: permalink}); }
      else { await navigator.clipboard.writeText(permalink); toast('Link copied'); }
      break;
    case 'interest_up':
      await post(`/items/${item.id}/interest`, {direction:'up'});
      toast('More like this ✓');
      break;
    case 'interest_down':
      if (_linkBoosted.delete(item.id)) {
        await post(`/items/${item.id}/interest`, {direction:'down'});
      }
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
  if (adx < 15 && ady < 15 && dur > 600) { openMenu(); return; }
  if (adx > 60 && adx > ady) {
    if (dx < 0) discardItem();
    else expandItem();
  } else if (ady > 60 && ady > adx) {
    if (dy < 0) nextItem();
    else prevItem();
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
      document.getElementById('feed-view').scrollTop += 80;
    } else if (e.key === 'ArrowUp' || e.key === 'k') {
      document.getElementById('feed-view').scrollTop -= 80;
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

// ── Popstate (browser back/forward) ──────────────────────────────────────
window.addEventListener('popstate', e => {
  const state = e.state;
  if (!state || state.view === 'feed') {
    document.getElementById('feed-view').style.display = '';
    document.getElementById('item-view').style.display = 'none';
    document.getElementById('interest-btns').style.display = 'none';
    document.title = 'newsagg';
    return;
  }
  if (state.view === 'item') {
    const idx = feed.findIndex(f => f.id === state.id);
    if (idx >= 0) {
      cursor = idx; expanded = null; itemReadStart = Date.now();
      renderItem();
      document.getElementById('feed-view').style.display = 'none';
      document.getElementById('item-view').style.display = 'flex';
    }
  }
});

boot();
connectSSE();
</script>
</body>
</html>
"""


_INTERESTS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Interests – newsagg</title>
<style>
  :root {
    --sat: env(safe-area-inset-top, 0px);
    --sab: env(safe-area-inset-bottom, 0px);
    --sal: env(safe-area-inset-left, 0px);
    --sar: env(safe-area-inset-right, 0px);
    --bg: #fff; --fg: #111; --meta: #666; --border: #ddd; --accent: #0057b8;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font: 16px/1.5 system-ui, sans-serif; background: var(--bg); color: var(--fg);
         padding: calc(var(--sat) + 12px) 16px calc(var(--sab) + 16px); max-width: 640px; margin: 0 auto; }
  h1 { font-size: 20px; margin-bottom: 16px; }
  h2 { font-size: 15px; color: var(--meta); margin: 20px 0 8px; text-transform: uppercase; letter-spacing: .05em; }
  a.back { font-size: 14px; color: var(--accent); text-decoration: none; display: inline-block; margin-bottom: 16px; }
  .row { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--border); }
  .label { flex: 1; font-size: 15px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .score { font-size: 13px; color: var(--meta); width: 34px; text-align: right; }
  .bar-wrap { width: 80px; background: var(--border); border-radius: 4px; height: 6px; flex-shrink: 0; }
  .bar-fill { height: 6px; border-radius: 4px; background: var(--accent); transition: width .2s; }
  .btn { border: 1px solid var(--border); background: none; cursor: pointer; border-radius: 4px;
         width: 28px; height: 28px; font-size: 16px; line-height: 1; color: var(--fg); flex-shrink: 0; }
  .btn:hover { background: #f0f0f0; }
  #status { font-size: 13px; color: var(--meta); margin-top: 16px; min-height: 20px; }
</style>
</head>
<body>
<a class="back" href="/">← Back to feed</a>
<h1>Interests</h1>
<p style="font-size:13px;color:var(--meta);margin-bottom:12px"><a href="/stats" style="color:var(--accent)">View stats →</a></p>
<h2>Topics</h2>
<div id="topics-list"><p style="color:var(--meta)">Loading…</p></div>
<h2>Cities</h2>
<div id="geo-city-list"><p style="color:var(--meta)">Loading…</p></div>
<h2>States / Provinces</h2>
<div id="geo-state-list"><p style="color:var(--meta)">Loading…</p></div>
<h2>Countries</h2>
<div id="geo-country-list"><p style="color:var(--meta)">Loading…</p></div>
<h2>World Regions</h2>
<div id="geo-region-list"><p style="color:var(--meta)">Loading…</p></div>
<h2>Sources</h2>
<div id="sources-list"><p style="color:var(--meta)">Loading…</p></div>
<div id="status"></div>
<script>
function pct(w) { return Math.round(w * 100); }

function row(label, weight, onUp, onDown) {
  const d = document.createElement('div');
  d.className = 'row';
  d.innerHTML = `
    <span class="label" title="${esc(label)}">${esc(label)}</span>
    <div class="bar-wrap"><div class="bar-fill" style="width:${pct(weight)}%"></div></div>
    <span class="score">${pct(weight)}%</span>
    <button class="btn" title="Less interest">−</button>
    <button class="btn" title="More interest">+</button>`;
  const [btnDown, btnUp] = d.querySelectorAll('.btn');
  btnDown.onclick = async () => { const w = await onDown(); updateRow(d, w); };
  btnUp.onclick   = async () => { const w = await onUp();   updateRow(d, w); };
  return d;
}

function updateRow(d, weight) {
  d.querySelector('.bar-fill').style.width = pct(weight) + '%';
  d.querySelector('.score').textContent = pct(weight) + '%';
}

function status(msg) { document.getElementById('status').textContent = msg; }

async function put(path, weight) {
  const r = await fetch(path, { method: 'PUT', headers: {'Content-Type':'application/json'},
                                body: JSON.stringify({weight}) });
  if (!r.ok) throw new Error(r.status);
}

function clamp(w) { return Math.max(0, Math.min(1, w)); }
const STEP = 0.1;

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function load() {
  const [tr, sr] = await Promise.all([
    fetch('/topics').then(r => r.json()),
    fetch('/topics/sources').then(r => r.json()),
  ]);

  // Split into regular topics and geo tags (geo:level:place)
  const geoRe = /^geo:(city|state|country|region):(.+)$/;
  const regular = [], geo = {city:[], state:[], country:[], region:[]};
  tr.forEach(t => {
    const m = t.topic.match(geoRe);
    if (m) geo[m[1]].push({...t, place: m[2]});
    else regular.push(t);
  });

  let tw = {};
  tr.forEach(t => { tw[t.topic] = t.weight; });

  function addTopicRows(el, items, labelFn) {
    el.innerHTML = '';
    if (!items.length) { el.innerHTML = '<p style="color:var(--meta);font-size:13px">None seen yet.</p>'; return; }
    items.forEach(t => {
      el.appendChild(row(
        labelFn(t),
        t.weight,
        async () => { const w = clamp(tw[t.topic] + STEP); await put(`/topics/${encodeURIComponent(t.topic)}/interest`, w); tw[t.topic] = w; status('Saved'); return w; },
        async () => { const w = clamp(tw[t.topic] - STEP); await put(`/topics/${encodeURIComponent(t.topic)}/interest`, w); tw[t.topic] = w; status('Saved'); return w; },
      ));
    });
  }

  addTopicRows(document.getElementById('topics-list'), regular,
    t => `${t.topic} (${t.item_count})`);
  addTopicRows(document.getElementById('geo-city-list'),   geo.city,
    t => `${t.place} (${t.item_count})`);
  addTopicRows(document.getElementById('geo-state-list'),  geo.state,
    t => `${t.place} (${t.item_count})`);
  addTopicRows(document.getElementById('geo-country-list'),geo.country,
    t => `${t.place} (${t.item_count})`);
  addTopicRows(document.getElementById('geo-region-list'), geo.region,
    t => `${t.place} (${t.item_count})`);

  const sEl = document.getElementById('sources-list');
  sEl.innerHTML = '';
  let sw = {};
  sr.forEach(s => {
    sw[s.id] = s.weight;
    sEl.appendChild(row(
      s.label,
      s.weight,
      async () => { const w = clamp(sw[s.id] + STEP); await put(`/topics/sources/${encodeURIComponent(s.id)}/interest`, w); sw[s.id] = w; status('Saved'); return w; },
      async () => { const w = clamp(sw[s.id] - STEP); await put(`/topics/sources/${encodeURIComponent(s.id)}/interest`, w); sw[s.id] = w; status('Saved'); return w; },
    ));
  });
}

load().catch(e => { document.getElementById('status').textContent = 'Load failed: ' + e; });
</script>
</body>
</html>
"""


_STATS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Stats – newsagg</title>
<style>
  :root {
    --sat: env(safe-area-inset-top, 0px);
    --sab: env(safe-area-inset-bottom, 0px);
    --bg: #fff; --fg: #111; --meta: #666; --border: #ddd; --accent: #0057b8; --green: #2a9d2a;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font: 15px/1.5 system-ui, sans-serif; background: var(--bg); color: var(--fg);
         padding: calc(var(--sat) + 12px) 16px calc(var(--sab) + 24px); max-width: 900px; margin: 0 auto; }
  h1 { font-size: 20px; margin-bottom: 4px; }
  h2 { font-size: 14px; color: var(--meta); margin: 24px 0 10px; text-transform: uppercase; letter-spacing: .05em; border-bottom: 1px solid var(--border); padding-bottom: 4px; }
  a.back { font-size: 13px; color: var(--accent); text-decoration: none; display: inline-block; margin-bottom: 14px; }
  .nav { display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }
  .nav a { font-size: 13px; color: var(--accent); text-decoration: none; }

  /* Summary cards */
  .cards { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
  .card { border: 1px solid var(--border); border-radius: 6px; padding: 12px 18px; min-width: 120px; }
  .card .val { font-size: 28px; font-weight: bold; }
  .card .lbl { font-size: 12px; color: var(--meta); }

  /* Charts */
  .chart-wrap { position: relative; height: 160px; margin-bottom: 4px; overflow: hidden; }
  canvas { display: block; }

  /* Sources table */
  .src-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .src-table th { text-align: left; padding: 6px 8px; border-bottom: 2px solid var(--border);
                  font-size: 12px; color: var(--meta); white-space: nowrap; }
  .src-table td { padding: 5px 8px; border-bottom: 1px solid var(--border); vertical-align: middle; }
  .src-table tr:hover td { background: #f8f8f8; }
  .spark { display: inline-block; vertical-align: middle; }
  .interest-val { font-size: 12px; color: var(--meta); width: 30px; text-align: right; display: inline-block; }
  .ibtn { border: 1px solid var(--border); background: none; cursor: pointer; border-radius: 3px;
          width: 22px; height: 22px; font-size: 14px; line-height: 1; color: var(--fg); }
  .ibtn:hover { background: #eee; }
  .err { color: #c00; font-size: 11px; }
  #status { font-size: 12px; color: var(--meta); margin-top: 12px; min-height: 18px; }
  .legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px; color: var(--meta); margin-bottom: 6px; }
  .legend span::before { content: ''; display: inline-block; width: 10px; height: 10px;
                          border-radius: 2px; margin-right: 4px; vertical-align: middle; }
  .leg-read::before { background: #0057b8; }
  .leg-click::before { background: #2a9d2a; }
  .leg-discard::before { background: #c44; }
  .leg-save::before { background: #c80; }
</style>
</head>
<body>
<a class="back" href="/">← Feed</a>
<div class="nav">
  <a href="/interests">Interests</a>
  <a href="/stats">Stats</a>
</div>
<h1>Stats</h1>

<div class="cards" id="cards"></div>

<h2>Activity — last 7 days (hourly)</h2>
<div class="legend">
  <span class="leg-read">Read</span>
  <span class="leg-click">Link click</span>
  <span class="leg-discard">Discard</span>
  <span class="leg-save">Save</span>
</div>
<div class="chart-wrap"><canvas id="chart7"></canvas></div>

<h2>Activity — last 30 days (daily)</h2>
<div class="legend">
  <span class="leg-read">Read</span>
  <span class="leg-click">Link click</span>
  <span class="leg-discard">Discard</span>
  <span class="leg-save">Save</span>
</div>
<div class="chart-wrap"><canvas id="chart30"></canvas></div>

<h2>Sources</h2>
<table class="src-table" id="src-table">
  <thead><tr>
    <th>Source</th>
    <th>Items</th>
    <th>Reads</th>
    <th>Link clicks</th>
    <th>Last 14d</th>
    <th>Interest</th>
    <th></th>
  </tr></thead>
  <tbody id="src-body"></tbody>
</table>
<div id="status"></div>

<script>
const STEP = 0.1;
const COLORS = {read:'#0057b8', interest_up:'#2a9d2a', discard:'#c44', save:'#c80', expand:'#888'};

function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function pct(w) { return Math.round((w||0)*100); }
function status(msg) { document.getElementById('status').textContent = msg; }

// ── Mini bar chart on a canvas ──
function drawBars(canvas, labels, series) {
  // series: [{label, color, values:[]}]
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.parentElement.clientWidth, H = 160;
  canvas.width = W * dpr; canvas.height = H * dpr;
  canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const pad = {t:8, r:8, b:28, l:36};
  const cw = W - pad.l - pad.r;
  const ch = H - pad.t - pad.b;
  const n = labels.length;
  const nSeries = series.length;
  const maxVal = Math.max(1, ...series.flatMap(s => s.values));
  const barGroup = cw / n;
  const barW = Math.max(1, barGroup / nSeries - 1);

  // gridlines
  ctx.strokeStyle = '#eee'; ctx.lineWidth = 1;
  for (let i=0; i<=4; i++) {
    const y = pad.t + ch - (ch * i / 4);
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l+cw, y); ctx.stroke();
    ctx.fillStyle = '#aaa'; ctx.font = '10px system-ui'; ctx.textAlign = 'right';
    ctx.fillText(Math.round(maxVal * i / 4), pad.l - 4, y + 3);
  }

  // bars
  series.forEach((s, si) => {
    ctx.fillStyle = s.color;
    s.values.forEach((v, i) => {
      const bh = (v / maxVal) * ch;
      const x = pad.l + i * barGroup + si * (barW + 1);
      ctx.fillRect(x, pad.t + ch - bh, barW, bh);
    });
  });

  // x-axis labels (every nth)
  ctx.fillStyle = '#888'; ctx.font = '10px system-ui'; ctx.textAlign = 'center';
  const step = Math.max(1, Math.ceil(n / 12));
  labels.forEach((lbl, i) => {
    if (i % step !== 0) return;
    const x = pad.l + i * barGroup + barGroup / 2;
    // show only time for hourly, date for daily
    const short = lbl.includes('T') ? lbl.slice(11) : lbl.slice(5);
    ctx.fillText(short, x, H - pad.b + 14);
  });
}

function buildCharts(summary) {
  // 7-day hourly
  buildChart('chart7', summary.hourly, 'hour');
  // 30-day daily
  buildChart('chart30', summary.daily, 'day');
}

function buildChart(id, rows, key) {
  const canvas = document.getElementById(id);
  // collect all labels in order
  const labelSet = [...new Set(rows.map(r => r[key]))].sort();
  const events = ['read','interest_up','discard','save'];
  const byEvent = {};
  events.forEach(e => { byEvent[e] = {}; });
  rows.forEach(r => {
    if (byEvent[r.event]) byEvent[r.event][r[key]] = r.n;
  });
  const series = events
    .filter(e => Object.values(byEvent[e]).some(v => v > 0))
    .map(e => ({
      label: e,
      color: COLORS[e] || '#888',
      values: labelSet.map(l => byEvent[e][l] || 0),
    }));
  if (labelSet.length) drawBars(canvas, labelSet, series);
}

// ── Sparkline SVG ──
function sparkline(values, w, h) {
  const max = Math.max(1, ...values);
  const n = values.length;
  const bw = w / n;
  const bars = values.map((v, i) => {
    const bh = Math.max(1, Math.round((v / max) * (h - 2)));
    const x = Math.round(i * bw);
    const y = h - bh;
    return `<rect x="${x}" y="${y}" width="${Math.max(1,Math.round(bw)-1)}" height="${bh}" fill="#0057b8" opacity="0.7"/>`;
  }).join('');
  return `<svg width="${w}" height="${h}" class="spark">${bars}</svg>`;
}

// ── Sources table ──
const _sw = {};  // source_id -> current interest weight

function buildSources(sources) {
  sources.forEach(s => { _sw[s.id] = s.interest; });
  const tbody = document.getElementById('src-body');
  tbody.innerHTML = '';
  sources.forEach(s => {
    const tr = document.createElement('tr');
    const errBadge = s.fetch_error_count > 0
      ? `<span class="err" title="${s.fetch_error_count} fetch errors"> ⚠${s.fetch_error_count}</span>` : '';
    tr.innerHTML = `
      <td>${esc(s.label)}${errBadge}</td>
      <td>${s.item_count}</td>
      <td>${s.read_count}</td>
      <td>${s.link_count}</td>
      <td>${sparkline(s.sparkline, 70, 20)}</td>
      <td>
        <span class="interest-val" id="iv-${esc(s.id)}">${pct(s.interest)}%</span>
      </td>
      <td>
        <button class="ibtn" title="Less interest" onclick="adjSrc('${esc(s.id)}',-1)">−</button>
        <button class="ibtn" title="More interest" onclick="adjSrc('${esc(s.id)}',1)">+</button>
      </td>`;
    tbody.appendChild(tr);
  });
}

async function adjSrc(id, dir) {
  const next = Math.max(0, Math.min(1, (_sw[id] ?? 0.5) + dir * STEP));
  _sw[id] = next;
  document.getElementById('iv-' + id).textContent = pct(next) + '%';
  try {
    await fetch(`/topics/sources/${encodeURIComponent(id)}/interest`, {
      method: 'PUT', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({weight: next}),
    });
    status('Saved');
  } catch(e) { status('Save failed'); }
}

// ── Summary cards ──
function buildCards(totals) {
  const labels = {
    read: 'Items opened',
    interest_up: 'Links clicked',
    discard: 'Discarded',
    save: 'Saved',
    expand: 'Expanded',
  };
  const cards = document.getElementById('cards');
  cards.innerHTML = Object.entries(labels).map(([k, l]) =>
    `<div class="card"><div class="val">${totals[k] || 0}</div><div class="lbl">${l}</div></div>`
  ).join('');
  // engagement rate
  const reads = totals.read || 0;
  const clicks = totals.interest_up || 0;
  const rate = reads > 0 ? Math.round(clicks / reads * 100) : 0;
  cards.innerHTML += `<div class="card"><div class="val">${rate}%</div><div class="lbl">Click-through rate</div></div>`;
}

async function load() {
  const [summary, sources] = await Promise.all([
    fetch('/stats/summary').then(r => r.json()),
    fetch('/stats/sources').then(r => r.json()),
  ]);
  buildCards(summary.totals);
  buildCharts(summary);
  buildSources(sources);
}

load().catch(e => status('Load failed: ' + e));
window.addEventListener('resize', () => {
  // redraw charts on resize
  fetch('/stats/summary').then(r => r.json()).then(buildCharts).catch(()=>{});
});
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def webui():
    return HTMLResponse(_HTML)


@router.get("/item/{item_id}", response_class=HTMLResponse, include_in_schema=False)
async def webui_item(item_id: int):
    return HTMLResponse(_HTML)


@router.get("/interests", response_class=HTMLResponse, include_in_schema=False)
async def interests_page():
    return HTMLResponse(_INTERESTS_HTML)


@router.get("/stats", response_class=HTMLResponse, include_in_schema=False)
async def stats_page():
    return HTMLResponse(_STATS_HTML)


@router.get("/manifest.json", include_in_schema=False)
async def manifest():
    return Response(_MANIFEST, media_type="application/manifest+json")


@router.get("/sw.js", include_in_schema=False)
async def service_worker():
    return Response(_SW_JS, media_type="application/javascript")


@router.get("/icon.svg", include_in_schema=False)
async def icon_svg():
    return Response(_SVG_ICON, media_type="image/svg+xml")


@router.get("/icon-192.png", include_in_schema=False)
async def icon_192():
    return Response(_PNG_192, media_type="image/png")


@router.get("/icon-512.png", include_in_schema=False)
async def icon_512():
    return Response(_PNG_512, media_type="image/png")
