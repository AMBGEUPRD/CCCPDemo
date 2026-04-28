/* results-generate.js — PBIX pipeline generation page */

/* Load session from sessionStorage or server — shows error if missing */
(async function() {
  try {
  if (!(await loadSession())) {
    document.getElementById('errorState').classList.add('on');
    return;
  }

  document.getElementById('generateContent').style.display = 'flex';

  /* Populate header from session */
  var dt    = new Date(session.timestamp);
  var dtStr = dt.toLocaleDateString('en-GB', {day:'2-digit',month:'short',year:'numeric'})
            + ' \u00B7 ' + dt.toLocaleTimeString('en-GB', {hour:'2-digit',minute:'2-digit'});
  var hdrEl = document.getElementById('genPageTitle');
  if (hdrEl) hdrEl.textContent = session.filename || 'Power BI Migration';
  var metaEl = document.getElementById('genMeta');
  if (metaEl) metaEl.textContent = '\u{1F550} ' + dtStr + '  \u00B7  \u{1F4C4} ' + (session.filename || '');

  /* Resolve run_id from session (stored by index.html or restore endpoint) */
  var params = new URLSearchParams(location.search);
  var resultId = params.get('id') || session.id;
  var runId = (session && session.run_id) || null;
  if (!runId && resultId) {
    try { runId = sessionStorage.getItem('run_id_' + resultId); } catch(_) {}
  }

  /* Check TDD status from run manifest if we have a run_id */
  var workbookName = (session.filename || '').replace(/\.\w+$/, '');
  var tddCached = false;
  var manifest = null;

  /* Show "Back to Project" link if navigated from project dashboard */
  var workbookParam = params.get('workbook');
  if (workbookParam) {
    var projLink = document.getElementById('backToProject');
    if (projLink) {
      projLink.href = '/project/' + encodeURIComponent(workbookParam);
      projLink.style.display = '';
    }
  }

  /* Fetch run manifest early so banner + TDD check can use it */
  if (runId) {
    try {
      var mResp = await fetch('/api/history/' + encodeURIComponent(workbookName) + '/' + encodeURIComponent(runId));
      if (mResp.ok) {
        manifest = await mResp.json();
        var tddStage = (manifest.stages || {}).target_technical_doc;
        if (tddStage && tddStage.status === 'completed') {
          tddCached = true;
        }
      }
    } catch(_) {}
  }

  /* Show force_stages banner if stages were requested for re-generation */
  var forceParam = params.get('force_stages');
  if (forceParam) {
    var stageLabels = {
      metadata_extractor: 'Metadata', functional_doc: 'Functional Doc',
      skeleton: 'Skeleton', target_technical_doc: 'TDD',
      semantic_model: 'Semantic Model', dax_measures: 'DAX Measures',
      report_visuals: 'Report Visuals', assembler: 'Assembly',
    };
    var stageUpstream = {
      metadata_extractor: [], functional_doc: ['metadata_extractor'],
      skeleton: [], target_technical_doc: ['metadata_extractor', 'functional_doc'],
      semantic_model: ['target_technical_doc'], dax_measures: ['target_technical_doc'],
      report_visuals: ['target_technical_doc'],
      assembler: ['skeleton', 'semantic_model', 'dax_measures', 'report_visuals'],
    };
    var stages = forceParam.split(',').filter(Boolean);
    // Compute transitive downstream — only include a stage if ALL its
    // upstreams are satisfied (completed in manifest, in force set, or
    // already added as downstream).
    var satisfied = {};
    stages.forEach(function(s) { satisfied[s] = true; });
    // Stages with no upstreams are auto-run by the backend when needed
    for (var ds in stageUpstream) {
      if (stageUpstream[ds].length === 0) satisfied[ds] = true;
    }
    // Mark completed stages from manifest (if available)
    if (manifest && manifest.stages) {
      for (var mk in manifest.stages) {
        var stageObj = manifest.stages[mk];
        if ((stageObj && stageObj.status === 'completed') || stageObj === 'completed') {
          satisfied[mk] = true;
        }
      }
    }
    var downstreamSet = {};
    var changed = true;
    while (changed) {
      changed = false;
      for (var sn in stageUpstream) {
        if (downstreamSet[sn] || satisfied[sn]) continue;
        var ups = stageUpstream[sn];
        if (ups.length === 0) continue;
        var allMet = ups.every(function(u) { return !!satisfied[u]; });
        if (!allMet) continue;
        var triggered = ups.some(function(u) { return stages.indexOf(u) !== -1 || !!downstreamSet[u]; });
        if (triggered) {
          downstreamSet[sn] = true;
          satisfied[sn] = true;
          changed = true;
        }
      }
    }
    var downstreamNames = Object.keys(downstreamSet).map(function(s) { return stageLabels[s] || s; });

    var names = stages.map(function(s) { return stageLabels[s] || s; });
    var bannerText = 'Re-generating: ' + names.join(', ');
    if (downstreamNames.length > 0) {
      bannerText += ' \u2192 also triggers: ' + downstreamNames.join(', ');
    }
    var banner = document.createElement('div');
    banner.style.cssText = 'max-width:1100px;margin:0 auto;padding:8px 48px;font-size:12px;color:var(--amber);font-weight:600;display:flex;align-items:center;gap:6px';
    banner.innerHTML = '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 1l6 12H1L7 1z"/><path d="M7 5v3M7 10h.01"/></svg> ' +
      esc(bannerText);
    var main = document.querySelector('main');
    if (main) main.insertBefore(banner, main.firstChild);
  }

  // If force_stages includes functional_doc, run it first
  var forceSet = forceParam ? forceParam.split(',').filter(Boolean) : [];

  if (forceSet.indexOf('functional_doc') !== -1) {
    await runFunctionalDocGeneration(workbookName, resultId, runId);
  }

  // If force_stages includes target_technical_doc (or functional_doc which
  // invalidates TDD inputs), force TDD regeneration even if cached.
  if (forceSet.indexOf('target_technical_doc') !== -1 ||
      forceSet.indexOf('functional_doc') !== -1) {
    tddCached = false;
  }

  if (tddCached) {
    showTddCached(workbookName, runId);
  } else {
    await startTddGeneration(workbookName, runId);
  }

  // When coming from the project dashboard (force_stages present),
  // auto-start the pipeline instead of waiting for user to click.
  if (forceParam) {
    var genBtn = document.getElementById('generateBtn');
    if (genBtn && !genBtn.disabled) {
      genBtn.click();
    }
  }

  } catch (err) { showRenderError(err); }
})();

