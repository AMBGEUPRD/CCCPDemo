/* results-analysis.js — Analysis results page (tables, KPIs, charts) */

(async function() {
  console.log('[BIM-AI] results-analysis.js IIFE started');
  try {
  if (!(await loadSession())) {
    console.warn('[BIM-AI] loadSession returned false, showing error state');
    document.getElementById('errorState').classList.add('on');
    return;
  }
  console.log('[BIM-AI] loadSession OK, rendering...');

  /* Show "Back to Project" link if workbook param is in URL */
  var _params = new URLSearchParams(location.search);
  var _wbParam = _params.get('workbook');
  if (_wbParam) {
    var _projLink = document.getElementById('backToProjectLink');
    if (_projLink) {
      _projLink.href = '/project/' + encodeURIComponent(_wbParam);
      _projLink.style.display = '';
    }
  }

  const content = document.getElementById('resultsContent');
  content.style.display = 'flex';

  // ── Header ──
  const dt    = new Date(session.timestamp);
  const dtStr = dt.toLocaleDateString('en-GB', {day:'2-digit',month:'short',year:'numeric'})
              + ' \u00B7 ' + dt.toLocaleTimeString('en-GB', {hour:'2-digit',minute:'2-digit'});
  document.getElementById('pageTitle').textContent  = session.filename || 'Report';
  document.getElementById('metaDate').textContent   = '\u{1F550} ' + dtStr;
  document.getElementById('metaFile').textContent   = '\u{1F4C4} ' + (session.filename || '\u2014');

  if (session.adls_path) {
    document.getElementById('adlsPath').textContent = session.adls_path;
    document.getElementById('adlsStrip').classList.add('on');
  }

  // ── Parse data ──
  const datasources = (analysis.datasources || []).filter(ds => ds.columns && ds.columns.length > 0);
  const worksheets  = analysis.worksheets  || [];
  const dashboards  = analysis.dashboards  || [];
  const parameters  = analysis.parameters  || [];

  const allColumns  = datasources.flatMap(ds => ds.columns || []);
  const allCalc     = datasources.flatMap(ds => ds.calculated_fields || []);
  const allJoins    = datasources.flatMap(ds => ds.joins || []);
  const allTables   = datasources.flatMap(ds => ds.tables || []);
  const totalFilters= worksheets.reduce((s, w) => s + (w.filters||[]).length, 0);

  // ── KPI tiles with animated counters ──
  const kpis = [
    { label:'Data Sources',       value: datasources.length,  color:'blue',   icon:'\u{1F5C4}\uFE0F' },
    { label:'Tables',             value: allTables.length,    color:'teal',   icon:'\u{1F4CB}' },
    { label:'Columns',            value: allColumns.length,   color:'indigo', icon:'#\uFE0F\u20E3'  },
    { label:'Calculated Fields',  value: allCalc.length,      color:'purple', icon:'\u2699\uFE0F'  },
    { label:'Worksheets',         value: worksheets.length,   color:'amber',  icon:'\u{1F4CA}' },
    { label:'Dashboards',         value: dashboards.length,   color:'green',  icon:'\u{1F5A5}\uFE0F'  },
    { label:'Filters',            value: totalFilters,        color:'rose',   icon:'\u{1F53D}' },
    { label:'Parameters',         value: parameters.length,   color:'teal',   icon:'\u{1F39B}\uFE0F'  },
  ];
  const kpiGrid = document.getElementById('kpiGrid');
  kpiGrid.style.gridTemplateColumns = `repeat(${Math.min(kpis.length,4)},1fr)`;

  /* Store KPI value elements for IntersectionObserver animation */
  var kpiValueEls = [];

  kpis.forEach((k, i) => {
    const el = document.createElement('div');
    el.className = `kpi ${k.color}`;
    el.style.animationDelay = (i * 0.05) + 's';
    el.innerHTML = `<div class="kpi-icon">${k.icon}</div>
                    <div class="kpi-value" data-target="${k.value}">0</div>
                    <div class="kpi-label">${k.label}</div>`;
    kpiGrid.appendChild(el);
    kpiValueEls.push({ el: el.querySelector('.kpi-value'), target: k.value });
  });

  /* IntersectionObserver — animate KPI numbers when they enter viewport */
  var kpiAnimated = false;
  var kpiObserver = new IntersectionObserver(function(entries) {
    entries.forEach(function(entry) {
      if (entry.isIntersecting && !kpiAnimated) {
        kpiAnimated = true;
        kpiValueEls.forEach(function(item) {
          animateValue(item.el, item.target, 1200);
        });
        kpiObserver.disconnect();
      }
    });
  }, { threshold: 0.2 });
  kpiObserver.observe(kpiGrid);

  // ── Data Overview charts ──
  renderCharts(analysis);

  // ── Datasources table ──
  document.getElementById('badgeDatasources').textContent = datasources.length + ' sources';
  const dsTbody = document.querySelector('#tableDatasources tbody');
  datasources.forEach(ds => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><strong>${esc(ds.caption || ds.name)}</strong></td>
      <td><span class="pill dim">${esc(ds.connection?.type || '\u2014')}</span></td>
      <td><span style="font-family:var(--mono);font-size:11px">${esc(ds.connection?.filename || (ds.tables[0]?.name) || '\u2014')}</span></td>
      <td><span class="pill meas">${(ds.columns||[]).length}</span></td>
      <td><span class="pill calc">${(ds.calculated_fields||[]).length}</span></td>
    `;
    dsTbody.appendChild(tr);
  });
  enableTableSort(document.getElementById('tableDatasources'));
  enableTableSearch('tableDatasources');

  // ── Columns table ──
  document.getElementById('badgeColumns').textContent = allColumns.length + ' fields';
  const colTbody = document.querySelector('#tableColumns tbody');
  allColumns.forEach(col => {
    const dtPill = dtypePill(col.datatype);
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${fieldNameCell(col.name, col.caption)}</td>
      <td>${dtPill}</td>
      <td><span class="pill dim">${esc(col.role || '\u2014')}</span></td>
      <td style="font-family:var(--mono);font-size:11px;color:var(--muted)">${esc(col.semantic_role || '\u2014')}</td>
    `;
    colTbody.appendChild(tr);
  });
  enableTableSort(document.getElementById('tableColumns'));
  enableTableSearch('tableColumns');

  // ── Calculated fields table (with syntax highlighting) ──
  document.getElementById('badgeCalc').textContent = allCalc.length + ' fields';
  const calcTbody = document.querySelector('#tableCalc tbody');
  if (allCalc.length === 0) {
    calcTbody.innerHTML = `<tr><td colspan="4" style="color:var(--muted);font-style:italic;text-align:center;padding:24px">No calculated fields found</td></tr>`;
  }
  allCalc.forEach(cf => {
    const tr = document.createElement('tr');
    var formulaHtml = cf.formula
      ? '<span class="calc-formula" title="' + esc(cf.formula) + '">' + highlightFormula(cf.formula) + '</span>'
      : '<span class="formula-code">\u2014</span>';
    tr.innerHTML = `
      <td>${fieldNameCell(cf.name, cf.caption)}</td>
      <td>${dtypePill(cf.datatype)}</td>
      <td>${formulaHtml}</td>
    `;
    calcTbody.appendChild(tr);
  });
  enableTableSort(document.getElementById('tableCalc'));
  enableTableSearch('tableCalc');

  // ── Worksheets table ──
  document.getElementById('badgeWorksheets').textContent = worksheets.length + ' sheets';
  const wsTbody = document.querySelector('#tableWorksheets tbody');
  worksheets.forEach(ws => {
    const cols = (ws.cols_shelf || []).filter(f => f.field).map(f => f.field).join(', ') || '\u2014';
    const rows = (ws.rows_shelf || []).filter(f => f.field).map(f => f.field).join(', ') || '\u2014';
    const filters = (ws.filters || []).length;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><strong>${esc(ws.title || ws.name)}</strong>${ws.uses_measure_values ? ' <span class="pill dim" title="Uses Measure Names / Measure Values pattern — needs special handling in Power BI">MV</span>' : ''}</td>
      <td><span class="pill dim">${esc(ws.mark_type || '\u2014')}</span></td>
      <td style="font-size:12px;color:var(--ink2)">${esc(cols)}</td>
      <td style="font-size:12px;color:var(--ink2)">${esc(rows)}</td>
      <td>${filters > 0 ? `<span class="pill meas">${filters}</span>` : '<span style="color:var(--muted)">\u2014</span>'}</td>
    `;
    wsTbody.appendChild(tr);
  });
  enableTableSort(document.getElementById('tableWorksheets'));
  enableTableSearch('tableWorksheets');

  // ── Dashboards ──
  document.getElementById('badgeDashboards').textContent = dashboards.length + ' dashboards';
  const dbBody = document.getElementById('dashboardBody');
  dashboards.forEach(db => {
    const hdr = document.createElement('div');
    hdr.style.cssText = 'padding:14px 20px 4px;font-weight:700;font-size:14px;color:var(--ink);border-bottom:1px solid var(--border)';
    const sizeW = db.size && (db.size.maxwidth  || db.size.width  || db.size.w);
    const sizeH = db.size && (db.size.maxheight || db.size.height || db.size.h);
    const sizeStr = (sizeW && sizeH) ? ` \u2014 ${sizeW}\u00D7${sizeH}px` : '';
    hdr.textContent = db.name + sizeStr;
    dbBody.appendChild(hdr);

    const grid = document.createElement('div');
    grid.className = 'dashboard-grid';
    const sheets = [...new Set(db.sheets || [])];
    sheets.forEach(s => {
      const zone = (db.layout_zones || []).find(z => z.name === s);
      const div  = document.createElement('div');
      div.className = 'dash-sheet';
      div.innerHTML = `<div class="dash-sheet-name">${esc(s)}</div>
        ${zone ? `<div class="dash-sheet-size">${Math.round(zone.w/1000)}k \u00D7 ${Math.round(zone.h/1000)}k units</div>` : ''}`;
      grid.appendChild(div);
    });
    dbBody.appendChild(grid);
  });

  // ── Parameters ──
  if (parameters.length > 0) {
    document.getElementById('cardParams').style.display = '';
    document.getElementById('badgeParams').textContent = parameters.length;
    const pTbody = document.querySelector('#tableParams tbody');
    parameters.forEach(p => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="font-family:var(--mono);font-size:11px">${esc(p.name)}</td>
        <td>${esc(p.caption || '\u2014')}</td>
        <td>${dtypePill(p.datatype)}</td>
        <td style="font-family:var(--mono);font-size:11px">${esc(String(p.default_value||'\u2014'))}</td>
        <td><span class="pill dim">${esc(p.domain_type||'\u2014')}</span></td>
      `;
      pTbody.appendChild(tr);
    });
    enableTableSort(document.getElementById('tableParams'));
    enableTableSearch('tableParams');
  }

  // ── Raw JSON ──
  document.getElementById('rawPre').textContent = JSON.stringify(analysis, null, 2);
  document.getElementById('rawToggle').addEventListener('click', () => {
    const box     = document.getElementById('rawBox');
    const chevron = document.getElementById('rawChevron');
    const open    = box.style.display === 'block';
    box.style.display = open ? 'none' : 'block';
    chevron.classList.toggle('open', !open);
  });

  // ── Copy JSON ──
  document.getElementById('copyRawBtn').addEventListener('click', () => {
    navigator.clipboard.writeText(JSON.stringify(analysis, null, 2)).then(() => {
      const btn = document.getElementById('copyRawBtn');
      btn.childNodes[btn.childNodes.length-1].textContent = ' Copied!';
      setTimeout(() => btn.childNodes[btn.childNodes.length-1].textContent = ' Copy JSON', 2000);
    });
  });

  // ── FDD + Migrate button logic ──
  var workbookName = (session.filename || '').replace(/\.\w+$/, '');
  var resultId = new URLSearchParams(location.search).get('id') || session.id || '';

  function showFddReady() {
    // Show section, swap from loading to ready
    var section = document.getElementById('fddSection');
    if (section) section.style.display = 'block';
    var loading = document.getElementById('fddLoading');
    if (loading) loading.style.display = 'none';
    var ready = document.getElementById('fddReady');
    if (ready) ready.style.display = 'flex';
    document.getElementById('fddViewHtml').href = '/documentation/' + encodeURIComponent(workbookName) + '/html';
    document.getElementById('fddDownloadMd').href = '/documentation/' + encodeURIComponent(workbookName) + '/md';

    // Show Migrate button
    var migrateBtn = document.getElementById('migrateBtn');
    if (migrateBtn) {
      migrateBtn.href = '/generate?id=' + encodeURIComponent(resultId);
      migrateBtn.style.display = 'inline-flex';
    }

    // Update FDD button in nav to "regenerate" state
    var fddBtn = document.getElementById('generateFddBtn');
    var fddLabel = document.getElementById('fddBtnLabel');
    if (fddBtn && fddLabel) {
      fddLabel.textContent = 'Regenerate FDD';
      fddBtn.disabled = false;
      fddBtn.classList.remove('loading');
      fddBtn.classList.remove('fdd-done');
      var spinner = document.getElementById('fddSpinner');
      if (spinner) spinner.style.display = 'none';
    }
  }

  // Check if FDD was already generated for this run (persisted in session)
  if (session.documentation) {
    showFddReady();
  }

  // Generate FDD button handler
  document.getElementById('generateFddBtn').addEventListener('click', async function() {
    var btn = this;
    if (btn.disabled) return;
    btn.disabled = true;
    btn.classList.add('loading');
    var label = document.getElementById('fddBtnLabel');
    var spinner = document.getElementById('fddSpinner');
    if (label) label.textContent = 'Generating\u2026';
    if (spinner) spinner.style.display = 'inline-block';

    // Show FDD section in loading state
    var fddSection = document.getElementById('fddSection');
    if (fddSection) fddSection.style.display = 'block';
    var fddLoading = document.getElementById('fddLoading');
    if (fddLoading) fddLoading.style.display = 'flex';
    var fddReady = document.getElementById('fddReady');
    if (fddReady) fddReady.style.display = 'none';
    if (fddSection) fddSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    try {
      var resp = await fetch('/documentation-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workbook_name: workbookName, result_id: resultId }),
      });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);

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
          if (msg.state === 'error') throw new Error(msg.message || 'FDD generation failed');
        }
      }

      if (!finalData) throw new Error('Stream ended without result');

      // Update session with documentation
      session.documentation = finalData.documentation;
      try {
        sessionStorage.setItem(resultId, JSON.stringify(session));
        fetch('/api/results/' + encodeURIComponent(resultId), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(session),
        });
      } catch(e) { /* best-effort */ }

      showFddReady();

    } catch (err) {
      if (label) label.textContent = 'Generate FDD';
      btn.disabled = false;
      btn.classList.remove('loading');
      if (spinner) spinner.style.display = 'none';
      // Hide the loading section on error
      var fddSec = document.getElementById('fddSection');
      if (fddSec) fddSec.style.display = 'none';
      alert('FDD generation failed: ' + err.message);
    }
  });

  /* ── Load Run History for this workbook ── */
  (async function loadRunHistory() {
    var workbookName = (session.filename || '').replace(/\.\w+$/, '');
    if (!workbookName) return;
    try {
      var resp = await fetch('/api/history/' + encodeURIComponent(workbookName));
      if (!resp.ok) return;
      var runs = await resp.json();
      if (!runs || runs.length === 0) return;

      var card = document.getElementById('cardHistory');
      var badge = document.getElementById('badgeHistory');
      var list = document.getElementById('historyRunsList');
      if (!card || !list) return;

      card.style.display = 'block';
      badge.textContent = runs.length;

      var resultId = new URLSearchParams(location.search).get('id');
      var currentRunId = (session && session.run_id) || null;
      if (!currentRunId && resultId) {
        try { currentRunId = sessionStorage.getItem('run_id_' + resultId); } catch(_) {}
      }

      runs.forEach(function(run) {
        var dt = new Date(run.created_at);
        var dtStr = dt.toLocaleDateString('en-GB', {day:'2-digit', month:'short', year:'numeric'})
                  + ' ' + dt.toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit'});
        var stages = run.stages || {};
        var completed = Object.values(stages).filter(function(s) { return s === 'completed'; }).length;
        var total = Object.keys(stages).length;
        var isCurrent = (run.run_id === currentRunId);

        var row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border)';
        row.innerHTML =
          '<div style="flex:1;min-width:0">' +
            '<div style="font-size:13px;font-weight:600;color:var(--ink1)">' + _escHist(run.run_id) +
              (isCurrent ? ' <span style="font-size:11px;color:var(--violet);font-weight:500">(current)</span>' : '') +
            '</div>' +
            '<div style="font-size:12px;color:var(--muted)">' + dtStr + ' \u00B7 ' + completed + '/' + total + ' stages</div>' +
          '</div>' +
          (isCurrent ? '' :
            '<button class="fdd-action fdd-action--teal" style="font-size:11px;padding:4px 12px" data-run="' + _escAttr(run.run_id) + '">Restore</button>'
          );
        list.appendChild(row);
      });

      // Wire restore buttons
      list.querySelectorAll('button[data-run]').forEach(function(btn) {
        btn.addEventListener('click', async function() {
          var rid = btn.getAttribute('data-run');
          btn.disabled = true;
          btn.textContent = 'Restoring...';
          try {
            var resp = await fetch('/api/history/' + encodeURIComponent(workbookName) + '/' + encodeURIComponent(rid) + '/restore', { method: 'POST' });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            var data = await resp.json();
            try { sessionStorage.setItem('run_id_' + data.result_id, data.run_id); } catch(_) {}
            window.location.href = '/results?id=' + encodeURIComponent(data.result_id);
          } catch(e) {
            btn.disabled = false;
            btn.textContent = 'Restore';
            alert('Restore failed: ' + e.message);
          }
        });
      });
    } catch(e) {
      console.warn('[BIM-AI] Run history load failed:', e);
    }
  })();

  } catch (err) {
    showRenderError(err);
  }
})();

