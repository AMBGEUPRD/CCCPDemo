/* project.js — Project dashboard logic */

/* ── Stage display config ── */
const STAGE_ORDER = [
  'metadata_extractor', 'functional_doc', 'target_technical_doc',
  'semantic_model', 'dax_measures', 'report_visuals', 'assembler',
];
const STAGE_LABELS = {
  metadata_extractor:   'Metadata Extraction',
  functional_doc:       'Functional Documentation',
  target_technical_doc: 'Technical Design Document',
  semantic_model:       'Semantic Model',
  dax_measures:         'DAX Measures',
  report_visuals:       'Report Visuals',
  assembler:            'Project Assembly',
};
const STATUS_ICONS = {
  completed:     '\u2713',
  failed:        '\u2717',
  not_attempted: '\u25CB',
  not_started:   '\u25CB',
  overwritten:   '\u25CB',
};

/**
 * Check whether all upstream dependencies of a stage are completed.
 * Uses the upstream list from the API (stages_full[name].upstream).
 */
function areUpstreamsMet(stageName, stages) {
  var info = stages[stageName];
  if (!info || !info.upstream) return true;
  for (var i = 0; i < info.upstream.length; i++) {
    var dep = info.upstream[i];
    var depInfo = stages[dep];
    if (!depInfo || depInfo.status !== 'completed') return false;
  }
  return true;
}

/**
 * Compute the transitive downstream set for one or more stages.
 * Only includes a downstream stage if ALL of its upstreams are
 * satisfied: already completed, in the checked set, or already
 * included in the downstream result.
 * Returns an array of stage names (not including the input stages).
 */
function getDownstream(stageNames, stages) {
  // Build the "satisfied" set: completed stages + user-selected stages
  // + stages with no upstreams (backend auto-runs them when needed)
  var satisfied = {};
  STAGE_ORDER.forEach(function(name) {
    var info = stages[name];
    if (info && info.status === 'completed') satisfied[name] = true;
  });
  // Include hidden stages (e.g. skeleton) that are completed or have no upstreams
  for (var sn in stages) {
    var si = stages[sn];
    if (si && (si.status === 'completed' || (si.upstream && si.upstream.length === 0))) {
      satisfied[sn] = true;
    }
  }
  stageNames.forEach(function(s) { satisfied[s] = true; });

  var result = {};
  var changed = true;
  // Iterate until no new stages are added (fixed-point)
  while (changed) {
    changed = false;
    STAGE_ORDER.forEach(function(name) {
      if (result[name] || satisfied[name]) return;
      var info = stages[name];
      if (!info || !info.upstream || info.upstream.length === 0) return;
      // Check if ALL upstreams of this stage are satisfied
      var allMet = true;
      for (var i = 0; i < info.upstream.length; i++) {
        if (!satisfied[info.upstream[i]]) { allMet = false; break; }
      }
      if (allMet) {
        // At least one upstream must be in the re-run set (checked or downstream)
        var triggered = false;
        for (var j = 0; j < info.upstream.length; j++) {
          var dep = info.upstream[j];
          if (stageNames.indexOf(dep) !== -1 || result[dep]) { triggered = true; break; }
        }
        if (triggered) {
          result[name] = true;
          satisfied[name] = true;
          changed = true;
        }
      }
    });
  }
  return Object.keys(result);
}

var workbookName = '';
var currentRun = null;
var allRuns = [];


(async function init() {
  // Extract workbook name from URL: /project/{workbook_name}
  var match = location.pathname.match(/^\/project\/(.+)$/);
  if (!match) { showError('Invalid project URL'); return; }
  workbookName = decodeURIComponent(match[1]);

  document.getElementById('projectTitle').textContent = workbookName;
  document.title = workbookName + ' — BIM-AI Project';

  try {
    await loadProject();
  } catch (err) {
    showError('Failed to load project: ' + err.message);
  }
})();