// ======================================================
//  Functional Documentation re-generation (when forced)
// ======================================================

async function runFunctionalDocGeneration(workbookName, resultId, runId) {
  var loadingEl = document.getElementById('tddLoading');
  var titleEl = loadingEl ? loadingEl.querySelector('.tdd-loading-title') : null;
  var subEl = loadingEl ? loadingEl.querySelector('.tdd-loading-sub') : null;

  // Repurpose the TDD loading indicator for functional doc
  if (titleEl) titleEl.textContent = 'Generating Functional Documentation\u2026';
  if (subEl) subEl.textContent = 'The AI agent is analyzing worksheets, dashboards, and data sources.';

  var body = { workbook_name: workbookName };
  if (resultId) body.result_id = resultId;
  if (runId) body.run_id = runId;

  var resp = await fetch('/documentation-stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error('Functional doc generation failed: HTTP ' + resp.status);

  var reader = resp.body.getReader();
  var decoder = new TextDecoder();
  var buffer = '';
  var finalData = null;

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
      if (msg.state === 'complete') finalData = msg;
      if (msg.state === 'error') throw new Error(msg.message || 'Functional doc generation failed');
    }
  }

  if (!finalData) throw new Error('Functional doc stream ended without result');

  // Restore original TDD loading text
  if (titleEl) titleEl.textContent = 'Generating Technical Design Document\u2026';
  if (subEl) subEl.textContent = 'The AI agent is designing the Power BI data model, DAX measures, and report layout.';
}

