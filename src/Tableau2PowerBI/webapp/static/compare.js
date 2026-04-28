/* ============================================================
   compare.js — Comparison result page
   ============================================================ */

function initCompareResultPage() {
  /* ── Parse URL: /projects/{name}/compare/{id} ─────────────── */
  var parts = location.pathname.split('/');
  var compareIdx = parts.indexOf('compare');
  var projectsIdx = parts.indexOf('projects');
  var projectName = projectsIdx >= 0 ? decodeURIComponent(parts[projectsIdx + 1] || '') : '';
  var compareId   = compareIdx  >= 0 ? decodeURIComponent(parts[compareIdx  + 1] || '') : '';

  /* ── DOM references ──────────────────────────────────────────── */
  var titleEl     = document.getElementById('cmpTitle');
  var metaEl      = document.getElementById('cmpMeta');
  var chipsEl     = document.getElementById('cmpChips');
  var backBtn     = document.getElementById('backBtn');
  var exportBtn   = document.getElementById('exportMdBtn');
  var runningEl   = document.getElementById('cmpRunning');
  var errorEl     = document.getElementById('cmpError');
  var errorMsgEl  = document.getElementById('cmpErrorMsg');
  var resultsEl   = document.getElementById('cmpResults');
  var breadProj   = document.getElementById('breadcrumbProject');
  var breadCmp    = document.getElementById('breadcrumbCmp');
  var tooltip     = document.getElementById('scoreTooltip');

  var projectUrl  = '/projects/' + encodeURIComponent(projectName);
  if (backBtn)    backBtn.href = projectUrl;
  if (breadProj)  { breadProj.textContent = projectName; breadProj.href = projectUrl; }
  if (exportBtn) {
    exportBtn.href = '/api/projects/' + encodeURIComponent(projectName) +
                     '/comparisons/' + encodeURIComponent(compareId) + '/report-md';
  }

  var _pollTimer       = null;
  var _activeCriterion = 'overall';
  var _currentPairs    = [];
  var _currentNames    = [];

  /* ── Initial load ────────────────────────────────────────────── */
  loadCompareResult();

  async function loadCompareResult() {
    try {
      var r = await fetch('/api/projects/' + encodeURIComponent(projectName) +
                          '/comparisons/' + encodeURIComponent(compareId));
      if (!r.ok) { showError('Could not load comparison (HTTP ' + r.status + ')'); return; }
      var data = await r.json();
      renderHeader(data);

      if (data.status === 'running') {
        show(runningEl); hide(errorEl); hide(resultsEl);
        if (!_pollTimer) _pollTimer = setInterval(loadCompareResult, 5000);
        return;
      }
      if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }

      if (data.status === 'error') {
        showError(data.error || 'Unknown error');
        return;
      }
      if (data.status === 'complete' && data.result) {
        hide(runningEl); hide(errorEl); show(resultsEl);
        renderResults(data.result, data);
      }
    } catch (e) { showError(e.message || 'Request failed'); }
  }

  function renderHeader(data) {
    var date = _fmtDate(data.created_at);
    if (titleEl) titleEl.textContent = 'Comparison — ' + date;
    if (breadCmp) breadCmp.textContent = 'Comparison ' + date;
    if (metaEl)  metaEl.textContent   = (data.workbook_names || []).length + ' reports · ' + date;
    if (chipsEl) {
      chipsEl.innerHTML = (data.workbook_names || []).map(function(n) {
        return '<span class="comparison-chip">' + _esc(n) + '</span>';
      }).join('');
    }
    if (exportBtn && data.status === 'complete') exportBtn.style.display = '';
  }

  function renderResults(result, meta) {
    /* Executive Summary */
    var summaryEl = document.getElementById('execSummary');
    if (summaryEl) summaryEl.textContent = result.executive_summary || '';

    /* Similarity Matrix */
    var pairs = result.similarity_pairs || [];
    if (pairs.length > 0) {
      var matrixSection = document.getElementById('matrixSection');
      var tableEl = document.getElementById('similarityTable');
      if (matrixSection && tableEl) {
        _currentPairs = pairs;
        _currentNames = meta.workbook_names || [];
        matrixSection.style.display = '';
        tableEl.innerHTML = buildMatrix(pairs, _currentNames, _activeCriterion);
        wireTooltips(tableEl, pairs);
        wireMatrixTabs(tableEl, pairs);
      }
    }

    /* Recommendation cards */
    var recEl = document.getElementById('recCards');
    if (recEl) {
      var groups = result.groups || [];
      var order = { merge: 0, borderline: 1, keep_separate: 2 };
      groups.sort(function(a, b) { return (order[a.verdict] || 0) - (order[b.verdict] || 0); });
      recEl.innerHTML = groups.map(buildGroupCard).join('');
    }
  }

  /* ── Similarity matrix ───────────────────────────────────────── */

  function scoreToColor(s) {
    return 'hsl(' + (s * 120).toFixed(0) + ',65%,' + (88 - s * 18).toFixed(0) + '%)';
  }

  function buildMatrix(pairs, names, criterion) {
    var lookup = {};
    pairs.forEach(function(p) {
      lookup[p.report_a + '||' + p.report_b] = p;
      lookup[p.report_b + '||' + p.report_a] = p;
    });

    var header = '<tr><th></th>' + names.map(function(n) {
      return '<th class="mat-head">' + _esc(n) + '</th>';
    }).join('') + '</tr>';

    var rows = names.map(function(rowName, ri) {
      var cells = names.map(function(colName, ci) {
        if (ri === ci) return '<td class="score-cell diagonal">—</td>';
        var key = rowName + '||' + colName;
        var pair = lookup[key];
        if (!pair) return '<td class="score-cell">·</td>';
        /* Support both new per-dimension scores and legacy flat score field */
        var scores = pair.scores || {};
        var val = typeof scores[criterion] === 'number' ? scores[criterion]
                : typeof scores.overall   === 'number' ? scores.overall
                : (typeof pair.score === 'number'      ? pair.score : 0);
        return '<td class="score-cell" style="background:' + scoreToColor(val) + '" ' +
               'data-pair="' + _esc(key) + '" tabindex="0">' + val.toFixed(2) + '</td>';
      }).join('');
      return '<tr><td class="mat-label">' + _esc(rowName) + '</td>' + cells + '</tr>';
    }).join('');

    return '<thead>' + header + '</thead><tbody>' + rows + '</tbody>';
  }

  function wireTooltips(tableEl, pairs) {
    var lookup = {};
    pairs.forEach(function(p) {
      lookup[p.report_a + '||' + p.report_b] = p;
      lookup[p.report_b + '||' + p.report_a] = p;
    });

    tableEl.addEventListener('mouseover', function(e) {
      var cell = e.target.closest('[data-pair]');
      if (!cell) { hide(tooltip); return; }
      var pair = lookup[cell.dataset.pair];
      if (!pair) return;
      if (_activeCriterion === 'overall') {
        tooltip.textContent = pair.reason || '';
      } else {
        var scores = pair.scores || {};
        var val = typeof scores[_activeCriterion] === 'number' ? scores[_activeCriterion].toFixed(2) : '—';
        tooltip.textContent = _criterionLabel(_activeCriterion) + ': ' + val;
      }
      var rect = cell.getBoundingClientRect();
      tooltip.style.left  = (rect.left + window.scrollX) + 'px';
      tooltip.style.top   = (rect.bottom + window.scrollY + 6) + 'px';
      tooltip.style.display = 'block';
    });

    tableEl.addEventListener('mouseleave', function() { hide(tooltip); });
  }

  function wireMatrixTabs(tableEl, pairs) {
    var tabsEl = document.getElementById('matrixTabs');
    if (!tabsEl) return;
    tabsEl.addEventListener('click', function(e) {
      var btn = e.target.closest('.matrix-tab');
      if (!btn) return;
      var criterion = btn.dataset.criterion;
      if (criterion === _activeCriterion) return;
      _activeCriterion = criterion;
      tabsEl.querySelectorAll('.matrix-tab').forEach(function(t) {
        t.classList.toggle('active', t === btn);
      });
      tableEl.innerHTML = buildMatrix(_currentPairs, _currentNames, criterion);
    });
  }

  function _criterionLabel(k) {
    var labels = {
      overall: 'Overall', business_scope: 'Business Scope',
      data_model: 'Data Model', measures_kpis: 'Measures & KPIs',
      visual_structure: 'Visual Structure', target_audience: 'Target Audience',
    };
    return labels[k] || k;
  }

  /* ── Recommendation cards ────────────────────────────────────── */

  function buildGroupCard(group) {
    var verdictLabel = { merge: 'MERGE', keep_separate: 'KEEP SEPARATE', borderline: 'BORDERLINE' };
    var cls = group.verdict === 'merge' ? 'merge'
            : group.verdict === 'borderline' ? 'borderline' : 'separate';

    var chips = (group.reports || []).map(function(n) {
      return '<span class="comparison-chip">' + _esc(n) + '</span>';
    }).join('');

    var sharedHtml = '';
    if ((group.shared || []).length > 0) {
      sharedHtml = '<div class="rec-section"><div class="rec-section-label">In common</div>' +
        '<ul class="rec-list">' + group.shared.map(function(s) {
          return '<li>' + _esc(s) + '</li>';
        }).join('') + '</ul></div>';
    }

    var diffHtml = '';
    if ((group.differences || []).length > 0) {
      diffHtml = '<div class="rec-section"><div class="rec-section-label">Differences</div>' +
        '<ul class="rec-list">' + group.differences.map(function(d) {
          return '<li>' + _esc(d) + '</li>';
        }).join('') + '</ul></div>';
    }

    var actionHtml = '';
    if (group.merge_action) {
      actionHtml = '<div class="merge-action-box">' +
        '<div class="rec-section-label">How to merge</div>' +
        '<p>' + _esc(group.merge_action) + '</p></div>';
    }

    var reasonHtml = group.reason
      ? '<div class="rec-section"><div class="rec-section-label">Rationale</div><p>' + _esc(group.reason) + '</p></div>'
      : '';

    return '<div class="rec-card ' + cls + '">' +
      '<div class="rec-card-header">' +
        '<span class="rec-verdict-label">' + (verdictLabel[group.verdict] || group.verdict) + '</span>' +
        '<span class="comparison-chips">' + chips + '</span>' +
      '</div>' +
      sharedHtml + diffHtml + actionHtml + reasonHtml +
    '</div>';
  }

  /* ── Helpers ─────────────────────────────────────────────────── */

  function showError(msg) {
    hide(runningEl); hide(resultsEl);
    if (errorMsgEl) errorMsgEl.textContent = msg;
    show(errorEl);
  }

  function show(el) { if (el) el.style.display = ''; }
  function hide(el) { if (el) el.style.display = 'none'; }

  function _esc(s) {
    var d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  function _fmtDate(iso) {
    if (!iso) return '—';
    var d = new Date(iso);
    return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  }
}