async function loadProject() {
  var resp = await fetch('/api/history/' + encodeURIComponent(workbookName));
  if (!resp.ok) throw new Error('HTTP ' + resp.status);
  allRuns = await resp.json();
  if (!allRuns || allRuns.length === 0) { showError('No runs found'); return; }

  // Auto-restore latest run so result_id is available for navigation
  currentRun = allRuns[0];
  try {
    var restoreResp = await fetch(
      '/api/history/' + encodeURIComponent(workbookName) + '/' +
      encodeURIComponent(currentRun.run_id) + '/restore',
      { method: 'POST' }
    );
    if (restoreResp.ok) {
      var restoreData = await restoreResp.json();
      currentRun._result_id = restoreData.result_id;
      currentRun._run_id = restoreData.run_id;
    }
  } catch (_) { /* non-critical */ }

  renderHeader();
  renderPipeline();
  renderActions();
  renderRunHistory();
}


function renderHeader() {
  var ext = (currentRun.workbook_file || '').split('.').pop() || '?';
  document.getElementById('projectExt').textContent =
    currentRun.source_format === 'pbip' ? '.ZIP / PBIP' : '.' + ext.toUpperCase();

  var dt = new Date(currentRun.updated_at || currentRun.created_at);
  var dtStr = dt.toLocaleDateString('en-GB', {day:'2-digit', month:'short', year:'numeric'})
            + ' \u00B7 ' + dt.toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit'});
  document.getElementById('projectDate').textContent = dtStr;

  var badge = document.getElementById('projectStatus');
  var completed = 0;
  var visible = 0;
  var stages = currentRun.stages_full || {};
  for (var k in stages) {
    if (k === 'skeleton') continue; // hidden from dashboard
    visible++;
    if (stages[k].status === 'completed') completed++;
  }
  var hasFailed = Object.values(stages).some(function(s) { return s.status === 'failed'; });
  var status = hasFailed ? 'failed' : (completed >= visible ? 'complete' : 'in_progress');
  var pct = visible > 0 ? Math.round(completed / visible * 100) : 0;
  var labels = { complete: 'Complete', in_progress: 'In Progress', failed: 'Failed' };
  badge.textContent = labels[status] + ' \u2014 ' + pct + '%';
  badge.className = 'project-badge ' + status;
}


function renderPipeline() {
  var container = document.getElementById('pipelineGrid');
  container.innerHTML = '';
  var stages = currentRun.stages_full || {};
  var isPbip = currentRun.source_format === 'pbip';

  STAGE_ORDER.forEach(function(name) {
    var info = stages[name] || { status: 'not_attempted', deterministic: false };
    var card = document.createElement('div');
    card.className = 'stage-card ' + info.status;

    var icon = STATUS_ICONS[info.status] || '\u25CB';
    var isLLM = !info.deterministic;

    var html = '<div class="stage-name">';
    html += '<span class="stage-icon ' + info.status + '">' + icon + '</span>';
    html += esc(STAGE_LABELS[name] || name);
    html += '</div>';

    // Type tag
    html += '<div style="margin-top:4px">';
    if (isLLM) {
      html += '<span class="stage-tag llm">LLM</span>';
    } else {
      html += '<span class="stage-tag auto">Auto</span>';
    }
    html += '</div>';

    // Details
    if (info.status === 'completed') {
      html += '<div class="stage-details">';
      if (info.duration_seconds != null) {
        html += '<span>' + info.duration_seconds.toFixed(1) + 's</span>';
      }
      if (info.input_tokens || info.output_tokens) {
        var tokens = (info.input_tokens || 0) + (info.output_tokens || 0);
        html += '<span>' + tokens.toLocaleString() + ' tokens</span>';
      }
      html += '</div>';
    }

    // Re-run checkbox: disabled if upstream deps not met
    var upstreamOk = areUpstreamsMet(name, stages);
    var disabledAttr = (upstreamOk && !isPbip) ? '' : ' disabled';
    var title = isPbip
      ? 'PBIP runs are analyze-only in v1'
      : (upstreamOk
        ? 'Select for re-generation'
        : 'Cannot re-run: upstream stages not completed (' +
          (info.upstream || []).filter(function(d) {
            var ds = stages[d]; return !ds || ds.status !== 'completed';
          }).map(function(d) { return STAGE_LABELS[d] || d; }).join(', ') + ')');
    html += '<input type="checkbox" class="stage-checkbox" data-stage="' + name + '"' +
      disabledAttr + ' title="' + esc(title) + '">';

    card.innerHTML = html;
    container.appendChild(card);
  });

  // Update re-generate button state when checkboxes change
  container.addEventListener('change', updateRegenButton);
}