// ======================================================
//  TDD cached state — show badge + regenerate button
// ======================================================

function showTddCached(workbookName, runId) {
  var loadingEl = document.getElementById('tddLoading');
  var readyEl   = document.getElementById('tddReady');
  var ctaEl     = document.getElementById('generateCta');

  if (loadingEl) loadingEl.style.display = 'none';
  if (readyEl) readyEl.style.display = 'flex';

  var subEl = document.getElementById('tddReadySub');
  if (subEl) subEl.textContent = '\u2713 Cached from previous run';

  document.getElementById('tddViewHtml').href = '/tdd/' + encodeURIComponent(workbookName) + '/html';
  document.getElementById('tddDownloadMd').href = '/tdd/' + encodeURIComponent(workbookName) + '/md';

  // Add a regenerate button
  var actionsEl = readyEl.querySelector('.tdd-ready-actions');
  if (actionsEl) {
    var regenBtn = document.createElement('button');
    regenBtn.className = 'fdd-action fdd-action--amber';
    regenBtn.innerHTML =
      '<svg viewBox="0 0 13 13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M1 1v4h4"/><path d="M3.51 8A5 5 0 1 0 2 5.5L1 5"/>' +
      '</svg> Regenerate TDD';
    regenBtn.addEventListener('click', function() {
      readyEl.style.display = 'none';
      if (loadingEl) loadingEl.style.display = 'flex';
      if (ctaEl) ctaEl.style.display = 'none';
      var assessmentEl = document.getElementById('migrationAssessment');
      if (assessmentEl) assessmentEl.style.display = 'none';
      startTddGeneration(workbookName, runId);
    });
    actionsEl.appendChild(regenBtn);
  }

  if (ctaEl) ctaEl.style.display = 'flex';
}

function resetTddPhaseIndicators() {
  var phase1Ind = document.getElementById('phase1Indicator');
  var phase2Ind = document.getElementById('phase2Indicator');

  if (phase1Ind) {
    phase1Ind.style.background = '#e5e7eb';
    phase1Ind.style.color = '#6b7280';
  }
  if (phase2Ind) {
    phase2Ind.style.background = '#e5e7eb';
    phase2Ind.style.color = '#6b7280';
  }
}

function setTddPhaseIndicators(phaseStep, isComplete) {
  var phase1Ind = document.getElementById('phase1Indicator');
  var phase2Ind = document.getElementById('phase2Indicator');

  if (!phase1Ind || !phase2Ind) return;

  resetTddPhaseIndicators();

  if (phaseStep >= 1) {
    phase1Ind.style.background = phaseStep > 1 || isComplete ? '#10b981' : '#3b82f6';
    phase1Ind.style.color = 'white';
  }
  if (phaseStep >= 2) {
    phase2Ind.style.background = isComplete ? '#10b981' : '#3b82f6';
    phase2Ind.style.color = 'white';
  }
}

// ======================================================
//  TDD auto-generation on page load
// ======================================================

