/* results-warnings.js — Warnings review page */

/* Load session from sessionStorage or server — shows error if missing */
(async function() {
  try {
  if (!(await loadSession())) {
    document.getElementById('errorState').classList.add('on');
    return;
  }

  document.getElementById('warningsContent').style.display = 'flex';

  /* Populate header from session */
  var dt    = new Date(session.timestamp);
  var dtStr = dt.toLocaleDateString('en-GB', {day:'2-digit',month:'short',year:'numeric'})
            + ' \u00B7 ' + dt.toLocaleTimeString('en-GB', {hour:'2-digit',minute:'2-digit'});
  var hdrEl = document.getElementById('warnPageTitle');
  if (hdrEl) hdrEl.textContent = (session.filename || 'Workbook') + ' \u2014 Warnings';
  var metaEl = document.getElementById('warnMeta');
  if (metaEl) metaEl.textContent = '\u{1F550} ' + dtStr + '  \u00B7  \u{1F4C4} ' + (session.filename || '');
  } catch (err) { showRenderError(err); }
})();

/* ══════════════════════════════════════════════════
   Warnings Review
   ══════════════════════════════════════════════════ */

function toggleFixCard(header) {
  const card = header.closest('.fix-card');
  card.classList.toggle('open');
}

function renderWarningsReview(review) {
  const panel    = document.getElementById('warningsPanel');
  const sub      = document.getElementById('warningsPanelSub');
  const summary  = document.getElementById('warningsSummary');
  const cards    = document.getElementById('warningsFixCards');

  // Summary block
  if (review.summary) {
    summary.textContent = review.summary;
    summary.style.display = 'block';
  }

  // Fix cards
  cards.innerHTML = '';
  const fixes = review.fixes || [];

  if (fixes.length === 0) {
    sub.textContent = 'No actionable warnings found — migration looks clean!';
    cards.innerHTML = '<div class="warnings-summary">No fix suggestions returned.</div>';
  } else {
    sub.textContent = fixes.length + ' fix suggestion' + (fixes.length !== 1 ? 's' : '') + ' ready';
    fixes.forEach(function(fix, idx) {
      const priority = fix.priority || 'Medium';
      const steps    = Array.isArray(fix.fix_steps) ? fix.fix_steps : [];
      const card     = document.createElement('div');
      card.className = 'fix-card';

      // Auto-open High priority cards
      if (priority === 'High') card.classList.add('open');

      card.innerHTML =
        '<div class="fix-card-header" onclick="toggleFixCard(this)">' +
          '<span class="fix-priority ' + esc(priority) + '">' + esc(priority) + '</span>' +
          '<span class="fix-code">' + esc(fix.warning_code || '—') + '</span>' +
          '<span class="fix-agent">' + esc((fix.agent || '').replace(/_agent$/, '').replace(/_/g, '\u00A0')) + '</span>' +
          '<span class="fix-chevron">&#9660;</span>' +
        '</div>' +
        '<div class="fix-card-body">' +
          (fix.original_message
            ? '<div class="fix-explanation" style="font-style:italic;color:var(--muted);font-size:12px;">' + esc(fix.original_message) + '</div>'
            : '') +
          (fix.issue_explanation
            ? '<div class="fix-explanation">' + esc(fix.issue_explanation) + '</div>'
            : '') +
          (steps.length > 0
            ? '<div class="fix-steps-label">Fix steps</div>' +
              '<ol class="fix-steps">' +
                steps.map(function(s) { return '<li>' + esc(s) + '</li>'; }).join('') +
              '</ol>'
            : '') +
          '<div class="fix-meta">' +
            (fix.effort ? '<span class="fix-meta-pill">Effort: ' + esc(fix.effort) + '</span>' : '') +
            (fix.severity ? '<span class="fix-meta-pill">Severity: ' + esc(fix.severity) + '</span>' : '') +
            (fix.manual_review_required ? '<span class="fix-meta-pill" style="color:var(--amber)">Manual review required</span>' : '') +
          '</div>' +
        '</div>';

      cards.appendChild(card);
    });
  }

  panel.classList.add('on');
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

document.getElementById('btnReviewWarnings').addEventListener('click', async function() {
  const btn          = document.getElementById('btnReviewWarnings');
  const overlay      = document.getElementById('reviewOverlay');
  const workbookName = (session && session.filename) ? session.filename.replace(/\.(twbx?|twb)$/i, '') : '';

  if (!workbookName) {
    alert('Could not determine workbook name. Please run the extraction first.');
    return;
  }

  btn.disabled = true;
  overlay.classList.add('on');

  try {
    // Step 1: collect warnings from disk (fast, no LLM)
    const collectResp = await fetch('/warnings-collect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workbook_name: workbookName }),
    });
    if (!collectResp.ok) {
      const errText = await collectResp.text();
      throw new Error(errText || 'HTTP ' + collectResp.status);
    }
    const warningsPayload = await collectResp.json();

    if (warningsPayload.total_warnings === 0) {
      overlay.classList.remove('on');
      renderWarningsReview({ summary: 'No migration warnings found in any agent output.', fixes: [] });
      btn.disabled = false;
      return;
    }

    // Step 2: submit to LLM for review via SSE stream
    const reviewResp = await fetch('/warnings-review-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ warnings: warningsPayload }),
    });
    if (!reviewResp.ok) {
      const errText = await reviewResp.text();
      throw new Error(errText || 'HTTP ' + reviewResp.status);
    }

    const reader  = reviewResp.body.getReader();
    const decoder = new TextDecoder();
    let buffer    = '';
    let reviewData = null;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const dataLine = raw.split('\n').find(function(l) { return l.startsWith('data:'); });
        if (!dataLine) continue;
        let msg;
        try { msg = JSON.parse(dataLine.slice(5).trim()); } catch { continue; }

        if (msg.state === 'complete') {
          reviewData = msg.review;
        } else if (msg.state === 'error') {
          throw new Error(msg.message || 'Review agent error');
        }
      }
    }

    if (!reviewData) throw new Error('Review stream ended without a result');

    overlay.classList.remove('on');
    renderWarningsReview(reviewData);

  } catch (err) {
    overlay.classList.remove('on');
    btn.disabled = false;
    alert('Warnings review failed: ' + err.message);
  }
});