function updateRegenButton() {
  if (currentRun && currentRun.source_format === 'pbip') {
    var pbipBtn = document.getElementById('btnRegen');
    var pbipBanner = document.getElementById('forceBanner');
    pbipBtn.disabled = true;
    pbipBtn.textContent = 'Unavailable for PBIP';
    pbipBanner.style.display = 'none';
    return;
  }
  var checked = getCheckedStages();
  var stages = currentRun.stages_full || {};
  var btn = document.getElementById('btnRegen');
  var banner = document.getElementById('forceBanner');
  if (checked.length > 0) {
    var downstream = getDownstream(checked, stages);
    // Filter downstream to only stages not already selected
    var extra = downstream.filter(function(s) { return checked.indexOf(s) === -1; });
    var totalCount = checked.length + extra.length;
    btn.disabled = false;
    btn.textContent = 'Re-generate ' + totalCount + ' stage' + (totalCount > 1 ? 's' : '');
    banner.style.display = 'block';
    var text = 'Will re-run: ' + checked.map(function(s) { return STAGE_LABELS[s]; }).join(', ');
    if (extra.length > 0) {
      text += ' \u2192 also triggers: ' + extra.map(function(s) { return STAGE_LABELS[s]; }).join(', ');
    }
    banner.textContent = text;
  } else {
    btn.disabled = true;
    btn.textContent = 'Re-generate Selected';
    banner.style.display = 'none';
  }
}

function getCheckedStages() {
  var boxes = document.querySelectorAll('.stage-checkbox:checked');
  return Array.from(boxes).map(function(cb) { return cb.dataset.stage; });
}


function renderActions() {
  // View Report button
  var btnReport = document.getElementById('btnReport');
  var stages = currentRun.stages_full || {};
  var metadataDone = stages.metadata_extractor && stages.metadata_extractor.status === 'completed';
  btnReport.disabled = !metadataDone;
  btnReport.onclick = function() {
    if (currentRun._result_id) {
      window.location.href = '/results?id=' + encodeURIComponent(currentRun._result_id) +
        '&workbook=' + encodeURIComponent(workbookName);
    }
  };

  // Re-generate button
  var btnRegen = document.getElementById('btnRegen');
  btnRegen.disabled = currentRun.source_format === 'pbip';
  btnRegen.textContent = currentRun.source_format === 'pbip' ? 'Unavailable for PBIP' : 'Re-generate Selected';
  btnRegen.onclick = function() {
    if (currentRun.source_format === 'pbip') return;
    var checked = getCheckedStages();
    if (checked.length === 0) return;
    var url = '/generate?id=' + encodeURIComponent(currentRun._result_id || '') +
      '&force_stages=' + encodeURIComponent(checked.join(',')) +
      '&workbook=' + encodeURIComponent(workbookName);
    window.location.href = url;
  };

  // Download button
  var btnDownload = document.getElementById('btnDownload');
  btnDownload.disabled = !currentRun.download_available || currentRun.source_format === 'pbip';
  btnDownload.onclick = function() {
    if (currentRun.source_format === 'pbip') return;
    window.location.href = '/api/history/' + encodeURIComponent(workbookName) + '/' +
      encodeURIComponent(currentRun.run_id) + '/download';
  };

  // Document links (FDD + TDD)
  renderDocLinks(stages);
}