async function startTddGeneration(workbookName, runId) {
  var loadingEl = document.getElementById('tddLoading');
  var titleEl = loadingEl ? loadingEl.querySelector('.tdd-loading-title') : null;
  var subEl = loadingEl ? loadingEl.querySelector('.tdd-loading-sub') : null;
  var readyEl   = document.getElementById('tddReady');
  var ctaEl     = document.getElementById('generateCta');
  resetTddPhaseIndicators();
  if (subEl) {
    subEl.textContent = 'The AI agent is designing the Power BI data model, DAX measures, and report layout.';
  }

  try {
    var body = { workbook_name: workbookName };
    if (runId) body.run_id = runId;
    var resp = await fetch('/tdd-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);

    var reader = resp.body.getReader();
    var decoder = new TextDecoder();
    var buffer = '';
    var finalData = null;
    var currentPhase = null;

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
        if (msg.state === 'complete') finalData = msg;
        if (msg.state === 'error') throw new Error(msg.message || 'TDD generation failed');

        if (msg.state === 'running' && msg.phase) {
          if (msg.phase !== currentPhase) {
            currentPhase = msg.phase;
            var phaseStep = msg.phase_step;
            if (!phaseStep && (msg.phase.includes('1/2') || msg.phase.includes('Data Model'))) {
              phaseStep = 1;
            } else if (!phaseStep && (msg.phase.includes('2/2') || msg.phase.includes('Report Design'))) {
              phaseStep = 2;
            }
            if (phaseStep) setTddPhaseIndicators(phaseStep, false);
          }

          if (subEl) subEl.textContent = msg.phase;
        }
      }
    }

    if (!finalData) throw new Error('TDD stream ended without result');

    // Show TDD ready state
  setTddPhaseIndicators(2, true);
    if (loadingEl) loadingEl.style.display = 'none';
    if (readyEl) readyEl.style.display = 'flex';

    // Set TDD doc links
    var tddData = finalData.tdd || {};
    var subText = tddData.tables + ' tables, ' + tddData.measures + ' measures, ' + tddData.pages + ' pages';
    var subEl = document.getElementById('tddReadySub');
    if (subEl) subEl.textContent = '\u2713 ' + subText;

    document.getElementById('tddViewHtml').href = '/tdd/' + encodeURIComponent(workbookName) + '/html';
    document.getElementById('tddDownloadMd').href = '/tdd/' + encodeURIComponent(workbookName) + '/md';

    // Show migration assessment if available
    if (tddData.migration_assessment) {
      renderMigrationAssessment(tddData.migration_assessment);
    }

    // Show generate button
    if (ctaEl) ctaEl.style.display = 'flex';

  } catch (err) {
    if (loadingEl) {
      loadingEl.innerHTML =
        '<div style="color:var(--red);font-weight:600">\u2717 TDD generation failed</div>' +
        '<div style="font-size:13px;color:var(--muted)">' + esc(err.message) + '</div>' +
        '<button class="btn-generate" onclick="startTddGeneration(\'' + esc(workbookName) + '\')" style="margin-top:12px;font-size:14px;padding:10px 24px">' +
        'Retry TDD Generation</button>';
    }
  }
}

function renderMigrationAssessment(assessment) {
  var container = document.getElementById('migrationAssessment');
  var body = document.getElementById('assessmentBody');
  if (!container || !body || !assessment) return;

  // Support both array and object shapes
  var warnings = [];
  if (Array.isArray(assessment)) {
    warnings = assessment;
  } else if (assessment.warnings) {
    warnings = assessment.warnings;
  } else if (assessment.items) {
    warnings = assessment.items;
  }

  if (warnings.length === 0) {
    body.innerHTML = '<div style="padding:16px 20px;font-size:13px;color:var(--green);font-weight:600">\u2713 No migration warnings detected</div>';
  } else {
    var html = '<div style="padding:12px 20px;display:flex;flex-direction:column;gap:8px">';
    warnings.forEach(function(w) {
      var severity = (w.severity || w.level || 'info').toLowerCase();
      var pillClass = severity === 'high' ? 'warn' : severity === 'medium' ? 'dim' : 'string';
      html += '<div style="display:flex;align-items:flex-start;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)">';
      html += '<span class="pill ' + pillClass + '" style="flex-shrink:0">' + esc(severity) + '</span>';
      html += '<span style="font-size:13px;color:var(--ink2)">' + esc(w.message || w.description || JSON.stringify(w)) + '</span>';
      html += '</div>';
    });
    html += '</div>';
    body.innerHTML = html;
  }

  container.style.display = 'block';
}

