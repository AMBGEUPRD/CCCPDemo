/* results-shared.js — Shared utilities for all results pages */

/* ── Session state (populated by loadSession) ── */
var session  = null;
var analysis = {};

/**
 * Load the analysis session.
 * Tries sessionStorage first, then falls back to GET /api/results/{id}.
 * Returns a Promise<boolean>.
 */
async function loadSession() {
  var params = new URLSearchParams(location.search);
  var id     = params.get("id");
  console.log('[BIM-AI] loadSession id=' + id);
  if (!id) return false;

  // 1. Try sessionStorage (instant, same-tab)
  try {
    var stored = sessionStorage.getItem(id);
    console.log('[BIM-AI] sessionStorage hit:', !!stored, stored ? stored.length + ' chars' : 'null');
    if (stored) {
      _parseSession(stored);
      console.log('[BIM-AI] session parsed OK, analysis keys:', Object.keys(analysis));
      return true;
    }
  } catch (e) {
    console.warn('[BIM-AI] sessionStorage parse failed, trying API', e);
    try { sessionStorage.removeItem(id); } catch(_) { /* ignore */ }
  }

  // 2. Fallback: fetch from server-side store
  try {
    console.log('[BIM-AI] Fetching from API...');
    var resp = await fetch('/api/results/' + encodeURIComponent(id));
    console.log('[BIM-AI] API response:', resp.status);
    if (resp.ok) {
      var data = await resp.text();
      console.log('[BIM-AI] API data length:', data.length);
      _parseSession(data);
      console.log('[BIM-AI] session parsed OK from API, analysis keys:', Object.keys(analysis));
      // Re-populate sessionStorage so subsequent navigations are instant
      try { sessionStorage.setItem(id, data); } catch(_) { /* quota */ }
      return true;
    }
  } catch (e) {
    console.error('[BIM-AI] API fetch failed:', e);
  }

  console.warn('[BIM-AI] loadSession returning false — no data found');
  return false;
}

function _parseSession(jsonStr) {
  console.log('[BIM-AI] _parseSession input length:', jsonStr.length);
  session = JSON.parse(jsonStr);
  console.log('[BIM-AI] session keys:', Object.keys(session));
  console.log('[BIM-AI] session.result type:', typeof session.result, 'length:', (session.result||'').length);
  var rawText = session.result || "{}";
  try { analysis = typeof rawText === "string" ? JSON.parse(rawText) : rawText; }
  catch(e) { console.error('[BIM-AI] analysis parse failed:', e); analysis = { raw: rawText }; }
  console.log('[BIM-AI] analysis keys:', Object.keys(analysis));
}

/**
 * Show a rendering error in the error-state div.
 * Used by page scripts when loadSession succeeds but rendering throws.
 */
function showRenderError(err) {
  console.error('[BIM-AI] Rendering error:', err);
  var errDiv = document.getElementById('errorState');
  if (errDiv) {
    errDiv.querySelector('.error-title').textContent = 'Rendering error';
    errDiv.querySelector('.error-sub').textContent   = String(err.message || err);
    // Add raw JSON fallback button if we have data
    if (session && session.result) {
      var btn = document.createElement('button');
      btn.className = 'btn-new';
      btn.textContent = 'Copy raw JSON';
      btn.style.marginTop = '8px';
      btn.addEventListener('click', function() {
        navigator.clipboard.writeText(
          typeof session.result === 'string' ? session.result : JSON.stringify(session.result, null, 2)
        ).then(function() { btn.textContent = 'Copied!'; });
      });
      errDiv.appendChild(btn);
    }
    errDiv.classList.add('on');
  }
  // Hide the content container
  var content = document.getElementById('resultsContent')
             || document.getElementById('generateContent')
             || document.getElementById('warningsContent');
  if (content) content.style.display = 'none';
}

/* Dark mode toggle is now handled by base.html */

/* ── Animated KPI counter helper ── */
function animateValue(el, target, duration) {
  var start = 0;
  var startTime = null;
  function easeOut(t) { return 1 - Math.pow(1 - t, 3); }
  function step(ts) {
    if (!startTime) startTime = ts;
    var progress = Math.min((ts - startTime) / duration, 1);
    var val = Math.round(easeOut(progress) * target);
    el.textContent = val;
    if (progress < 1) requestAnimationFrame(step);
  }
  if (target > 0) requestAnimationFrame(step);
}