function renderCharts(data) {
  try {
  const chartsRow = document.getElementById('chartsRow');
  if (!chartsRow) return;

  const palette = ['#7c3aed','#4f46e5','#0d9488','#059669','#d97706','#e11d48','#a78bfa','#818cf8'];

  // Helper: capitalise first letter of a role/type string
  function cleanLabel(s) {
    if (!s) return 'Unknown';
    return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
  }

  // Helper: truncate long labels for display
  function truncate(s, max) {
    if (!s) return 'Unknown';
    return s.length > max ? s.slice(0, max) + '\u2026' : s;
  }

  // --- Data computation (all done before any Chart creation) ---

  // Chart 1 data: Field type distribution doughnut
  // Group by role (dimension / measure / calculation), fall back to datatype
  const typeCounts = {};
  (data.datasources || []).forEach(function(ds) {
    (ds.columns || []).forEach(function(col) {
      // Prefer role over datatype — gives "Dimension" / "Measure" etc.
      var raw = col.role || col.datatype || 'unknown';
      var key = cleanLabel(raw);
      typeCounts[key] = (typeCounts[key] || 0) + 1;
    });
  });

  // Sort descending so largest slice is first
  const typeEntries = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]);
  const typeLabels  = typeEntries.map(e => e[0]);
  const typeValues  = typeEntries.map(e => e[1]);
  const total       = typeValues.reduce((s, v) => s + v, 0);

  // Chart 2 data: Columns per datasource horizontal bar
  // Use caption (human-readable) then fall back to name, truncate to 28 chars
  var allDs = (data.datasources || []).filter(function(ds) {
    return (ds.columns || []).length > 0;
  });

  // Sort descending by column count, take top 10
  allDs.sort(function(a, b) { return (b.columns||[]).length - (a.columns||[]).length; });
  allDs = allDs.slice(0, 10);

  var dsLabels = allDs.map(function(ds) {
    return truncate(ds.caption || ds.name || 'Unknown', 28);
  });
  var dsCols = allDs.map(function(ds) { return (ds.columns || []).length; });

  // Full names for tooltip
  var dsFullNames = allDs.map(function(ds) {
    return ds.caption || ds.name || 'Unknown';
  });

  // --- Show container BEFORE creating charts so canvases have real dimensions ---
  if (typeLabels.length > 0 || dsLabels.length > 0) {
    chartsRow.style.display = 'grid';
  } else {
    chartsRow.style.display = 'none';
  }

  // --- Chart 1: Field type distribution doughnut ---
  if (typeLabels.length > 0) {
    new Chart(document.getElementById('chartFieldTypes'), {
      type: 'doughnut',
      data: {
        labels: typeLabels,
        datasets: [{
          data: typeValues,
          backgroundColor: palette.slice(0, typeLabels.length),
          borderWidth: 3,
          borderColor: '#ffffff',
          hoverOffset: 8
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: { right: 8 } },
        plugins: {
          legend: {
            position: 'bottom',
            labels: {
              font: { family: "'Inter', sans-serif", size: 11, weight: '500' },
              color: '#3730a3',
              boxWidth: 10,
              boxHeight: 10,
              borderRadius: 3,
              padding: 14,
              usePointStyle: true,
              pointStyleWidth: 10
            }
          },
          tooltip: {
            callbacks: {
              label: function(ctx) {
                var pct = total > 0 ? Math.round((ctx.raw / total) * 100) : 0;
                return '  ' + ctx.label + ': ' + ctx.raw + ' (' + pct + '%)';
              }
            }
          }
        },
        cutout: '65%'
      }
    });
  }

  // --- Chart 2: Columns per datasource horizontal bar ---
  if (dsLabels.length > 0) {
    // Set height on the wrapper div, not the canvas — avoids Chart.js hover resize bug
    var barHeight = Math.max(160, dsLabels.length * 44);
    document.getElementById('chartDatasourceWrap').style.height = barHeight + 'px';

    new Chart(document.getElementById('chartDatasourceCols'), {
      type: 'bar',
      data: {
        labels: dsLabels,
        datasets: [{
          label: 'Columns',
          data: dsCols,
          backgroundColor: palette.slice(0, dsLabels.length).map(function(c) {
            return c + 'cc'; // add alpha
          }),
          borderColor: palette.slice(0, dsLabels.length),
          borderWidth: 1,
          borderRadius: 6,
          borderSkipped: false
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: function(items) { return dsFullNames[items[0].dataIndex]; },
              label: function(ctx) { return '  ' + ctx.raw + ' columns'; }
            }
          }
        },
        scales: {
          x: {
            grid: { color: 'rgba(124,58,237,0.07)' },
            ticks: { font: { family: "'Inter', sans-serif", size: 11 }, color: '#818cf8' },
            border: { display: false }
          },
          y: {
            grid: { display: false },
            ticks: {
              font: { family: "'Inter', sans-serif", size: 11 },
              color: '#3730a3'
            },
            border: { display: false }
          }
        }
      }
    });
  }
  } catch (chartErr) {
    console.warn('[BIM-AI] Chart rendering failed (non-critical):', chartErr);
  }
}

/* History panel helpers */
function _escHist(s) {
  var d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}
function _escAttr(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