// ======================================================
//  PBIX Generation pipeline (5 steps, no TDD)
// ======================================================
const PIPELINE_STEPS = [
  { key:'semantic',  id:'pbip_semantic_model_generator', label:'Semantic Model Generator',   elId:'ps-semantic',  statusId:'pss-semantic',  checkId:'psc-semantic' },
  { key:'dax',       id:'pbip_dax_generator',            label:'DAX Generator',              elId:'ps-dax',       statusId:'pss-dax',       checkId:'psc-dax' },
  { key:'visuals',   id:'pbip_visuals_generator',        label:'Visuals Generator',          elId:'ps-visuals',   statusId:'pss-visuals',   checkId:'psc-visuals' },
  { key:'assembler', id:'pbip_project_assembler',        label:'Project Assembler',          elId:'ps-assembler', statusId:'pss-assembler', checkId:'psc-assembler' },
];

/* Pipeline connector elements between steps */
const PIPELINE_CONNECTORS = [
  document.getElementById('pmc-0'),
  document.getElementById('pmc-1'),
  document.getElementById('pmc-2'),
];

const AGENT_ICONS = {
  pbip_project_skeleton:         '\u{1F3D7}\uFE0F',
  pbip_semantic_model_generator: '\u{1F9E0}',
  pbip_dax_generator:            '\u{1F4CA}',
  pbip_visuals_generator:        '\u{1F4C8}',
  pbip_project_assembler:        '\u{1F4E6}',
};


const logConsole = document.getElementById('logConsole');

function appendLog(level, message) {
  const line = document.createElement('div');
  line.className = 'log-line ' + level;
  line.textContent = message;
  logConsole.appendChild(line);
  logConsole.scrollTop = logConsole.scrollHeight;
}


function setStepState(step, state, statusText) {
  const el     = document.getElementById(step.elId);
  const status = document.getElementById(step.statusId);
  const check  = document.getElementById(step.checkId);
  if (!el) return;
  el.classList.remove('active','done','error');
  if (state === 'active') {
    el.classList.add('active');
    var stepIdx = PIPELINE_STEPS.findIndex(function(s) { return s.elId === step.elId; });
    status.textContent = statusText || 'Running\u2026 (' + (stepIdx + 1) + '/' + PIPELINE_STEPS.length + ')';
    check.textContent  = '\u2026';
  } else if (state === 'done') {
    el.classList.add('done');
    status.textContent = statusText || 'Completed \u2713';
    check.textContent  = '\u2713';
  } else if (state === 'error') {
    el.classList.add('error');
    status.textContent = statusText || 'Failed \u2717';
    check.textContent  = '\u2717';
  } else {
    status.textContent = 'Waiting\u2026';
    check.textContent  = '\u2013';
  }
}

/* Fill vertical connector line when a step completes */
function fillConnectorAfterStep(stepIdx) {
  /* Connector index i sits between step i and step i+1 */
  if (stepIdx >= 0 && stepIdx < PIPELINE_CONNECTORS.length) {
    var conn = PIPELINE_CONNECTORS[stepIdx];
    if (conn) {
      conn.style.height = '16px';
      conn.classList.add('filled');
    }
  }
}


function setProgress(done, total) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  document.getElementById('pmFill').style.width = pct + '%';
  document.getElementById('pmLabel').textContent = done + ' / ' + total + ' agents completed (' + pct + '%)';
}

