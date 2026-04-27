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
  const sourceFormat = String(session.source_format || analysis.source_format || 'tableau').toLowerCase();
  const workbookName = session.workbook_name || (session.filename || '').replace(/\.\w+$/, '');
  const resultId = new URLSearchParams(location.search).get('id') || session.id || '';

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

  if (sourceFormat === 'pbip') {
    await renderPowerBiAnalysis(workbookName, resultId);
    return;
  }

  // ── Parse data ──
  const datasources = (analysis.datasources || []).filter(ds => ds.columns && ds.columns.length > 0);
  const worksheets  = analysis.worksheets  || [];
  const dashboards  = analysis.dashboards  || [];
  const parameters  = analysis.parameters  || [];

  const allColumns  = datasources.flatMap(ds => ds.columns || []);
  const allCalc     = datasources.flatMap(ds =>
    (ds.calculated_fields || []).map(cf => Object.assign({ owner_datasource: ds.caption || ds.name || '\u2014' }, cf))
  );
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

  _setSectionCopyTableau();

  // ── Data Overview charts ──
  renderCharts('tableau', analysis);

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
      <td><span class="pill dim">${esc(cf.owner_datasource || '\u2014')}</span></td>
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

  // ── Pages & visuals ──
  document.getElementById('badgeDashboards').textContent = dashboards.length + ' pages';
  const dbBody = document.getElementById('dashboardBody');
  renderTableauPageVisualTable(dashboards, worksheets, dbBody);
  enableTableSort(document.getElementById('tablePageVisuals'));
  enableTableSearch('tablePageVisuals');

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

