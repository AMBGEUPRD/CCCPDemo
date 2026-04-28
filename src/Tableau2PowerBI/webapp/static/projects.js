/* ============================================================
   projects.js — Project list page + Project detail page
   ============================================================ */

/* ── Utilities ──────────────────────────────────────────────────────────── */

function _escHtml(s) {
  var d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

function _fmtDate(iso) {
  if (!iso) return '—';
  var d = new Date(iso);
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
}

function _statusBadge(status) {
  var map = {
    pending:  { label: 'Pending',  color: 'var(--muted)',  bg: 'var(--lavender-l)' },
    running:  { label: 'Running',  color: 'var(--violet)', bg: 'var(--violet-l)' },
    complete: { label: 'Complete', color: 'var(--green)',  bg: 'var(--green-l)' },
    error:    { label: 'Error',    color: 'var(--rose)',   bg: 'var(--rose-l)' },
  };
  var s = map[status] || map.pending;
  return '<span class="status-badge" style="color:' + s.color + ';background:' + s.bg + '">' + s.label + '</span>';
}

/* ══════════════════════════════════════════════════════════════════════════
   PROJECTS LIST PAGE
   ══════════════════════════════════════════════════════════════════════════ */

function initProjectsPage() {
  var newBtn    = document.getElementById('newProjectBtn');
  var form      = document.getElementById('newProjForm');
  var input     = document.getElementById('projNameInput');
  var createBtn = document.getElementById('createProjBtn');
  var cancelBtn = document.getElementById('cancelProjBtn');
  var errEl     = document.getElementById('projFormErr');
  var grid      = document.getElementById('projGrid');
  var emptyEl   = document.getElementById('projEmpty');

  function showForm() {
    form.style.display = 'flex';
    input.value = '';
    errEl.style.display = 'none';
    input.focus();
  }
  function hideForm() { form.style.display = 'none'; }

  newBtn.addEventListener('click', showForm);
  cancelBtn.addEventListener('click', hideForm);
  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter')  createProject();
    if (e.key === 'Escape') hideForm();
  });
  createBtn.addEventListener('click', createProject);

  async function createProject() {
    var name = input.value.trim();
    if (!name) { showErr('Please enter a project name.'); return; }
    createBtn.disabled = true;
    errEl.style.display = 'none';
    try {
      var resp = await fetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name }),
      });
      if (!resp.ok) throw new Error(await resp.text() || 'HTTP ' + resp.status);
      var proj = await resp.json();
      window.location.href = '/projects/' + encodeURIComponent(proj.name);
    } catch (e) {
      showErr(e.message || 'Could not create project.');
      createBtn.disabled = false;
    }
  }

  function showErr(msg) { errEl.textContent = msg; errEl.style.display = 'inline'; }

  loadProjects();

  async function loadProjects() {
    try {
      var resp = await fetch('/api/projects');
      if (!resp.ok) return;
      var projects = await resp.json();
      grid.innerHTML = '';
      if (!projects || projects.length === 0) { emptyEl.style.display = 'flex'; return; }
      emptyEl.style.display = 'none';
      projects.forEach(function(p) {
        var totalReports = (p.reports || []).length;
        var doneCount    = (p.reports || []).filter(function(r) { return r.status === 'complete'; }).length;
        var hasRunning   = (p.reports || []).some(function(r) { return r.status === 'running'; });
        var hasError     = (p.reports || []).some(function(r) { return r.status === 'error'; });
        var projStatus   = hasRunning ? 'running'
          : hasError ? 'error'
          : (doneCount === totalReports && totalReports > 0 ? 'complete' : 'pending');
        var card = document.createElement('a');
        card.className = 'proj-card';
        card.href = '/projects/' + encodeURIComponent(p.name);
        card.innerHTML =
          '<div class="proj-card-top"><div class="proj-card-name">' + _escHtml(p.name) + '</div>' + _statusBadge(projStatus) + '</div>' +
          '<div class="proj-card-counts"><span>' + totalReports + ' report' + (totalReports !== 1 ? 's' : '') + '</span>' +
          (totalReports > 0 ? '<span>' + doneCount + '/' + totalReports + ' complete</span>' : '') + '</div>' +
          '<div class="proj-card-date">' + _fmtDate(p.updated_at || p.created_at) + '</div>';

        var delBtn = document.createElement('button');
        delBtn.className = 'btn-delete-proj';
        delBtn.title = 'Delete project';
        delBtn.innerHTML =
          '<svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="M2 3.5h9M5.5 3.5V2.5h2v1M3.5 3.5l.5 7h5l.5-7"/>' +
          '</svg>';
        delBtn.addEventListener('click', async function(e) {
          e.preventDefault();
          e.stopPropagation();
          if (!confirm('Delete project "' + p.name + '"?\nThis will permanently remove all uploaded files and cannot be undone.')) return;
          try {
            var r = await fetch('/api/projects/' + encodeURIComponent(p.name), { method: 'DELETE' });
            if (r.ok || r.status === 204) { loadProjects(); }
            else { var t = await r.text(); alert('Delete failed: ' + t); }
          } catch (ex) { alert('Delete failed: ' + ex.message); }
        });
        card.appendChild(delBtn);
        grid.appendChild(card);
      });
    } catch (e) { console.warn('Failed to load projects:', e); }
  }
}

