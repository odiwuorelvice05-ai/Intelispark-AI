/* Intelispark AI — live intelligence test bench. */
(function () {
  const BACKEND = '/api';

  function renderIntelligence(p) {
    const examples = [
      'How much is the Samsung Galaxy S25?',
      'Do you have any phones under 30000?',
      'Which phone is best for gaming?',
      'I want to buy the iPhone 15.'
    ];

    p.innerHTML = head(
      'Test Intelispark',
      'Send a customer message through the real intelligence loop and inspect what the engine understood.',
      '<span class="pill">LIVE ENGINE</span>'
    ) + `
      <div class="ai-console">
        <section class="card ai-chat-card">
          <div class="section-kicker">CUSTOMER SIMULATOR</div>
          <h3>Ask as a customer</h3>
          <p class="ai-muted">The request is evaluated against this shop's real Supabase catalog.</p>
          <div class="ai-examples">${examples.map(x => `<button class="ghost ai-example" type="button">${esc(x)}</button>`).join('')}</div>
          <form id="aiTestForm" class="ai-form">
            <textarea id="aiMessage" rows="5" required placeholder="e.g. Do you have a Samsung phone under KES 30,000 with a good camera?"></textarea>
            <div class="form-actions"><span class="ai-hint">No external AI API required.</span><button class="primary" id="aiSend" type="submit">Run intelligence →</button></div>
          </form>
          <div id="aiReply" class="ai-result" hidden></div>
        </section>
        <aside class="card ai-inspector">
          <div class="section-kicker">ENGINE INSPECTOR</div>
          <h3>What Intelispark sees</h3>
          <div id="aiInspector" class="ai-inspector-body">
            <div class="empty">Run a message to inspect intent, entities, sales signals and catalog matches.</div>
          </div>
        </aside>
      </div>`;

    document.querySelectorAll('.ai-example').forEach(btn => {
      btn.addEventListener('click', () => { $('#aiMessage').value = btn.textContent; $('#aiMessage').focus(); });
    });
    $('#aiTestForm')?.addEventListener('submit', runIntelligence);
  }

  function showInspector(data) {
    const entities = data.intelligence?.entities || {};
    const signal = data.intelligence?.sales_signal || {};
    $('#aiInspector').innerHTML = `
      <div class="ai-fact"><span>Intent</span><b>${esc(data.intelligence?.intent || '—')}</b></div>
      <div class="ai-fact"><span>Confidence</span><b>${Math.round(Number(data.intelligence?.confidence || 0) * 100)}%</b></div>
      <div class="ai-fact"><span>Brands</span><b>${esc((entities.brands || []).join(', ') || 'None detected')}</b></div>
      <div class="ai-fact"><span>Budget</span><b>${entities.budget_max != null ? money(entities.budget_max) : 'None detected'}</b></div>
      <div class="ai-fact"><span>Condition</span><b>${esc(entities.condition || 'Any')}</b></div>
      <div class="ai-fact"><span>Priorities</span><b>${esc((entities.priorities || []).join(', ') || 'None detected')}</b></div>
      <div class="ai-fact"><span>Purchase intent</span><b>${signal.purchase_intent ? 'Detected' : 'Not detected'}</b></div>
      <div class="ai-fact"><span>Catalog matches</span><b>${Number(data.intelligence?.products_considered || 0)}</b></div>`;
  }

  async function runIntelligence(e) {
    e.preventDefault();
    const button = $('#aiSend');
    const message = $('#aiMessage')?.value.trim();
    if (!message || !APP.business || !APP.user) return;
    button.disabled = true;
    button.textContent = 'Thinking…';
    $('#aiReply').hidden = false;
    $('#aiReply').innerHTML = '<div class="ai-loading">Retrieving business knowledge and reasoning over the request…</div>';
    try {
      const session = await APP.supabase.auth.getSession();
      const token = session.data?.session?.access_token;
      if (!token) throw new Error('Your session has expired. Please sign in again.');

      const customer = APP.customers[0];
      if (!customer) throw new Error('Add at least one customer before testing the conversation engine.');

      const response = await fetch(`${BACKEND}/sales/reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ business_id: APP.business.id, customer_id: customer.id, customer_message: message })
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `Intelligence request failed (${response.status}).`);
      $('#aiReply').innerHTML = `<div class="ai-reply-label">INTELISPARK RESPONSE</div><div class="ai-reply-text">${esc(payload.reply || '')}</div>`;
      showInspector(payload);
      await loadData();
    } catch (error) {
      $('#aiReply').innerHTML = `<div class="ai-error">${esc(error.message || 'Could not run intelligence.')}</div>`;
    } finally {
      button.disabled = false;
      button.textContent = 'Run intelligence →';
    }
  }

  window.renderAI = renderIntelligence;
})();