function renderPbixResults(data) {
  const results = data.pipeline_results || [];
  const status  = data.status || 'error';

  // Header badge
  const badge = document.getElementById('pbixStatusBadge');
  if (status === 'ok') {
    badge.textContent = '\u2713 All agents completed';
    badge.className   = 'pbix-status-badge ok';
  } else if (status === 'partial') {
    badge.textContent = '\u26A0 Partial success';
    badge.className   = 'pbix-status-badge partial';
  } else {
    badge.textContent = '\u2717 Failed';
    badge.className   = 'pbix-status-badge error';
  }

  // Agent result cards
  const container = document.getElementById('agentCards');
  container.innerHTML = '';
  results.forEach((r, idx) => {
    const isOk   = r.status === 'ok';
    const icon   = AGENT_ICONS[r.agent_id] || '\u{1F916}';
    const card   = document.createElement('div');
    card.className = `agent-card ${r.status}`;
    card.innerHTML = `
      <div class="agent-card-header" onclick="toggleAgentCard(this)">
        <div class="agent-card-num">${idx + 1}</div>
        <div class="agent-card-name">${esc(r.agent_label)}</div>
        <span class="agent-card-status">${isOk ? '\u2713 Success' : '\u2717 Error'}</span>
        <span class="agent-card-chevron">\u25BC</span>
      </div>
      <div class="agent-card-body">
        <div class="agent-card-pre">${esc(r.result || '\u2014')}</div>
      </div>
    `;
    // Auto-open first failed card
    if (!isOk) card.classList.add('open');
    container.appendChild(card);
  });

  document.getElementById('pbixResults').classList.add('on');
  document.getElementById('generateCta').style.display = 'none';
  document.getElementById('pbixResults').scrollIntoView({ behavior:'smooth', block:'start' });
}

function toggleAgentCard(header) {
  const card = header.closest('.agent-card');
  card.classList.toggle('open');
}

/* Sub-agent event handler — renders page-level progress for the
   Visuals Generator step in the pipeline overlay. */
function handleSubAgentEvent(msg) {
  var panel = document.getElementById('subAgentPanel');
  var container = document.getElementById('subAgentPages');
  if (!panel || !container) return;

  // Show the sub-agent panel when we get the first event.
  panel.style.display = 'block';

  var pageIdx  = msg.page_index;
  var pageId   = 'sa-page-' + pageIdx;
  var existing = document.getElementById(pageId);

  if (msg.state === 'running') {
    if (!existing) {
      var el = document.createElement('div');
      el.id = pageId;
      el.className = 'sa-page running';
      el.innerHTML =
        '<div class="sa-dot"></div>' +
        '<span class="sa-name">' + esc(msg.page_name || 'Page ' + (pageIdx + 1)) + '</span>' +
        '<span class="sa-status">' + (pageIdx + 1) + '/' + msg.page_total + ' Running\u2026</span>';
      container.appendChild(el);
    }
    // Update the visuals step status to show sub-progress.
    var status = document.getElementById('pss-visuals');
    if (status) {
      status.textContent = 'Page ' + (pageIdx + 1) + '/' + msg.page_total + ': ' + (msg.page_name || '');
    }
  } else if (msg.state === 'done') {
    if (existing) {
      existing.className = 'sa-page done';
      var statusSpan = existing.querySelector('.sa-status');
      if (statusSpan) {
        statusSpan.textContent = (msg.visuals_count || 0) + ' visuals \u2713';
      }
    }
  } else if (msg.state === 'error') {
    if (existing) {
      existing.className = 'sa-page error';
      var statusSpan = existing.querySelector('.sa-status');
      if (statusSpan) {
        statusSpan.textContent = 'Failed \u2717';
      }
    }
  }

  // Auto-scroll sub-agent panel.
  container.scrollTop = container.scrollHeight;
}

