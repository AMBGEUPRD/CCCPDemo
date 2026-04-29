/* ============================================================
   compare.js — Comparison result page
   ============================================================ */

/* Fixed rationalization dataset — always shown, regardless of API output */
var _FIXED_RATIONALIZATION = [
  // KEEP — high value, high usage
  { id:'A', name:'Weekly Sales Dashboard',       quadrant:'keep',   desc:'Core KPI tracker used daily by commercial teams.',          rationale:'Keep. Prioritise for migration.',              early_value: true  },
  { id:'B', name:'Promotional ROI Report',       quadrant:'keep',   desc:'Widely used by marketing. Informs trade spend decisions.',  rationale:'Keep. Add scenario-modelling layer.',          early_value: true  },
  { id:'C', name:'Outlet Execution Tracker',     quadrant:'keep',   desc:'Daily usage by field sales. Tracks POS compliance.',       rationale:'Keep. Automate data feed.',                    early_value: true  },
  { id:'D', name:'Market Share Report',          quadrant:'keep',   desc:'Monthly brand share vs competitors. Used by CMO.',         rationale:'Keep. Enrich with Nielsen feed.',              early_value: false },
  { id:'E', name:'Trade Spend Tracker',          quadrant:'keep',   desc:'Finance and commercial use weekly to manage accruals.',    rationale:'Keep. Link to P&L view.',                      early_value: false },
  { id:'F', name:'Distribution Coverage Map',    quadrant:'keep',   desc:'Visualises outlet reach across geographies.',              rationale:'Keep. Automate monthly refresh.',              early_value: false },
  // MERGE — low value, high usage
  { id:'G', name:'Channel Mix Report',           quadrant:'merge',  desc:'Overlaps heavily with Weekly Sales Dashboard.',            rationale:'Merge into Sales Dashboard.',                  early_value: false },
  { id:'H', name:'Brand Volume vs Target',       quadrant:'merge',  desc:'KPIs replicated across two other reports.',               rationale:'Consolidate into Brand Performance Pack.',     early_value: false },
  { id:'I', name:'SKU Velocity Report',          quadrant:'merge',  desc:'Overlaps with Outlet Execution Tracker.',                 rationale:'Merge via common data layer.',                 early_value: false },
  { id:'J', name:'Customer Segment Summary',     quadrant:'merge',  desc:'Segment breakdown duplicated in 3 other reports.',        rationale:'Merge into single customer view.',             early_value: false },
  { id:'K', name:'Retail Pricing Overview',      quadrant:'merge',  desc:'Price ladder data already inside Trade Spend Tracker.',   rationale:'Absorb into Trade Spend Tracker.',             early_value: false },
  // RETIRE — low value, low usage
  { id:'L', name:'Legacy NPD Pipeline',          quadrant:'retire', desc:'Outdated methodology, superseded by Stage-Gate tool.',    rationale:'Retire immediately.',                          early_value: false },
  { id:'M', name:'Monthly PDF Sales Brief',      quadrant:'retire', desc:'Manual static PDF. Users prefer live dashboards.',        rationale:'Retire. Direct users to live view.',           early_value: false },
  { id:'N', name:'Regional Cost-per-Case',       quadrant:'retire', desc:'Rarely accessed. Data embedded in variance reporting.',   rationale:'Decommission. Archive data model.',            early_value: false },
  { id:'O', name:'Annual Brand Health PDF',      quadrant:'retire', desc:'Printed deck, no interactivity, 18 months stale.',        rationale:'Retire. Replace with live Brand Health view.', early_value: false },
  { id:'P', name:'Salesperson Ranking Sheet',    quadrant:'retire', desc:'Manual Excel. Superseded by CRM leaderboard.',           rationale:'Retire. Use CRM output.',                      early_value: false },
  // ADD — high value, low usage
  { id:'Q', name:'Shopper Conversion Funnel',    quadrant:'add',    desc:'High demand from Category and Commercial teams.',         rationale:'Build. Prioritise in next sprint.',            early_value: false },
  { id:'R', name:'Media Attribution Report',     quadrant:'add',    desc:'Absent despite growing digital spend.',                   rationale:'Add. Integrate with media buying data.',       early_value: false },
  { id:'S', name:'Key Account Health Score',     quadrant:'add',    desc:'Requested by sales leadership for distributor tracking.', rationale:'Pilot with top 5 accounts.',                   early_value: false },
  { id:'T', name:'Digital Shelf Analytics',      quadrant:'add',    desc:'Needed to track e-com availability and content score.',   rationale:'Add. Source from retail media API.',           early_value: false },
  { id:'U', name:'Innovation Launch Tracker',    quadrant:'add',    desc:'No live view of NPD launch KPIs post-gate.',             rationale:'Add. Link to Stage-Gate milestones.',          early_value: false },
  { id:'V', name:'Consumer Sentiment Dashboard', quadrant:'add',    desc:'Social & survey data not yet integrated.',               rationale:'Add. Pilot with 2 key brands.',                early_value: false },
];

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

  /* ── Notes section wiring ────────────────────────────────────────── */
  var _notesFiles   = [];
  var notesZone     = document.getElementById('notesUploadZone');
  var notesInput    = document.getElementById('notesFileInput');
  var notesFileList = document.getElementById('notesFileList');
  var notesSaveBtn  = document.getElementById('notesSaveBtn');
  var notesSavedMsg = document.getElementById('notesSavedMsg');

  if (notesZone) {
    notesZone.addEventListener('click', function(e) {
      if (e.target.closest('.notes-file-remove')) return;
      notesInput && notesInput.click();
    });
    notesZone.addEventListener('dragover', function(e) {
      e.preventDefault(); notesZone.classList.add('drag-over');
    });
    notesZone.addEventListener('dragleave', function() {
      notesZone.classList.remove('drag-over');
    });
    notesZone.addEventListener('drop', function(e) {
      e.preventDefault(); notesZone.classList.remove('drag-over');
      addNotesFiles(Array.from(e.dataTransfer.files));
    });
  }
  if (notesInput) {
    notesInput.addEventListener('change', function() {
      addNotesFiles(Array.from(notesInput.files));
      notesInput.value = '';
    });
  }
  if (notesSaveBtn) { notesSaveBtn.addEventListener('click', saveNotes); }

  function addNotesFiles(files) {
    files.forEach(function(f) { _notesFiles.push(f); });
    renderNotesFileList();
  }

  function renderNotesFileList() {
    if (!notesFileList) return;
    notesFileList.innerHTML = _notesFiles.map(function(f, i) {
      return '<div class="notes-file-item">' +
        '<span class="notes-file-name">' + _esc(f.name) + '</span>' +
        '<span class="notes-file-size">(' + _fmtSize(f.size) + ')</span>' +
        '<button class="notes-file-remove" data-idx="' + i + '">×</button></div>';
    }).join('');
    notesFileList.querySelectorAll('.notes-file-remove').forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        _notesFiles.splice(parseInt(btn.dataset.idx), 1);
        renderNotesFileList();
      });
    });
  }

  function saveNotes() {
    if (notesSavedMsg) {
      notesSavedMsg.style.display = '';
      setTimeout(function() { notesSavedMsg.style.display = 'none'; }, 2500);
    }
  }

  function _fmtSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }

  /* ── Accordion toggle ────────────────────────────────────────────── */
  function initAccordions() {
    document.querySelectorAll('.cmp-accordion-header').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var item = btn.closest('.cmp-accordion-item');
        var body = btn.nextElementSibling;
        var isOpen = body.classList.contains('open');
        body.classList.toggle('open', !isOpen);
        btn.setAttribute('aria-expanded', String(!isOpen));
        if (!isOpen) {
          setTimeout(function() {
            item.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }, 50);
        }
      });
    });
  }

  initAccordions();

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
    if (titleEl) titleEl.textContent = 'Report Comparison — ' + date;
    if (breadCmp) breadCmp.textContent = 'Report Comparison ' + date;
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
        wireMatrixTabs(tableEl);
      }
    }

    /* KPI Glossary */
    var reportNames = Object.keys(result.profiles || {});
    renderKpiGlossary(result.kpi_glossary || [], reportNames);

    /* Rationalization Matrix — always uses the fixed dataset */
    renderRationalizationMatrix();

    /* Recommendation cards */
    var recEl = document.getElementById('recCards');
    if (recEl) {
      var groups = result.groups || [];
      var order = { merge: 0, borderline: 1, keep_separate: 2 };
      groups.sort(function(a, b) { return (order[a.verdict] || 0) - (order[b.verdict] || 0); });
      recEl.innerHTML = groups.map(buildGroupCard).join('');
    }
  }

  /* ── KPI Glossary ─────────────────────────────────────────────────── */

  function renderKpiGlossary(glossary, reportNames) {
    var section = document.getElementById('kpiSection');
    var tableEl = document.getElementById('kpiTable');
    if (!section || !tableEl || glossary.length === 0) return;

    var headerCells = '<th>KPI Name</th><th>Description</th>' +
      reportNames.map(function(n) { return '<th>' + _esc(n) + '</th>'; }).join('');

    var rows = glossary.map(function(entry) {
      var count = entry.reports.length;
      var countBadge = count > 0
        ? '<span class="kpi-count">' + count + '/' + reportNames.length + '</span>'
        : '';
      var reportCells = reportNames.map(function(n) {
        return entry.reports.indexOf(n) >= 0
          ? '<td class="kpi-check-cell"><span class="kpi-check">&#10003;</span></td>'
          : '<td></td>';
      }).join('');
      return '<tr><td>' + _esc(entry.name) + countBadge + '</td><td>' +
             _esc(entry.description) + '</td>' + reportCells + '</tr>';
    }).join('');

    tableEl.innerHTML = '<thead><tr>' + headerCells + '</tr></thead><tbody>' + rows + '</tbody>';
    section.style.display = '';
  }

  /* ── Rationalization Matrix ────────────────────────────────────────── */

  function renderRationalizationMatrix() {
    var section   = document.getElementById('rationSection');
    var matrixEl  = document.getElementById('rationMatrix');
    var legendEl  = document.getElementById('rationLegend');
    if (!section || !matrixEl) return;

    /* Always use the fixed dataset — API result is ignored for this section */
    var data = _FIXED_RATIONALIZATION;

    var W = 700, H = 600;
    var MX = W / 2, MY = H / 2;
    var MARGIN = 36;
    var CHIP_H = 28;
    var GAP_X  = 10;

    var bounds = {
      keep:   { x1: MX + 4, x2: W - 8,  y1: MARGIN,   y2: MY - 4 },
      merge:  { x1: 8,      x2: MX - 4, y1: MARGIN,   y2: MY - 4 },
      retire: { x1: 8,      x2: MX - 4, y1: MY + 4,   y2: H - MARGIN },
      add:    { x1: MX + 4, x2: W - 8,  y1: MY + 4,   y2: H - MARGIN },
    };

    function chipW(name) { return 18 + 5 + name.length * 6.3 + 18; }

    function layoutQuadrant(chips, b) {
      var availW = b.x2 - b.x1;
      var availH = b.y2 - b.y1;

      var rows = [];
      var remaining = chips.slice();
      while (remaining.length > 0) {
        var row = [], usedW = 0;
        for (var i = 0; i < remaining.length; i++) {
          var cw = chipW(remaining[i].name);
          var needed = usedW + (row.length > 0 ? GAP_X : 0) + cw;
          if (needed <= availW) { row.push(remaining[i]); usedW = needed; }
        }
        if (row.length === 0) { row.push(remaining[0]); usedW = chipW(remaining[0].name); }
        rows.push({ chips: row, usedW: usedW });
        var placed = {};
        row.forEach(function(c) { placed[c.id] = true; });
        remaining = remaining.filter(function(c) { return !placed[c.id]; });
      }

      var placed = [];
      rows.forEach(function(row, ri) {
        var py = b.y1 + (availH / (rows.length + 1)) * (ri + 1);
        var cx = b.x1 + (availW - row.usedW) / 2;
        row.chips.forEach(function(chip) {
          var cw = chipW(chip.name);
          var jx = (Math.random() - 0.5) * 12;
          var jy = (Math.random() - 0.5) * 8;
          var px = Math.max(b.x1 + cw / 2 + 2, Math.min(b.x2 - cw / 2 - 2, cx + cw / 2 + jx));
          var py2 = Math.max(b.y1 + CHIP_H / 2 + 2, Math.min(b.y2 - CHIP_H / 2 - 2, py + jy));
          placed.push({ chip: chip, x: px, y: py2 });
          cx += cw + GAP_X;
        });
      });
      return placed;
    }

    /* Group by quadrant */
    var quadrantChips = { keep: [], merge: [], retire: [], add: [] };
    data.forEach(function(r) {
      if (quadrantChips[r.quadrant]) quadrantChips[r.quadrant].push(r);
    });

    /* Clear previously rendered chips / circles */
    matrixEl.querySelectorAll('.ration-chip, .ration-ev-circle, .ration-ev-label').forEach(function(el) {
      el.remove();
    });

    var allPlaced = [];
    ['keep', 'merge', 'retire', 'add'].forEach(function(q) {
      layoutQuadrant(quadrantChips[q], bounds[q]).forEach(function(item) {
        allPlaced.push(item);
      });
    });

    /* Early-value circle — inserted BEFORE chips so chips (z-index:5) render on top */
    var evItems = allPlaced.filter(function(item) { return !!item.chip.early_value; });
    if (evItems.length > 0) {
      var cxEV = evItems.reduce(function(s, c) { return s + c.x; }, 0) / evItems.length;
      var cyEV = evItems.reduce(function(s, c) { return s + c.y; }, 0) / evItems.length;
      var radius = 0;
      evItems.forEach(function(c) {
        var d = Math.sqrt(Math.pow(c.x - cxEV, 2) + Math.pow(c.y - cyEV, 2));
        if (d > radius) radius = d;
      });
      radius = Math.max(radius + 34, 40);

      var circle = document.createElement('div');
      circle.className = 'ration-ev-circle';
      circle.style.cssText = 'left:' + (cxEV - radius) + 'px;top:' + (cyEV - radius) + 'px;' +
                             'width:' + (radius * 2) + 'px;height:' + (radius * 2) + 'px;';
      matrixEl.appendChild(circle);

      var evLabel = document.createElement('div');
      evLabel.className = 'ration-ev-label';
      evLabel.textContent = '⭐ Top 3 quick wins';
      evLabel.style.cssText = 'left:' + (cxEV - radius) + 'px;top:' + (cyEV - radius - 20) + 'px;';
      matrixEl.appendChild(evLabel);
    }

    /* Render chips */
    allPlaced.forEach(function(item) {
      var r = item.chip;
      var qwBadge = r.early_value
        ? '<span class="ration-qw-badge">⭐ Quick win</span>'
        : '';

      var el = document.createElement('div');
      el.className = 'ration-chip ration-q-' + r.quadrant;
      el.style.left = item.x + 'px';
      el.style.top  = item.y + 'px';
      el.innerHTML =
        '<span class="ration-chip-id">' + _esc(r.id) + '</span>' +
        '<span>' + _esc(r.name) + '</span>' +
        '<div class="ration-tooltip">' +
          qwBadge +
          '<strong>' + _esc(r.name) + '</strong>' +
          '<span class="ration-desc">' + _esc(r.desc) + '</span>' +
          '<span class="ration-action">→ ' + _esc(r.rationale) + '</span>' +
        '</div>';
      matrixEl.appendChild(el);
    });

    /* Legend */
    if (legendEl) {
      var legendQuadrants = [
        { key: 'keep', label: 'Keep' }, { key: 'merge', label: 'Merge' },
        { key: 'retire', label: 'Retire' }, { key: 'add', label: 'Add' },
      ];
      var legendHtml = legendQuadrants.map(function(q) {
        return '<div class="ration-legend-item">' +
          '<div class="ration-leg-dot ration-q-' + q.key + '"></div>' + q.label +
          '</div>';
      }).join('');
      legendHtml += '<div class="ration-legend-item">' +
        '<div style="width:12px;height:12px;border-radius:50%;border:2px dashed #C62828;flex-shrink:0"></div>' +
        'Quick win' +
        '</div>';
      legendEl.innerHTML = legendHtml;
    }

    section.style.display = '';
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

  function wireMatrixTabs(tableEl) {
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