function renderCharts(sourceFormat, data) {
  try {
  const chartsRow = document.getElementById('chartsRow');
  if (!chartsRow) return;
  var chart1Title = document.getElementById('chartCard1Title');
  var chart1Sub = document.getElementById('chartCard1Sub');
  var chart2Title = document.getElementById('chartCard2Title');
  var chart2Sub = document.getElementById('chartCard2Sub');

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
  var typeLabels = [];
  var typeValues = [];
  var total = 0;
  var dsLabels = [];
  var dsCols = [];
  var dsFullNames = [];

  if (sourceFormat === 'pbip') {
    var semanticModel = (data && data.semantic_model) || {};
    var report = (data && data.report) || {};
    var tables = semanticModel.tables || [];
    var allColumns = tables.flatMap(function(table) { return table.columns || []; });
    var physicalColumns = allColumns.filter(function(column) { return !column.is_calculated; }).length;
    var calculatedColumns = allColumns.filter(function(column) { return !!column.is_calculated; }).length;
    var measures = tables.reduce(function(sum, table) { return sum + ((table.measures || []).length); }, 0);
    var pages = report.pages || [];
    var visuals = pages.reduce(function(sum, page) { return sum + ((page.visuals || []).length); }, 0);
    var expressions = (semanticModel.expressions || []).length;

    var typeEntriesPbip = [
      ['Tables', tables.length],
      ['Columns', physicalColumns],
      ['Calc Columns', calculatedColumns],
      ['Measures', measures],
      ['Visuals', visuals],
      ['Pages', pages.length],
      ['Queries', expressions],
    ].filter(function(entry) { return entry[1] > 0; });

    typeLabels = typeEntriesPbip.map(function(entry) { return entry[0]; });
    typeValues = typeEntriesPbip.map(function(entry) { return entry[1]; });
    total = typeValues.reduce(function(sum, value) { return sum + value; }, 0);

    var topTables = tables
      .map(function(table) {
        return {
          name: table.name,
          caption: _pbipFriendlyTableCaption(table.name) || table.name,
          count: (table.columns || []).length + (table.measures || []).length,
        };
      })
      .filter(function(table) { return table.count > 0; })
      .sort(function(a, b) { return b.count - a.count; })
      .slice(0, 10);

    dsLabels = topTables.map(function(table) { return truncate(table.caption || table.name || 'Unknown', 28); });
    dsCols = topTables.map(function(table) { return table.count; });
    dsFullNames = topTables.map(function(table) { return table.caption || table.name || 'Unknown'; });

    if (chart1Title) chart1Title.textContent = 'Semantic Object Mix';
    if (chart1Sub) chart1Sub.textContent = 'Key extracted PBIP objects by category';
    if (chart2Title) chart2Title.textContent = 'Fields per Table';
    if (chart2Sub) chart2Sub.textContent = 'Columns and measures grouped by table';
  } else {
    const datasources = data.datasources || [];
    const worksheets = data.worksheets || [];
    const dashboards = data.dashboards || [];
    const parameters = data.parameters || [];
    const allColumns = datasources.flatMap(function(ds) { return ds.columns || []; });
    const allCalc = datasources.reduce(function(sum, ds) { return sum + ((ds.calculated_fields || []).length); }, 0);

    const typeEntriesTableau = [
      ['Sources', datasources.length],
      ['Columns', allColumns.length],
      ['Calculations', allCalc],
      ['Visuals', worksheets.length],
      ['Pages', dashboards.length],
      ['Parameters', parameters.length],
    ].filter(function(entry) { return entry[1] > 0; });

    typeLabels = typeEntriesTableau.map(function(entry) { return entry[0]; });
    typeValues = typeEntriesTableau.map(function(entry) { return entry[1]; });
    total = typeValues.reduce(function(sum, value) { return sum + value; }, 0);

    var allDs = datasources.filter(function(ds) {
      return ((ds.columns || []).length + (ds.calculated_fields || []).length) > 0;
    });
    allDs.sort(function(a, b) {
      return (((b.columns || []).length + (b.calculated_fields || []).length) - ((a.columns || []).length + (a.calculated_fields || []).length));
    });
    allDs = allDs.slice(0, 10);

    dsLabels = allDs.map(function(ds) { return truncate(ds.caption || ds.name || 'Unknown', 28); });
    dsCols = allDs.map(function(ds) { return (ds.columns || []).length + (ds.calculated_fields || []).length; });
    dsFullNames = allDs.map(function(ds) { return ds.caption || ds.name || 'Unknown'; });

    if (chart1Title) chart1Title.textContent = 'Semantic Object Mix';
    if (chart1Sub) chart1Sub.textContent = 'Key extracted Tableau objects by category';
    if (chart2Title) chart2Title.textContent = 'Fields per Source';
    if (chart2Sub) chart2Sub.textContent = 'Columns and calculations grouped by data source';
  }

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
              label: function(ctx) { return '  ' + ctx.raw + ' fields'; }
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

async function renderPowerBiAnalysis(workbookName, resultId) {
  const pbip = analysis.pbip || {};
  const semanticModel = pbip.semantic_model || {};
  const report = pbip.report || {};
  const tables = semanticModel.tables || [];
  const allColumns = tables.flatMap(function(table) {
    return (table.columns || []).map(function(column) {
      return Object.assign({ owner_table: table.name }, column);
    });
  });
  const physicalColumns = allColumns.filter(function(column) { return !column.is_calculated; });
  const calculatedColumns = allColumns.filter(function(column) { return !!column.is_calculated; });
  const allMeasures = tables.flatMap(function(table) {
    return (table.measures || []).map(function(measure) {
      return Object.assign({ owner_table: table.name }, measure);
    });
  });
  const allExpressions = semanticModel.expressions || [];
  const pages = report.pages || [];
  const allVisuals = pages.flatMap(function(page) {
    return (page.visuals || []).map(function(visual) {
      return Object.assign({ page_name: page.display_name || page.name }, visual);
    });
  });
  const warnings = pbip.warnings || [];

  document.getElementById('pageTitle').textContent = (session.filename || 'PBIP Package') + ' (PBIP)';
  document.getElementById('generateFddBtn').style.display = 'none';
  document.getElementById('migrateBtn').style.display = 'none';
  document.getElementById('fddSection').style.display = 'none';
  document.getElementById('tabDocs').style.display = 'none';
  var docsBtn = document.querySelector('.tab-btn[data-tab="docs"]');
  if (docsBtn) docsBtn.style.display = 'none';
  var calcColumnsCard = document.getElementById('cardCalcColumns');
  if (calcColumnsCard) calcColumnsCard.style.display = '';
  document.getElementById('cardParams').style.display = '';

  _setSectionCopyPbip();
  renderCharts('pbip', pbip);

  const kpis = [
    { label:'Model Tables', value: tables.length, color:'blue', icon:'\u{1F4C1}' },
    { label:'Physical Columns', value: physicalColumns.length, color:'teal', icon:'#\uFE0F\u20E3' },
    { label:'Calc Columns', value: calculatedColumns.length, color:'rose', icon:'fx' },
    { label:'Measures', value: allMeasures.length, color:'purple', icon:'\u03A3' },
    { label:'Pages', value: pages.length, color:'amber', icon:'\u{1F4C4}' },
    { label:'Visuals', value: allVisuals.length, color:'green', icon:'\u{1F5BC}\uFE0F' },
    { label:'Relationships', value: (semanticModel.relationships || []).length, color:'indigo', icon:'\u{1F517}' },
    { label:'Queries', value: allExpressions.length, color:'rose', icon:'\u2699\uFE0F' },
    { label:'Warnings', value: warnings.length, color:'teal', icon:'\u26A0\uFE0F' },
  ];
  const kpiGrid = document.getElementById('kpiGrid');
  kpiGrid.innerHTML = '';
  kpiGrid.style.gridTemplateColumns = `repeat(${Math.min(kpis.length,4)},1fr)`;
  var kpiValueEls = [];
  kpis.forEach(function(k, i) {
    const el = document.createElement('div');
    el.className = `kpi ${k.color}`;
    el.style.animationDelay = (i * 0.05) + 's';
    el.innerHTML = `<div class="kpi-icon">${k.icon}</div>
                    <div class="kpi-value" data-target="${k.value}">0</div>
                    <div class="kpi-label">${k.label}</div>`;
    kpiGrid.appendChild(el);
    kpiValueEls.push({ el: el.querySelector('.kpi-value'), target: k.value });
  });
  var kpiAnimated = false;
  var kpiObserver = new IntersectionObserver(function(entries) {
    entries.forEach(function(entry) {
      if (entry.isIntersecting && !kpiAnimated) {
        kpiAnimated = true;
        kpiValueEls.forEach(function(item) { animateValue(item.el, item.target, 1200); });
        kpiObserver.disconnect();
      }
    });
  }, { threshold: 0.2 });
  kpiObserver.observe(kpiGrid);

  document.getElementById('badgeDatasources').textContent = tables.length + ' tables';
  const dsTbody = document.querySelector('#tableDatasources tbody');
  dsTbody.innerHTML = '';
  tables.forEach(function(table) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${_pbipTableCell(table.name)}</td>
      <td><span class="pill dim">${esc(_pbipTableTypeLabel(table))}</span></td>
      <td><span style="font-family:var(--mono);font-size:11px">${esc(_pbipTableModeLabel(table))}</span></td>
      <td><span class="pill meas">${(table.columns||[]).length}</span></td>
      <td><span class="pill calc">${(table.measures||[]).length}</span></td>
    `;
    dsTbody.appendChild(tr);
  });
  enableTableSort(document.getElementById('tableDatasources'));
  enableTableSearch('tableDatasources');

  document.getElementById('badgeColumns').textContent = physicalColumns.length + ' columns';
  const colTbody = document.querySelector('#tableColumns tbody');
  colTbody.innerHTML = '';
  physicalColumns.forEach(function(col) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${_pbipTableCell(col.owner_table)}</td>
      <td>${fieldNameCell(col.name, col.caption)}</td>
      <td>${dtypePill(col.data_type || col.datatype)}</td>
      <td style="font-family:var(--mono);font-size:11px;color:var(--muted)">${esc(_displayText(col.source_column))}</td>
    `;
    colTbody.appendChild(tr);
  });
  if (physicalColumns.length === 0) {
    colTbody.innerHTML = `<tr><td colspan="4" style="color:var(--muted);font-style:italic;text-align:center;padding:24px">No physical columns found</td></tr>`;
  }
  enableTableSort(document.getElementById('tableColumns'));
  enableTableSearch('tableColumns');

  document.getElementById('badgeCalcColumns').textContent = calculatedColumns.length + ' columns';
  const calcColumnsTbody = document.querySelector('#tableCalcColumns tbody');
  calcColumnsTbody.innerHTML = '';
  calculatedColumns.forEach(function(column) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${_pbipTableCell(column.owner_table)}</td>
      <td>${fieldNameCell(column.name, column.caption)}</td>
      <td>${dtypePill(column.data_type || column.datatype)}</td>
      <td>${_formulaHtml(column.expression)}</td>
    `;
    calcColumnsTbody.appendChild(tr);
  });
  if (calculatedColumns.length === 0) {
    calcColumnsTbody.innerHTML = `<tr><td colspan="4" style="color:var(--muted);font-style:italic;text-align:center;padding:24px">No calculated columns found</td></tr>`;
  }
  enableTableSort(document.getElementById('tableCalcColumns'));
  enableTableSearch('tableCalcColumns');

  document.getElementById('badgeCalc').textContent = allMeasures.length + ' measures';
  const calcTbody = document.querySelector('#tableCalc tbody');
  calcTbody.innerHTML = '';
  if (allMeasures.length === 0) {
    calcTbody.innerHTML = `<tr><td colspan="4" style="color:var(--muted);font-style:italic;text-align:center;padding:24px">No measures found</td></tr>`;
  }
  allMeasures.forEach(function(measure) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${_pbipTableCell(measure.owner_table)}</td>
      <td>${fieldNameCell(measure.name, measure.caption)}</td>
      <td><span class="pill dim">${esc(_displayText(measure.format_string))}</span></td>
      <td>${_formulaHtml(measure.expression)}</td>
    `;
    calcTbody.appendChild(tr);
  });
  enableTableSort(document.getElementById('tableCalc'));
  enableTableSearch('tableCalc');

  document.getElementById('badgeWorksheets').textContent = pages.length + ' pages';
  const wsTbody = document.querySelector('#tableWorksheets tbody');
  wsTbody.innerHTML = '';
  pages.forEach(function(page) {
    const visualTypes = (page.visuals || []).map(function(v) { return v.visual_type; }).filter(Boolean);
    const topTypes = Array.from(new Set(visualTypes)).slice(0, 3).join(', ') || '\u2014';
    const filterCount = (page.visuals || []).reduce(function(total, visual) {
      return total + ((visual.filters || []).length);
    }, 0);
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><strong>${esc(page.display_name || page.name)}</strong></td>
      <td><span class="pill dim">${esc(page.display_option || '\u2014')}</span></td>
      <td style="font-size:12px;color:var(--ink2)">${esc(String((page.visuals || []).length))}</td>
      <td style="font-size:12px;color:var(--ink2)">${esc(topTypes)}</td>
      <td>${filterCount > 0 ? `<span class="pill meas">${filterCount}</span>` : '<span style="color:var(--muted)">\u2014</span>'}</td>
    `;
    wsTbody.appendChild(tr);
  });
  enableTableSort(document.getElementById('tableWorksheets'));
  enableTableSearch('tableWorksheets');

  const totalVisuals = pages.reduce(function(total, page) {
    return total + ((page.visuals || []).length);
  }, 0);
  document.getElementById('badgeDashboards').textContent = totalVisuals + ' visuals';
  const dbBody = document.getElementById('dashboardBody');
  renderPbipPageVisualTable(pages, dbBody);
  enableTableSort(document.getElementById('tablePageVisuals'));
  enableTableSearch('tablePageVisuals');

  document.getElementById('badgeParams').textContent = allExpressions.length;
  const pTbody = document.querySelector('#tableParams tbody');
  pTbody.innerHTML = '';
  allExpressions.forEach(function(expr) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td style="font-family:var(--mono);font-size:11px">${esc(_displayText(expr.name))}</td>
      <td><span class="pill dim">${esc(_pbipExpressionKindLabel(expr.kind))}</span></td>
      <td>${dtypePill(expr.result_type || expr.type)}</td>
      <td style="font-family:var(--mono);font-size:11px">${esc(_displayText(expr.query_group))}</td>
      <td>${_formulaHtml(expr.expression)}</td>
    `;
    pTbody.appendChild(tr);
  });
  if (allExpressions.length === 0) {
    pTbody.innerHTML = `<tr><td colspan="5" style="color:var(--muted);font-style:italic;text-align:center;padding:24px">No queries or expressions found</td></tr>`;
  }
  enableTableSort(document.getElementById('tableParams'));
  enableTableSearch('tableParams');

  document.getElementById('rawPre').textContent = JSON.stringify(analysis, null, 2);
  document.getElementById('rawToggle').addEventListener('click', function() {
    const box = document.getElementById('rawBox');
    const chevron = document.getElementById('rawChevron');
    const open = box.style.display === 'block';
    box.style.display = open ? 'none' : 'block';
    chevron.classList.toggle('open', !open);
  });
  document.getElementById('copyRawBtn').addEventListener('click', function() {
    navigator.clipboard.writeText(JSON.stringify(analysis, null, 2)).then(function() {
      const btn = document.getElementById('copyRawBtn');
      btn.childNodes[btn.childNodes.length - 1].textContent = ' Copied!';
      setTimeout(function() { btn.childNodes[btn.childNodes.length - 1].textContent = ' Copy JSON'; }, 2000);
    });
  });

  var tabCountData = document.getElementById('tabCountData');
  if (tabCountData) {
    tabCountData.textContent = tables.length + physicalColumns.length + calculatedColumns.length + allMeasures.length + pages.length + allExpressions.length;
  }
  var tabCountWarnings = document.getElementById('tabCountWarnings');
  if (tabCountWarnings) tabCountWarnings.textContent = warnings.length;
  var warningsTab = document.getElementById('tabWarnings');
  var warningsEmpty = document.getElementById('warningsEmpty');
  if (warningsTab && warningsEmpty) {
    if (warnings.length === 0) {
      warningsEmpty.querySelector('div:last-child').textContent = 'No PBIP extraction warnings.';
    } else {
      warningsEmpty.style.display = 'none';
      var list = document.createElement('div');
      list.style.cssText = 'display:flex;flex-direction:column;gap:10px;padding:16px 20px';
      warnings.forEach(function(w) {
        var item = document.createElement('div');
        item.style.cssText = 'padding:10px 12px;border:1px solid var(--border);border-radius:12px;background:#fff';
        item.innerHTML = '<div style="font-size:12px;font-weight:700;color:var(--amber)">' + esc(w.code || 'warning') + '</div>' +
          '<div style="font-size:13px;color:var(--ink2);margin-top:4px">' + esc(w.message || '') + '</div>';
        list.appendChild(item);
      });
      warningsTab.appendChild(list);
    }
  }

  try {
    const resp = await fetch('/api/history/' + encodeURIComponent(workbookName));
    if (!resp.ok) return;
    const runs = await resp.json();
    if (!runs || runs.length === 0) return;

    var card = document.getElementById('cardHistory');
    var badge = document.getElementById('badgeHistory');
    var list = document.getElementById('historyRunsList');
    if (!card || !list) return;

    card.style.display = 'block';
    badge.textContent = runs.length;

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
}

var PBIP_TECHNICAL_VISUAL_TYPES = new Set(['shape', 'actionbutton', 'image', 'textbox', 'pagenavigator', 'group']);

function _displayText(value) {
  return value === null || value === undefined || value === '' ? '\u2014' : String(value);
}

function _splitIdentifierWords(value) {
  return String(value || '')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function _titleCaseWords(value) {
  return _splitIdentifierWords(value).replace(/\b([a-z])/g, function(match) {
    return match.toUpperCase();
  });
}

function _pbipFriendlyTableCaption(tableName) {
  if (!tableName) return null;
  if (/^LocalDateTable_/i.test(tableName)) return 'Auto Date Table';
  if (/^DateTableTemplate_/i.test(tableName)) return 'Template Date Table';
  if (/^Dim[A-Z]/.test(tableName)) return _splitIdentifierWords(tableName.replace(/^Dim/, ''));
  if (/^Fact[A-Z]/.test(tableName)) return _splitIdentifierWords(tableName.replace(/^Fact/, ''));
  return null;
}

function _pbipHideRawTableName(tableName) {
  return /^LocalDateTable_/i.test(tableName || '') || /^DateTableTemplate_/i.test(tableName || '');
}

function _pbipTableCell(tableName) {
  var caption = _pbipFriendlyTableCaption(tableName);
  if (!caption || caption === tableName) return fieldNameCell(tableName, null);
  if (_pbipHideRawTableName(tableName)) {
    return '<div class="field-name-cell"><span class="field-label">' + esc(caption) + '</span></div>';
  }
  return (
    '<div class="field-name-cell">' +
      '<span class="field-label">' + esc(caption) + '</span>' +
      '<span class="field-raw-id field-raw-id--static">' + esc(tableName) + '</span>' +
    '</div>'
  );
}

function _pbipTableSourceTables(table) {
  var refs = new Set();
  (table && table.columns || []).forEach(function(column) {
    var source = String(column && column.source_column || '');
    var match = source.match(/^([^.\[]+)\[/);
    if (!match) return;
    if (match[1] && match[1] !== table.name) refs.add(match[1]);
  });
  return Array.from(refs);
}

function _pbipTableTypeLabel(table) {
  if (table && /^LocalDateTable_/i.test(String(table.name || ''))) return 'auto date';
  var sourceTables = _pbipTableSourceTables(table);
  if (sourceTables.length === 1) return 'calculated table';
  return 'table';
}

function _pbipTableModeLabel(table) {
  var sourceTables = _pbipTableSourceTables(table);
  if (/^LocalDateTable_/i.test(String(table && table.name || ''))) return 'generated';
  if (sourceTables.length === 1) return 'from ' + sourceTables[0];
  return ((table && table.partitions || [])[0] || {}).mode || ((table && table.partitions || [])[0] || {}).kind || '\u2014';
}

function _formulaHtml(expression) {
  return expression
    ? '<span class="calc-formula" title="' + esc(expression) + '">' + highlightFormula(expression) + '</span>'
    : '<span class="formula-code">\u2014</span>';
}

function _pbipExpressionKindLabel(kind) {
  return kind === 'parameter_query' ? 'Parameter Query' : 'Expression';
}

function _pbipVisualLabel(visual) {
  return visual.group_display_name || _titleCaseWords(visual.visual_type || '') || visual.name || 'Visual';
}

function _pbipVisualCell(visual) {
  var rawName = visual.name || '\u2014';
  var displayName = _pbipVisualLabel(visual);
  return fieldNameCell(rawName, displayName && displayName !== rawName ? displayName : null);
}

function _pbipVisualTypeLabel(visual) {
  return _titleCaseWords(visual.visual_type || visual.container_kind || 'visual');
}

function _pbipFieldBindingLabel(binding) {
  return [binding.entity, binding.property].filter(Boolean).join('.') || binding.property || binding.kind || 'binding';
}

function _pbipBindingSummary(visual, maxItems) {
  var bindings = (visual.field_bindings || []).map(_pbipFieldBindingLabel).filter(Boolean);
  if (bindings.length === 0) return 'No field bindings';
  var shown = bindings.slice(0, maxItems);
  return shown.join(', ') + (bindings.length > maxItems ? ' +' + (bindings.length - maxItems) + ' more' : '');
}

function _pbipShortId(value) {
  if (!value) return '\u2014';
  return value.length > 12 ? value.slice(0, 12) + '\u2026' : value;
}

function _isTechnicalPbipVisual(visual) {
  if (visual.container_kind === 'group') return true;
  var visualType = String(visual.visual_type || '').toLowerCase();
  return PBIP_TECHNICAL_VISUAL_TYPES.has(visualType);
}

function _tableauWorksheetFieldSummary(worksheet, maxItems) {
  var fields = []
    .concat((worksheet.cols_shelf || []).map(function(item) { return item.field; }))
    .concat((worksheet.rows_shelf || []).map(function(item) { return item.field; }))
    .filter(Boolean);
  if (fields.length === 0) return 'No field bindings';
  var uniqueFields = Array.from(new Set(fields));
  var shown = uniqueFields.slice(0, maxItems);
  return shown.join(', ') + (uniqueFields.length > maxItems ? ' +' + (uniqueFields.length - maxItems) + ' more' : '');
}

function renderTableauPageVisualTable(dashboards, worksheets, container) {
  container.innerHTML = '';
  var worksheetMap = new Map();
  (worksheets || []).forEach(function(worksheet) {
    worksheetMap.set(worksheet.title || worksheet.name, worksheet);
    worksheetMap.set(worksheet.name, worksheet);
  });

  var rows = [];
  (dashboards || []).forEach(function(dashboard) {
    var sheets = Array.from(new Set(dashboard.sheets || []));
    if (sheets.length === 0) {
      rows.push({ dashboard: dashboard, worksheet: null, zone: null });
      return;
    }
    sheets.forEach(function(sheetName) {
      rows.push({
        dashboard: dashboard,
        worksheet: worksheetMap.get(sheetName) || null,
        zone: (dashboard.layout_zones || []).find(function(zone) { return zone.name === sheetName; }) || null,
        sheetName: sheetName,
      });
    });
  });

  if (rows.length === 0) {
    container.innerHTML = '<tr><td colspan="5" style="color:var(--muted);font-style:italic;text-align:center;padding:24px">No pages or visuals found</td></tr>';
    return;
  }

  rows.forEach(function(item) {
    var dashboard = item.dashboard;
    var worksheet = item.worksheet;
    var tr = document.createElement('tr');
    tr.innerHTML =
      '<td><strong>' + esc(dashboard.name || '\u2014') + '</strong></td>' +
      '<td><span class="pill meas">Business</span></td>' +
      '<td><strong>' + esc((worksheet && (worksheet.title || worksheet.name)) || item.sheetName || '\u2014') + '</strong></td>' +
      '<td><span class="pill dim">' + esc((worksheet && worksheet.mark_type) || 'worksheet') + '</span></td>' +
      '<td class="pbip-fields-cell">' + esc(worksheet ? _tableauWorksheetFieldSummary(worksheet, 4) : 'No field bindings') + '</td>';
    container.appendChild(tr);
  });
}

function renderPbipPageVisualTable(pages, container) {
  container.innerHTML = '';
  var rows = [];
  pages.forEach(function(page) {
    (page.visuals || []).forEach(function(visual) {
      rows.push({ page: page, visual: visual });
    });
  });

  rows.sort(function(a, b) {
    var pageA = String(a.page.display_name || a.page.name || '');
    var pageB = String(b.page.display_name || b.page.name || '');
    if (pageA !== pageB) return pageA.localeCompare(pageB);
    var typeA = String(a.visual.visual_type || '');
    var typeB = String(b.visual.visual_type || '');
    if (typeA !== typeB) return typeA.localeCompare(typeB);
    return String(a.visual.name || '').localeCompare(String(b.visual.name || ''));
  });

  if (rows.length === 0) {
    container.innerHTML = '<tr><td colspan="5" style="color:var(--muted);font-style:italic;text-align:center;padding:24px">No page visuals found</td></tr>';
    return;
  }

  rows.forEach(function(item) {
    var page = item.page;
    var visual = item.visual;
    var technical = _isTechnicalPbipVisual(visual);

    var tr = document.createElement('tr');
    tr.innerHTML =
      '<td><strong>' + esc(page.display_name || page.name || '\u2014') + '</strong></td>' +
      '<td><span class="pill ' + (technical ? 'dim' : 'meas') + '">' + esc(technical ? 'Technical' : 'Business') + '</span></td>' +
      '<td>' + _pbipVisualCell(visual) + '</td>' +
      '<td><span class="pill dim">' + esc(_pbipVisualTypeLabel(visual)) + '</span></td>' +
      '<td class="pbip-fields-cell">' + esc(_pbipBindingSummary(visual, 4)) + '</td>';
    container.appendChild(tr);
  });
}

function _setSectionCopyPbip() {
  _setText('#cardDatasources .section-title', 'Semantic Model Tables');
  _setText('#cardDatasources .section-sub', 'Tables from the PBIP semantic model');
  _setHeaderText('tableDatasources', ['Table', 'Type', 'Mode', 'Columns', 'Measures']);

  _setText('#cardColumns .section-title', 'Model Columns');
  _setText('#cardColumns .section-sub', 'Physical columns defined in the semantic model');
  _setHeaderText('tableColumns', ['Table', 'Column', 'Data Type', 'Source Column']);

  _setText('#cardCalcColumns .section-title', 'Calculated Columns');
  _setText('#cardCalcColumns .section-sub', 'Column-level DAX and formulas');
  _setHeaderText('tableCalcColumns', ['Table', 'Column', 'Data Type', 'DAX']);

  _setText('#cardCalc .section-title', 'Measures');
  _setText('#cardCalc .section-sub', 'DAX measures');
  _setHeaderText('tableCalc', ['Table', 'Measure', 'Format', 'DAX']);

  _setText('#cardWorksheets .section-title', 'Report Pages');
  _setText('#cardWorksheets .section-sub', 'PBIP report pages and visual summaries');
  _setHeaderText('tableWorksheets', ['Page', 'Display', 'Visuals', 'Visual Types', 'Filters']);

  _setText('#cardDashboards .section-title', 'Page Visuals');
  _setText('#cardDashboards .section-sub', 'Simple inventory of business and technical/support objects');
  _setHeaderText('tablePageVisuals', ['Page', 'Category', 'Visual', 'Type', 'Fields']);

  _setText('#cardParams .section-title', 'Queries & Expressions');
  _setText('#cardParams .section-sub', 'Model expressions and parameter queries');
  _setHeaderText('tableParams', ['Name', 'Kind', 'Result Type', 'Query Group', 'Definition']);
}

function _setSectionCopyTableau() {
  _setText('#cardDatasources .section-title', 'Queries & Connections');
  _setText('#cardDatasources .section-sub', 'Tableau data sources and source connections');
  _setHeaderText('tableDatasources', ['Query / Source', 'Type', 'Connection', 'Columns', 'Calculations']);

  _setText('#cardColumns .section-title', 'Model Columns');
  _setText('#cardColumns .section-sub', 'Fields available to Tableau visuals');
  _setHeaderText('tableColumns', ['Column', 'Data Type', 'Role', 'Semantic Role']);

  _setText('#cardCalc .section-title', 'Calculations');
  _setText('#cardCalc .section-sub', 'Calculated fields and formulas');
  _setHeaderText('tableCalc', ['Source', 'Calculation', 'Data Type', 'Formula']);

  _setText('#cardWorksheets .section-title', 'Visuals');
  _setText('#cardWorksheets .section-sub', 'Worksheet-level visuals extracted from Tableau');
  _setHeaderText('tableWorksheets', ['Visual', 'Type', 'Columns', 'Rows', 'Filters']);

  _setText('#cardDashboards .section-title', 'Pages & Visuals');
  _setText('#cardDashboards .section-sub', 'Dashboard pages with contained visuals');
  _setHeaderText('tablePageVisuals', ['Page', 'Category', 'Visual', 'Type', 'Fields']);

  _setText('#cardParams .section-title', 'Parameters');
  _setText('#cardParams .section-sub', 'Interactive controls used by Tableau');
}

function _setText(selector, text) {
  var el = document.querySelector(selector);
  if (el) el.textContent = text;
}

function _setHeaderText(tableId, texts) {
  var headers = document.querySelectorAll('#' + tableId + ' thead th');
  headers.forEach(function(th, idx) {
    var indicator = th.querySelector('.sort-indicator');
    th.innerHTML = esc(texts[idx] || '') + (indicator ? ' <span class="sort-indicator">&#9650;&#9660;</span>' : '');
  });
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