/* ── Column sort for data tables ── */
function enableTableSort(table) {
  var headers = table.querySelectorAll('th');
  headers.forEach(function(th, colIdx) {
    th.addEventListener('click', function() {
      var tbody = table.querySelector('tbody');
      if (!tbody) return;
      var rows = Array.from(tbody.querySelectorAll('tr'));
      var isAsc = th.classList.contains('sort-asc');

      // Remove sort state from all headers in this table
      headers.forEach(function(h) { h.classList.remove('sort-asc', 'sort-desc'); });

      if (isAsc) {
        th.classList.add('sort-desc');
      } else {
        th.classList.add('sort-asc');
      }

      var dir = isAsc ? -1 : 1;
      rows.sort(function(a, b) {
        var aText = (a.cells[colIdx] || {}).textContent || '';
        var bText = (b.cells[colIdx] || {}).textContent || '';
        var aNum = parseFloat(aText);
        var bNum = parseFloat(bText);
        if (!isNaN(aNum) && !isNaN(bNum)) return (aNum - bNum) * dir;
        return aText.localeCompare(bText) * dir;
      });
      rows.forEach(function(row) { tbody.appendChild(row); });
    });
  });
}

/* ── WIN 1: Table search/filter ── */
function enableTableSearch(tableId) {
  var input = document.querySelector('.table-search[data-table="' + tableId + '"]');
  var table = document.getElementById(tableId);
  if (!input || !table) return;
  input.addEventListener('input', function() {
    var q = this.value.trim().toLowerCase();
    var rows = table.querySelectorAll('tbody tr');
    rows.forEach(function(row) {
      row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
  });
}

/* ── WIN 2: Export table to CSV ── */
function tableToCSV(tableId) {
  var table = document.getElementById(tableId);
  if (!table) return '';
  var rows = [];
  // Headers — strip sort indicator text
  var headers = Array.from(table.querySelectorAll('thead th')).map(function(th) {
    return '"' + th.textContent.replace(/[▲▼↑↓▴▾\u25B2\u25BC\u2191\u2193\u25B4\u25BE\u2650\u2660]/g, '').trim().replace(/"/g, '""') + '"';
  });
  rows.push(headers.join(','));
  // Visible body rows only
  table.querySelectorAll('tbody tr').forEach(function(tr) {
    if (tr.style.display === 'none') return;
    var cells = Array.from(tr.querySelectorAll('td')).map(function(td) {
      return '"' + td.textContent.trim().replace(/"/g, '""') + '"';
    });
    rows.push(cells.join(','));
  });
  return rows.join('\n');
}

document.addEventListener('click', function(e) {
  var btn = e.target.closest('.btn-export-csv');
  if (!btn) return;
  var tableId  = btn.dataset.table;
  var filename = btn.dataset.filename || 'export.csv';
  var csv = tableToCSV(tableId);
  var blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  var url  = URL.createObjectURL(blob);
  var a    = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
});

/* ── WIN 3: Collapsible section cards ── */
document.addEventListener('click', function(e) {
  var btn = e.target.closest('.btn-collapse');
  if (!btn) return;
  var card = btn.closest('.section-card');
  if (card) card.classList.toggle('collapsed');
});


/* ── Detect auto-generated / internal Tableau field names ── */
function isAutoGenerated(name) {
  if (!name) return false;
  // Matches patterns like: Calculation_123456789, [Calculation_...], :Measure Values,
  // __Record_ID__, %something, long hex-like strings with no spaces
  return /^(\[?Calculation_\d+\]?|:[\w\s]+|__\w+__|%\w+)$/i.test(name)
      || /^[a-f0-9]{8,}$/i.test(name)
      || (name.length > 30 && !/\s/.test(name) && /[_0-9]{6,}/.test(name));
}

/* Build the field name cell: show caption as primary, raw name as secondary,
   warn badge if name looks auto-generated */
function fieldNameCell(name, caption) {
  var displayName = caption || name || '\u2014';
  var rawId       = (caption && caption !== name) ? name : null;
  var autoGen     = isAutoGenerated(name) && !caption;
  var html = '<div class="field-name-cell">';
  html += '<span class="field-label">' + esc(displayName) + '</span>';
  if (rawId) {
    html += '<span class="field-raw-id" title="Click to expand" onclick="this.classList.toggle(\'expanded\')">'
          + '<svg class="raw-expand-icon" width="9" height="9" viewBox="0 0 9 9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M1.5 3l3 3 3-3"/></svg>'
          + esc(rawId)
          + '</span>';
  }
  if (autoGen) {
    html += '<span class="pill warn" style="font-size:10px;padding:1px 7px;width:fit-content">'
          + '<svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M5 1v4M5 7.5v.5"/><circle cx="5" cy="5" r="4.25"/></svg>'
          + 'auto-generated</span>';
  }
  html += '</div>';
  return html;
}

/* ── Syntax highlight for Tableau/DAX keywords ── */
var FORMULA_KEYWORDS = /\b(IF|THEN|ELSE|END|SUM|AVG|COUNT|FIXED|INCLUDE|EXCLUDE|DATEPART|ZN|ISNULL|IIF|AND|OR|NOT|COUNTD|MIN|MAX|ATTR|CASE|WHEN|CONTAINS|STARTSWITH|ENDSWITH|LEFT|RIGHT|MID|LEN|TRIM|UPPER|LOWER|ROUND|INT|FLOAT|STR|DATE|DATEADD|DATEDIFF|DATETRUNC|TODAY|NOW|YEAR|MONTH|DAY|LOOKUP|RUNNING_SUM|WINDOW_SUM|RANK|INDEX|FIRST|LAST|SIZE|TOTAL|CALCULATE|FILTER|ALL|VALUES|DISTINCT|RELATED|SUMX|AVERAGEX|COUNTAX|MINX|MAXX|DIVIDE|BLANK|ISBLANK|SELECTEDVALUE|SWITCH|TRUE|FALSE|VAR|RETURN)\b/gi;

function highlightFormula(text) {
  return esc(text).replace(FORMULA_KEYWORDS, function(m) {
    return '<span class="kw">' + m + '</span>';
  });
}

// ── Helpers ──
function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function dtypePill(dt) {
  if (!dt) return '<span class="pill dim">\u2014</span>';
  const map = { string:'string', integer:'int', real:'int', date:'date', datetime:'date', boolean:'dim' };
  const cls = map[dt] || 'dim';
  return `<span class="pill ${cls}">${esc(dt)}</span>`;
}


/* ════════════════════════════════════════════════════════
   SSE Stream Manager — centralised abort + cleanup
   ════════════════════════════════════════════════════════ */

/**
 * Registry of active SSE streams.  Each entry is an AbortController.
 * When the user navigates away (beforeunload), all active streams
 * are aborted to prevent orphaned server-side processes and memory
 * leaks.
 */
var _activeStreams = {};
var _streamCounter = 0;

/**
 * Start a managed SSE fetch.
 *
 * @param {string}   url       — POST endpoint path
 * @param {object}   body      — JSON body to send
 * @param {function} onMessage — called for each parsed SSE message
 * @param {object}   [opts]    — optional: { formData: FormData } for multipart
 * @returns {Promise<void>}    — resolves when stream ends
 *
 * Usage:
 *   await sseStream('/tdd-stream', { workbook_name: 'X' }, function(msg) {
 *     if (msg.state === 'complete') { ... }
 *   });
 */
async function sseStream(url, body, onMessage, opts) {
  var id = ++_streamCounter;
  var controller = new AbortController();
  _activeStreams[id] = controller;

  var fetchOpts = { method: 'POST', signal: controller.signal };
  if (opts && opts.formData) {
    fetchOpts.body = opts.formData;
  } else {
    fetchOpts.headers = { 'Content-Type': 'application/json' };
    fetchOpts.body = JSON.stringify(body);
  }

  try {
    var resp = await fetch(url, fetchOpts);
    if (!resp.ok) {
      var errText = await resp.text();
      throw new Error(errText || 'HTTP ' + resp.status);
    }
    var reader = resp.body.getReader();
    var decoder = new TextDecoder();
    var buffer = '';

    while (true) {
      var chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      var boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        var raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        var dataLine = raw.split('\n').find(function(l) { return l.startsWith('data:'); });
        if (!dataLine) continue;
        var msg;
        try { msg = JSON.parse(dataLine.slice(5).trim()); } catch(e) { continue; }
        onMessage(msg);
      }
    }
  } finally {
    delete _activeStreams[id];
  }
}

/**
 * Abort all active SSE streams.  Called automatically on page
 * unload and can be called manually when switching contexts.
 */
function abortAllStreams() {
  Object.keys(_activeStreams).forEach(function(id) {
    try { _activeStreams[id].abort(); } catch(_) {}
  });
  _activeStreams = {};
}

/* Abort active streams when navigating away */
window.addEventListener('beforeunload', abortAllStreams);

/**
 * Guard a button against double-click during an async operation.
 * Disables the button, runs the callback, then re-enables on
 * completion or error.
 *
 * @param {HTMLElement} btn — button element to guard
 * @param {function} fn    — async function to execute
 */
async function guardButton(btn, fn) {
  if (btn.disabled) return;
  btn.disabled = true;
  var prevText = btn.textContent;
  try {
    await fn();
  } finally {
    btn.disabled = false;
  }
}