/* ══════════════════════════════════════════════════════════════════════════
   PROJECT DETAIL PAGE
   ══════════════════════════════════════════════════════════════════════════ */

function initProjectDetailPage() {
  var projectName = decodeURIComponent(location.pathname.split('/projects/')[1] || '');
  var titleEl     = document.getElementById('projTitle');
  var metaEl      = document.getElementById('projMeta');
  var breadcrumb  = document.getElementById('breadcrumbName');
  var addBtn      = document.getElementById('addReportBtn');
  var compareBtn  = document.getElementById('compareBtn');
  var uploadZone  = document.getElementById('uploadZone');
  var dzMini      = document.getElementById('dzMini');
  var dzInput     = document.getElementById('dzInput');
  var dzFileList  = document.getElementById('dzFileList');
  var uploadBtn   = document.getElementById('uploadBtn');
  var cancelUpBtn = document.getElementById('cancelUploadBtn');
  var uploadErr   = document.getElementById('uploadErr');
  var reportsEmpty= document.getElementById('reportsEmpty');
  var reportsList = document.getElementById('reportsList');

  if (breadcrumb) breadcrumb.textContent = projectName;
  if (titleEl)    titleEl.textContent    = projectName;

  var selectedFiles = [];  // FileList → Array

  /* ── Upload zone wiring ─────────────────────────────────────────────── */

  addBtn.addEventListener('click', function() {
    uploadZone.style.display = 'block';
    addBtn.style.display = 'none';
    if (compareBtn) compareBtn.style.display = 'none';
  });

  cancelUpBtn.addEventListener('click', resetUploadZone);

  dzMini.addEventListener('click', function() { dzInput.click(); });
  dzMini.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); dzInput.click(); }
  });
  dzMini.addEventListener('dragover', function(e) { e.preventDefault(); dzMini.classList.add('over'); });
  dzMini.addEventListener('dragleave', function() { dzMini.classList.remove('over'); });
  dzMini.addEventListener('drop', function(e) {
    e.preventDefault(); dzMini.classList.remove('over');
    pickFiles(e.dataTransfer.files);
  });
  dzInput.addEventListener('change', function(e) { pickFiles(e.target.files); });

  function pickFiles(fileList) {
    if (!fileList || fileList.length === 0) return;
    var valid = [];
    var skipped = [];
    for (var i = 0; i < fileList.length; i++) {
      var f = fileList[i];
      var ext = f.name.split('.').pop().toLowerCase();
      if (['twb', 'twbx'].includes(ext)) valid.push(f);
      else skipped.push(f.name);
    }
    if (skipped.length > 0) {
      showUploadErr('Skipped ' + skipped.length + ' unsupported file(s): ' + skipped.join(', '));
    } else {
      uploadErr.style.display = 'none';
    }
    if (valid.length === 0) return;
    selectedFiles = valid;
    renderFileList();
    uploadBtn.disabled = false;
    uploadBtn.textContent = 'Upload ' + valid.length + ' Report' + (valid.length > 1 ? 's' : '');
  }

  function renderFileList() {
    dzMini.style.display = 'none';
    dzFileList.style.display = 'block';
    dzFileList.innerHTML = '';
    selectedFiles.forEach(function(f, i) {
      var row = document.createElement('div');
      row.className = 'dz-file-row';
      row.id = 'dzfile-' + i;
      row.innerHTML =
        '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="var(--violet)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
          '<path d="M8 1.5H4a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V4.5l-3-3z"/><path d="M8 1.5V4.5h3"/>' +
        '</svg>' +
        '<span class="dz-file-name">' + _escHtml(f.name) + '</span>' +
        '<span class="dz-file-status" id="dfstatus-' + i + '"></span>';
      dzFileList.appendChild(row);
    });
  }

  function resetUploadZone() {
    selectedFiles = [];
    dzInput.value = '';
    dzFileList.innerHTML = '';
    dzFileList.style.display = 'none';
    dzMini.style.display = '';
    uploadBtn.disabled = true;
    uploadBtn.textContent = 'Upload Reports';
    uploadErr.style.display = 'none';
    uploadZone.style.display = 'none';
    addBtn.style.display = '';
    if (compareBtn) compareBtn.style.display = '';
  }

  function showUploadErr(msg) { uploadErr.textContent = msg; uploadErr.style.display = 'inline'; }

  /* ── Sequential multi-file upload ──────────────────────────────────── */

  uploadBtn.addEventListener('click', async function() {
    if (selectedFiles.length === 0) return;
    uploadBtn.disabled = true;
    uploadBtn.textContent = 'Uploading…';
    uploadErr.style.display = 'none';

    var errors = [];
    for (var i = 0; i < selectedFiles.length; i++) {
      var statusEl = document.getElementById('dfstatus-' + i);
      if (statusEl) { statusEl.textContent = '⟳'; statusEl.style.color = 'var(--violet)'; }
      try {
        var fd = new FormData();
        fd.append('file', selectedFiles[i]);
        var resp = await fetch('/api/projects/' + encodeURIComponent(projectName) + '/reports', {
          method: 'POST', body: fd,
        });
        if (!resp.ok) {
          var msg = await resp.text();
          throw new Error(msg || 'HTTP ' + resp.status);
        }
        if (statusEl) { statusEl.textContent = '✓'; statusEl.style.color = 'var(--green)'; }
      } catch (e) {
        errors.push(selectedFiles[i].name + ': ' + (e.message || 'failed'));
        if (statusEl) { statusEl.textContent = '✕'; statusEl.style.color = 'var(--rose)'; }
      }
    }

    await loadReports();

    if (errors.length > 0) {
      showUploadErr('Some uploads failed: ' + errors.join(' | '));
      uploadBtn.disabled = false;
      uploadBtn.textContent = 'Retry Failed';
    } else {
      resetUploadZone();
    }
  });

  /* ── Reports list ───────────────────────────────────────────────────── */

  async function loadReports() {
    try {
      var resp = await fetch('/api/projects/' + encodeURIComponent(projectName));
      if (!resp.ok) { if (titleEl) titleEl.textContent = 'Project not found'; return; }
      var proj = await resp.json();

      if (titleEl)    titleEl.textContent    = proj.name;
      if (breadcrumb) breadcrumb.textContent = proj.name;

      var reports = proj.reports || [];
      var doneCount = reports.filter(function(r) { return r.status === 'complete'; }).length;
      if (metaEl) {
        metaEl.textContent = reports.length + ' report' + (reports.length !== 1 ? 's' : '') +
          (reports.length > 0 ? ' · ' + doneCount + ' complete' : '') +
          ' · Updated ' + _fmtDate(proj.updated_at);
      }

      /* Show Compare button only when there are ≥ 2 complete reports */
      if (compareBtn) compareBtn.style.display = doneCount >= 2 ? '' : 'none';

      reportsList.innerHTML = '';
      if (reports.length === 0) { reportsEmpty.style.display = 'flex'; return; }
      reportsEmpty.style.display = 'none';
      reports.forEach(function(report) { reportsList.appendChild(buildReportRow(report)); });
    } catch (e) { console.error('Failed to load project:', e); }
    loadComparisons();
  }

  /* ── Build a single report row ──────────────────────────────────────── */

  function buildReportRow(report) {
    var row = document.createElement('div');
    row.className = 'report-row';
    row.id = 'row-' + report.workbook_name;

    var isRunning = report.status === 'running';
    var isDone    = report.status === 'complete';

    var viewLink = isDone
      ? '<a class="btn-view-sm" href="/project/' + encodeURIComponent(report.workbook_name) + '">View Dashboard</a>'
      : '';

    var fddBtn = isDone
      ? '<button class="btn-fdd btn-sm" data-workbook="' + _escHtml(report.workbook_name) + '" data-run="' + _escHtml(report.last_run_id || '') + '">FDD</button>'
      : '';

    row.innerHTML =
      '<div class="report-row-info">' +
        '<div class="report-filename">' + _escHtml(report.filename) + '</div>' +
        (report.error ? '<div class="report-error">' + _escHtml(report.error) + '</div>' : '') +
      '</div>' +
      '<div class="report-row-actions">' +
        _statusBadge(report.status) +
        viewLink +
        fddBtn +
        '<button class="btn-start btn-sm" data-workbook="' + _escHtml(report.workbook_name) + '"' + (isRunning ? ' disabled' : '') + '>' +
          (isRunning ? 'Running…' : (isDone ? 'Re-run' : 'Start')) +
        '</button>' +
        '<button class="btn-delete-report" title="Delete report"' + (isRunning ? ' disabled' : '') + '>' +
          '<svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="M2 3.5h9M5.5 3.5V2.5h2v1M3.5 3.5l.5 7h5l.5-7"/>' +
          '</svg>' +
        '</button>' +
      '</div>' +
      '<div class="report-progress" id="progress-' + report.workbook_name + '" style="display:none">' +
        '<div class="prog-stages" id="stages-' + report.workbook_name + '"></div>' +
        '<div class="prog-log"   id="log-'    + report.workbook_name + '"></div>' +
      '</div>' +
      '<div class="fdd-progress" id="fddprogress-' + report.workbook_name + '" style="display:none">' +
        '<div class="prog-stages" id="fddstages-' + report.workbook_name + '"></div>' +
      '</div>';

    row.querySelector('.btn-start').addEventListener('click', function() {
      startPipeline(report.workbook_name);
    });

    var fddBtnEl = row.querySelector('.btn-fdd');
    if (fddBtnEl) {
      fddBtnEl.addEventListener('click', function() {
        generateFdd(report.workbook_name, report.last_run_id || null);
      });
    }

    var delReportBtn = row.querySelector('.btn-delete-report');
    if (delReportBtn) {
      delReportBtn.addEventListener('click', async function() {
        if (!confirm('Remove "' + report.filename + '" from this project?\nThe uploaded file will be permanently deleted.')) return;
        try {
          var r = await fetch(
            '/api/projects/' + encodeURIComponent(projectName) +
            '/reports/' + encodeURIComponent(report.workbook_name),
            { method: 'DELETE' }
          );
          if (r.ok) { loadReports(); }
          else { var t = await r.text(); alert('Delete failed: ' + t); }
        } catch (ex) { alert('Delete failed: ' + ex.message); }
      });
    }

    return row;
  }

  /* ── Pipeline start / SSE streaming ────────────────────────────────── */

  function startPipeline(workbookName) {
    var row      = document.getElementById('row-' + workbookName);
    var startBtn = row ? row.querySelector('.btn-start') : null;
    var progEl   = document.getElementById('progress-' + workbookName);
    var stagesEl = document.getElementById('stages-' + workbookName);
    var logEl    = document.getElementById('log-' + workbookName);
    var badge    = row ? row.querySelector('.status-badge') : null;

    if (startBtn) { startBtn.disabled = true; startBtn.textContent = 'Running…'; }
    if (progEl)   progEl.style.display = 'block';
    if (stagesEl) stagesEl.innerHTML = '';
    if (logEl)    logEl.innerHTML = '';
    if (badge)    { badge.textContent = 'Running'; badge.style.color = 'var(--violet)'; badge.style.background = 'var(--violet-l)'; }

    var url = '/api/projects/' + encodeURIComponent(projectName) +
              '/reports/' + encodeURIComponent(workbookName) + '/start-stream';

    _streamSse(url, 'POST', function(msg) {
      handlePipelineEvent(msg, workbookName, stagesEl, logEl, badge, startBtn);
    }, function(err) {
      onPipelineDone(workbookName, badge, startBtn, err);
    }, function() {
      onPipelineDone(workbookName, badge, startBtn, null);
    });
  }

  function handlePipelineEvent(msg, workbookName, stagesEl, logEl, badge, startBtn) {
    if (msg.type === 'log') {
      if (logEl) {
        var line = document.createElement('div');
        line.className = 'prog-log-line ' + (msg.level || '').toLowerCase();
        line.textContent = msg.message;
        logEl.appendChild(line);
        logEl.scrollTop = logEl.scrollHeight;
      }
      return;
    }
    if (typeof msg.step === 'number') {
      var labels = { 1: 'Uploading', 2: 'Parsing workbook' };
      upsertStage(stagesEl, 'analyze-' + msg.step, labels[msg.step] || 'Step ' + msg.step, msg.state);
      return;
    }
    if (msg.agent_id) {
      upsertStage(stagesEl, msg.agent_id, msg.agent_label || msg.agent_id, msg.state);
      return;
    }
    if (msg.step === 'complete') {
      if (badge) { badge.textContent = 'Complete'; badge.style.color = 'var(--green)'; badge.style.background = 'var(--green-l)'; }
      if (startBtn) startBtn.textContent = 'Re-run';
      var row = document.getElementById('row-' + workbookName);
      if (row && !row.querySelector('.btn-view-sm')) {
        var actionsEl = row.querySelector('.report-row-actions');
        if (actionsEl) {
          var link = document.createElement('a');
          link.className = 'btn-view-sm';
          link.href = '/project/' + encodeURIComponent(workbookName);
          link.textContent = 'View Dashboard';
          actionsEl.insertBefore(link, actionsEl.querySelector('.btn-start'));
        }
      }
      return;
    }
    if (msg.step === 'error') {
      if (badge) { badge.textContent = 'Error'; badge.style.color = 'var(--rose)'; badge.style.background = 'var(--rose-l)'; }
      if (startBtn) { startBtn.disabled = false; startBtn.textContent = 'Retry'; }
      if (logEl) {
        var errLine = document.createElement('div');
        errLine.className = 'prog-log-line error';
        errLine.textContent = '✕ ' + (msg.message || 'Unknown error');
        logEl.appendChild(errLine);
      }
    }
  }

  function onPipelineDone(workbookName, badge, startBtn, errMsg) {
    if (errMsg) {
      if (badge)    { badge.textContent = 'Error'; badge.style.color = 'var(--rose)'; badge.style.background = 'var(--rose-l)'; }
      if (startBtn) { startBtn.disabled = false; startBtn.textContent = 'Retry'; }
    }
    loadReports();
  }

  /* ── FDD generation ─────────────────────────────────────────────────── */

  function generateFdd(workbookName, runId) {
    var row      = document.getElementById('row-' + workbookName);
    var fddBtn   = row ? row.querySelector('.btn-fdd') : null;
    var progEl   = document.getElementById('fddprogress-' + workbookName);
    var stagesEl = document.getElementById('fddstages-' + workbookName);

    if (fddBtn)   { fddBtn.disabled = true; fddBtn.textContent = 'Generating…'; }
    if (progEl)   progEl.style.display = 'block';
    if (stagesEl) stagesEl.innerHTML = '';

    upsertStage(stagesEl, 'fdd', 'Functional Documentation', 'running');

    /* POST to existing /documentation-stream endpoint */
    fetch('/documentation-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workbook_name: workbookName, run_id: runId }),
    }).then(function(resp) {
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      var reader  = resp.body.getReader();
      var decoder = new TextDecoder();
      var buffer  = '';

      function read() {
        reader.read().then(function(result) {
          if (result.done) {
            onFddDone(workbookName, fddBtn, stagesEl, null);
            return;
          }
          buffer += decoder.decode(result.value, { stream: true });
          var boundary;
          while ((boundary = buffer.indexOf('\n\n')) !== -1) {
            var raw = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            var dataLine = raw.split('\n').find(function(l) { return l.startsWith('data:'); });
            if (!dataLine) continue;
            var jsonStr = dataLine.slice(5).trim();
            var msg; try { msg = JSON.parse(jsonStr); } catch(e) { continue; }
            if (msg.state === 'done') {
              upsertStage(stagesEl, 'fdd', 'Functional Documentation', 'done');
            } else if (msg.state === 'error' || msg.step === 'error') {
              upsertStage(stagesEl, 'fdd', 'Functional Documentation', 'error');
              onFddDone(workbookName, fddBtn, stagesEl, msg.message || 'FDD failed');
              return;
            }
          }
          read();
        }).catch(function(e) { onFddDone(workbookName, fddBtn, stagesEl, e.message); });
      }
      read();
    }).catch(function(e) { onFddDone(workbookName, fddBtn, stagesEl, e.message); });
  }

  function onFddDone(workbookName, fddBtn, stagesEl, errMsg) {
    if (errMsg) {
      upsertStage(stagesEl, 'fdd', 'Functional Documentation', 'error');
      if (fddBtn) { fddBtn.disabled = false; fddBtn.textContent = 'FDD'; }
    } else {
      upsertStage(stagesEl, 'fdd', 'Functional Documentation', 'done');
      if (fddBtn) {
        /* Replace button with a direct link */
        var link = document.createElement('a');
        link.className = 'btn-fdd btn-sm btn-fdd-done';
        link.href = '/documentation/' + encodeURIComponent(workbookName) + '/html';
        link.target = '_blank';
        link.textContent = 'View FDD';
        fddBtn.replaceWith(link);
      }
    }
  }

  /* ── Compare modal ──────────────────────────────────────────────────── */

  var compareOverlay    = document.getElementById('compareOverlay');
  var compareChecklist  = document.getElementById('compareChecklist');
  var compareRunBtn     = document.getElementById('compareRunBtn');
  var compareHint       = document.getElementById('compareHint');
  var compareSelectAll  = document.getElementById('compareSelectAll');
  var compareDeselectAll= document.getElementById('compareDeselectAll');
  var compareModalClose = document.getElementById('compareModalClose');
  var compareCancelBtn  = document.getElementById('compareCancelBtn');

  if (compareBtn) {
    compareBtn.addEventListener('click', openCompareModal);
  }

  function openCompareModal() {
    buildCompareChecklist();
    compareOverlay.style.display = 'flex';
    updateCompareBtn();
  }

  function closeCompareModal() { compareOverlay.style.display = 'none'; }

  if (compareModalClose) compareModalClose.addEventListener('click', closeCompareModal);
  if (compareCancelBtn)  compareCancelBtn.addEventListener('click', closeCompareModal);
  if (compareOverlay) {
    compareOverlay.addEventListener('click', function(e) {
      if (e.target === compareOverlay) closeCompareModal();
    });
  }
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && compareOverlay && compareOverlay.style.display !== 'none') closeCompareModal();
  });

  function buildCompareChecklist() {
    if (!compareChecklist) return;
    compareChecklist.innerHTML = '';

    /* Collect complete reports from DOM rows */
    var rows = reportsList.querySelectorAll('.report-row');
    var found = 0;
    rows.forEach(function(row) {
      var badge = row.querySelector('.status-badge');
      if (!badge || badge.textContent !== 'Complete') return;
      var workbookName = row.id.replace('row-', '');
      var filename = row.querySelector('.report-filename');
      found++;

      var item = document.createElement('label');
      item.className = 'compare-item';
      item.innerHTML =
        '<input type="checkbox" class="compare-cb" value="' + _escHtml(workbookName) + '" />' +
        '<span class="compare-item-name">' + _escHtml(filename ? filename.textContent : workbookName) + '</span>';
      item.querySelector('input').addEventListener('change', updateCompareBtn);
      compareChecklist.appendChild(item);
    });

    if (found === 0) {
      compareChecklist.innerHTML = '<p style="color:var(--muted);font-size:13px;padding:8px 0">No completed reports to compare.</p>';
    }
  }

  function getChecked() {
    if (!compareChecklist) return [];
    return Array.from(compareChecklist.querySelectorAll('.compare-cb:checked')).map(function(cb) { return cb.value; });
  }

  function updateCompareBtn() {
    var checked = getChecked();
    if (compareRunBtn)  compareRunBtn.disabled  = checked.length < 2;
    if (compareHint)    compareHint.textContent = checked.length < 2
      ? 'Select at least 2 reports'
      : checked.length + ' report' + (checked.length > 1 ? 's' : '') + ' selected';
  }

  if (compareSelectAll) {
    compareSelectAll.addEventListener('click', function() {
      compareChecklist.querySelectorAll('.compare-cb').forEach(function(cb) { cb.checked = true; });
      updateCompareBtn();
    });
  }

  if (compareDeselectAll) {
    compareDeselectAll.addEventListener('click', function() {
      compareChecklist.querySelectorAll('.compare-cb').forEach(function(cb) { cb.checked = false; });
      updateCompareBtn();
    });
  }

  if (compareRunBtn) {
    compareRunBtn.addEventListener('click', async function() {
      var selected = getChecked();
      if (selected.length < 2) return;
      closeCompareModal();
      await startComparison(selected);
    });
  }

  /* ── Comparison history ─────────────────────────────────────────────── */

  var newCompareBtn2 = document.getElementById('newCompareBtn2');
  if (newCompareBtn2) newCompareBtn2.addEventListener('click', openCompareModal);

  async function startComparison(workbookNames) {
    try {
      /* 1. Create the comparison record */
      var r = await fetch('/api/projects/' + encodeURIComponent(projectName) + '/comparisons', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workbook_names: workbookNames }),
      });
      if (!r.ok) { var t = await r.text(); alert('Could not start comparison: ' + t); return; }
      var meta = await r.json();
      var compareId = meta.id;

      /* 2. Insert a placeholder row immediately */
      loadComparisons();

      /* 3. Start the SSE stream */
      var streamUrl = '/api/projects/' + encodeURIComponent(projectName) +
                      '/comparisons/' + encodeURIComponent(compareId) + '/stream';
      _streamSse(streamUrl, 'POST',
        function(msg) { /* log events — no UI action needed during compare */ },
        function(err) { loadComparisons(); },
        function() {
          loadComparisons();
          window.location.href = '/projects/' + encodeURIComponent(projectName) +
                                 '/compare/' + encodeURIComponent(compareId);
        }
      );
    } catch (ex) { alert('Comparison failed: ' + ex.message); }
  }

  var _pollTimers = {};

  function pollComparison(compareId) {
    if (_pollTimers[compareId]) return;  // already polling
    _pollTimers[compareId] = setInterval(async function() {
      try {
        var r = await fetch('/api/projects/' + encodeURIComponent(projectName) +
                            '/comparisons/' + encodeURIComponent(compareId));
        if (!r.ok) { clearInterval(_pollTimers[compareId]); delete _pollTimers[compareId]; return; }
        var cmp = await r.json();
        if (cmp.status !== 'running') {
          clearInterval(_pollTimers[compareId]);
          delete _pollTimers[compareId];
          loadComparisons();
        }
      } catch (ex) { clearInterval(_pollTimers[compareId]); delete _pollTimers[compareId]; }
    }, 5000);
  }

  async function loadComparisons() {
    var listEl   = document.getElementById('comparisonsList');
    var emptyEl  = document.getElementById('comparisonsEmpty');
    var countEl  = document.getElementById('cmpCount');
    if (!listEl) return;
    try {
      var r = await fetch('/api/projects/' + encodeURIComponent(projectName) + '/comparisons');
      if (!r.ok) return;
      var comparisons = await r.json();
      listEl.innerHTML = '';
      if (!comparisons || comparisons.length === 0) {
        if (emptyEl) emptyEl.style.display = 'flex';
        if (countEl) countEl.textContent = '';
        return;
      }
      if (emptyEl) emptyEl.style.display = 'none';
      if (countEl) countEl.textContent = '(' + comparisons.length + ')';
      comparisons.forEach(function(cmp) {
        listEl.appendChild(buildComparisonRow(cmp));
        if (cmp.status === 'running') pollComparison(cmp.id);
      });
    } catch (e) { console.warn('Failed to load comparisons:', e); }
  }

  function buildComparisonRow(cmp) {
    var row = document.createElement('div');
    row.className = 'comparison-row';
    row.id = 'cmp-' + cmp.id;

    var date = _fmtDate(cmp.created_at);
    var chips = (cmp.workbook_names || []).map(function(n) {
      return '<span class="comparison-chip">' + _escHtml(n) + '</span>';
    }).join('');

    var verdictHtml = '';
    if (cmp.verdict_summary) {
      var vs = cmp.verdict_summary;
      var parts = [];
      if (vs.merge_count > 0)    parts.push('<span class="verdict-mini merge">'     + vs.merge_count     + ' merge</span>');
      if (vs.borderline_count > 0) parts.push('<span class="verdict-mini borderline">' + vs.borderline_count + ' borderline</span>');
      if (vs.separate_count > 0) parts.push('<span class="verdict-mini separate">'  + vs.separate_count  + ' separate</span>');
      verdictHtml = parts.join(' ');
    }

    var actionHtml = '';
    if (cmp.status === 'running') {
      actionHtml = '<span class="cmp-running">⟳ Running…</span>';
    } else if (cmp.status === 'error') {
      actionHtml = '<span class="cmp-error">✕ Error</span>';
    } else if (cmp.status === 'complete') {
      actionHtml = '<a class="btn-view-sm" href="/projects/' + encodeURIComponent(projectName) +
                   '/compare/' + encodeURIComponent(cmp.id) + '">View</a>';
    }

    row.innerHTML =
      '<div class="cmp-row-main">' +
        '<div class="cmp-row-info">' +
          '<span class="cmp-date">' + date + '</span>' +
          '<span class="comparison-chips">' + chips + '</span>' +
          verdictHtml +
        '</div>' +
        '<div class="cmp-row-action">' + actionHtml + '</div>' +
      '</div>' +
      (cmp.error ? '<div class="report-error">' + _escHtml(cmp.error) + '</div>' : '');
    return row;
  }

  /* ── Shared SSE helper ──────────────────────────────────────────────── */

  function _streamSse(url, method, onMsg, onError, onDone) {
    fetch(url, { method: method }).then(function(resp) {
      if (!resp.ok) { onError && onError('HTTP ' + resp.status); return; }
      var reader  = resp.body.getReader();
      var decoder = new TextDecoder();
      var buffer  = '';
      function read() {
        reader.read().then(function(result) {
          if (result.done) { onDone && onDone(); return; }
          buffer += decoder.decode(result.value, { stream: true });
          var boundary;
          while ((boundary = buffer.indexOf('\n\n')) !== -1) {
            var raw = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            var dataLine = raw.split('\n').find(function(l) { return l.startsWith('data:'); });
            if (!dataLine) continue;
            var jsonStr = dataLine.slice(5).trim();
            var msg; try { msg = JSON.parse(jsonStr); } catch(e) { continue; }
            onMsg && onMsg(msg);
          }
          read();
        }).catch(function(e) { onError && onError(e.message || 'Stream error'); });
      }
      read();
    }).catch(function(e) { onError && onError(e.message || 'Request failed'); });
  }

  /* ── Stage chip helper ──────────────────────────────────────────────── */

  function upsertStage(container, id, label, state) {
    if (!container) return;
    var el = container.querySelector('[data-stage="' + id + '"]');
    if (!el) { el = document.createElement('div'); el.className = 'stage-chip'; el.dataset.stage = id; container.appendChild(el); }
    var icons  = { running: '⟳', done: '✓', error: '✕', skipped: '–' };
    var colors = { running: 'var(--violet)', done: 'var(--green)', error: 'var(--rose)', skipped: 'var(--muted)' };
    el.textContent = (icons[state] || '·') + ' ' + label;
    el.style.color = colors[state] || 'var(--ink)';
    el.style.opacity = state === 'skipped' ? '0.5' : '1';
  }

  /* Initial load */
  loadReports();
}