function renderDocLinks(stages) {
  var docsBar = document.getElementById('docsBar');
  if (currentRun.source_format === 'pbip') {
    docsBar.style.display = 'none';
    return;
  }
  var fddDone = stages.functional_doc && stages.functional_doc.status === 'completed';
  var tddDone = stages.target_technical_doc && stages.target_technical_doc.status === 'completed';

  if (!fddDone && !tddDone) {
    docsBar.style.display = 'none';
    return;
  }

  var wb = encodeURIComponent(workbookName);
  docsBar.style.display = '';

  // FDD card
  var fddCard = document.getElementById('docFddCard');
  if (fddDone) {
    fddCard.style.display = '';
    document.getElementById('docFddHtml').href = '/documentation/' + wb + '/html';
    document.getElementById('docFddMd').href = '/documentation/' + wb + '/md';
  } else {
    fddCard.style.display = 'none';
  }

  // TDD card
  var tddCard = document.getElementById('docTddCard');
  if (tddDone) {
    tddCard.style.display = '';
    document.getElementById('docTddHtml').href = '/tdd/' + wb + '/html';
    document.getElementById('docTddMd').href = '/tdd/' + wb + '/md';
  } else {
    tddCard.style.display = 'none';
  }
}


function renderRunHistory() {
  var container = document.getElementById('runsList');
  container.innerHTML = '';
  if (allRuns.length === 0) return;

  allRuns.forEach(function(run, idx) {
    var card = document.createElement('div');
    card.className = 'run-card' + (run.run_id === currentRun.run_id ? ' active' : '');

    var dt = new Date(run.created_at);
    var dtStr = dt.toLocaleDateString('en-GB', {day:'2-digit', month:'short', year:'numeric'})
              + ' \u00B7 ' + dt.toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit'});

    var pct = run.completion_pct || 0;

    card.innerHTML =
      '<div class="run-id">' + esc(run.run_id) + '</div>' +
      '<div class="run-date">' + dtStr + '</div>' +
      '<span class="run-completion">' + pct + '% complete</span>' +
      '<div class="run-actions">' +
        (run.download_available ? '<button class="action-btn download" style="padding:4px 12px;font-size:11px" data-run="' + esc(run.run_id) + '">Download</button>' : '') +
      '</div>';

    card.addEventListener('click', function(e) {
      if (e.target.tagName === 'BUTTON') {
        // Download click
        window.location.href = '/api/history/' + encodeURIComponent(workbookName) + '/' +
          encodeURIComponent(run.run_id) + '/download';
        return;
      }
      switchRun(run);
    });
    container.appendChild(card);
  });
}


async function switchRun(run) {
  try {
    var resp = await fetch(
      '/api/history/' + encodeURIComponent(workbookName) + '/' +
      encodeURIComponent(run.run_id) + '/restore',
      { method: 'POST' }
    );
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    var data = await resp.json();
    run._result_id = data.result_id;
    run._run_id = data.run_id;
    currentRun = run;
    renderHeader();
    renderPipeline();
    renderActions();
    renderRunHistory();
  } catch (err) {
    alert('Failed to switch run: ' + err.message);
  }
}


function showError(msg) {
  document.getElementById('projectContent').innerHTML =
    '<div style="text-align:center;padding:80px 48px;color:var(--muted)">' +
    '<div style="font-size:48px;margin-bottom:16px">\u26A0</div>' +
    '<div style="font-size:16px">' + esc(msg) + '</div>' +
    '<a href="/" style="display:inline-block;margin-top:24px;color:var(--violet);font-weight:600">\u2190 Back to Home</a>' +
    '</div>';
}


function esc(s) {
  var d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}