document.getElementById('generateBtn').addEventListener('click', async () => {
  const btn = document.getElementById('generateBtn');
  btn.disabled = true;

  /* Resolve run_id */
  var params = new URLSearchParams(location.search);
  var resultId = params.get('id') || (session && session.id);
  var runId = (session && session.run_id) || null;
  if (!runId && resultId) {
    try { runId = sessionStorage.getItem('run_id_' + resultId); } catch(_) {}
  }

  // Reset all steps to visible + waiting
  PIPELINE_STEPS.forEach(s => {
    const el = document.getElementById(s.elId);
    if (el) el.style.display = '';
    setStepState(s, 'waiting');
  });
  PIPELINE_CONNECTORS.forEach(c => { if (c) { c.style.display = ''; c.style.height = '0'; c.classList.remove('filled'); } });
  setProgress(0, PIPELINE_STEPS.length);
  logConsole.innerHTML = '';
  // Reset sub-agent panel
  var subPanel = document.getElementById('subAgentPanel');
  if (subPanel) subPanel.style.display = 'none';
  var subPages = document.getElementById('subAgentPages');
  if (subPages) subPages.innerHTML = '';
  document.getElementById('pipelineOverlay').classList.add('on');

  // Map agent_id -> PIPELINE_STEPS index for fast lookup
  const stepByAgent = {};
  PIPELINE_STEPS.forEach((s, i) => { stepByAgent[s.id] = i; });

  let doneCount = 0;
  let visibleTotal = PIPELINE_STEPS.length;  // shrinks as skipped steps are hidden

  try {
    var requestBody = {
      metadata_json: JSON.stringify(analysis),
      twb_path: session.filename || '',
    };
    if (runId) requestBody.run_id = runId;

    // Read force_stages from URL query params (set by project dashboard)
    var forceParam = params.get('force_stages');
    if (forceParam) {
      requestBody.force_stages = forceParam.split(',').filter(Boolean);
    }

    // POST as JSON (not FormData) so the SSE endpoint can read request.json()
    const resp = await fetch('/generate-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    });
    if (!resp.ok) {
      const errText = await resp.text();
      throw new Error(errText || 'HTTP ' + resp.status);
    }

    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer    = '';
    let finalData = null;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE messages are delimited by double newlines
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);

        const dataLine = raw.split('\n').find(l => l.startsWith('data:'));
        if (!dataLine) continue;
        const jsonStr = dataLine.slice(5).trim();
        let msg;
        try { msg = JSON.parse(jsonStr); } catch { continue; }

        // Live log event
        if (msg.type === 'log') {
          appendLog(msg.level, msg.message);
          continue;
        }

        // Sub-agent progress event (page-level detail for visuals)
        if (msg.type === 'sub_agent') {
          handleSubAgentEvent(msg);
          appendLog('INFO', msg.message);
          continue;
        }

        // Final completion event
        if (msg.state === 'complete') {
          finalData = msg;
          continue;
        }

        // Per-agent progress events
        const idx = stepByAgent[msg.agent_id];
        if (idx === undefined) continue;

        if (msg.state === 'running') {
          setStepState(PIPELINE_STEPS[idx], 'active', 'Running\u2026');
        } else if (msg.state === 'skipped') {
          // Hide the skipped step and its preceding connector
          const stepEl = document.getElementById(PIPELINE_STEPS[idx].elId);
          if (stepEl) stepEl.style.display = 'none';
          // Hide connector that leads INTO this step (connector idx-1)
          if (idx > 0 && idx - 1 < PIPELINE_CONNECTORS.length) {
            const conn = PIPELINE_CONNECTORS[idx - 1];
            if (conn) conn.style.display = 'none';
          }
          visibleTotal--;
          setProgress(doneCount, visibleTotal);
        } else if (msg.state === 'done') {
          doneCount++;
          setStepState(PIPELINE_STEPS[idx], 'done', 'Completed \u2713');
          setProgress(doneCount, visibleTotal);
          fillConnectorAfterStep(idx);
        } else if (msg.state === 'error') {
          setStepState(PIPELINE_STEPS[idx], 'error',
            'Failed: ' + (msg.message || '').slice(0, 60));
          setProgress(doneCount, visibleTotal);
        }
      }
    }

    if (!finalData) throw new Error('Stream ended without a result');

    // Brief pause so the user sees the last step go green
    await new Promise(r => setTimeout(r, 600));
    document.getElementById('pipelineOverlay').classList.remove('on');
    renderPbixResults(finalData);

  } catch (err) {
    PIPELINE_STEPS.forEach(s => setStepState(s, 'error', 'Pipeline error'));
    await new Promise(r => setTimeout(r, 800));
    document.getElementById('pipelineOverlay').classList.remove('on');
    btn.disabled = false;
    alert('Generation failed: ' + err.message);
  }
});

