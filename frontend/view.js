/**
 * yzli/kanban — Frontend view
 * Board kanban avec colonnes drag-and-drop (stub — full DnD à implémenter).
 */
(function () {
  const COLUMNS = ['Backlog', 'In Progress', 'Done', 'Live'];
  const COL_ICONS = { 'Backlog': 'ph-tray', 'In Progress': 'ph-spinner', 'Done': 'ph-check', 'Live': 'ph-wave-sine' };

  const view = document.createElement('div');
  view.id = 'view-kanban-v2';
  view.className = 'view module-view';
  view.innerHTML = `
    <div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5rem">
        <h1 style="font-size:1.4rem">Kanban</h1>
        <div style="display:flex;gap:0.5rem;align-items:center">
          <select id="kv2-client-filter" onchange="kanbanV2Load()" style="background:var(--surface);border:1px solid var(--border);padding:0.4rem;border-radius:6px;color:var(--text);font-size:0.8rem">
            <option value="">Tous les clients</option>
          </select>
          <button onclick="kanbanV2NewTask()" style="background:var(--accent);color:#fff;border:none;padding:0.5rem 1rem;border-radius:6px;cursor:pointer;font-size:0.84rem">
            + Tâche
          </button>
        </div>
      </div>
      <div id="kv2-board" style="display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;align-items:start"></div>
    </div>`;
  document.getElementById('main').appendChild(view);

  async function kanbanV2Load() {
    const clientFilter = document.getElementById('kv2-client-filter')?.value || '';
    const params = clientFilter ? `?client_slug=${clientFilter}` : '';
    try {
      const board = await mcApi(`/api/kanban-v2${params}`);
      const el = document.getElementById('kv2-board');
      el.innerHTML = COLUMNS.map(col => `
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:1rem">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem">
            <span style="font-weight:600;font-size:0.9rem">
              <i class="ph-light ${COL_ICONS[col]}"></i> ${col}
            </span>
            <span style="font-size:0.75rem;background:var(--accent-dim);padding:0.15rem 0.4rem;border-radius:4px">${(board[col]||[]).length}</span>
          </div>
          <div id="kv2-col-${col.replace(' ','-')}">
            ${(board[col]||[]).map(card => `
              <div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:0.75rem;margin-bottom:0.5rem">
                <div style="font-weight:500;font-size:0.85rem;margin-bottom:0.25rem">${card.title}</div>
                <div style="font-size:0.72rem;color:var(--muted)">${card.client_slug || '—'} · ${card.priority}</div>
                <div style="display:flex;gap:0.5rem;margin-top:0.5rem">
                  ${col !== 'Done' && col !== 'Live' ? `
                    <button onclick="kanbanV2Move(${card.id}, '${nextCol(col)}')"
                      style="font-size:0.7rem;padding:0.2rem 0.4rem;border:1px solid var(--border);border-radius:4px;background:transparent;color:var(--muted);cursor:pointer">
                      → ${nextCol(col)}
                    </button>` : ''}
                  <button onclick="kanbanV2Delete(${card.id})"
                    style="font-size:0.7rem;padding:0.2rem 0.4rem;border:1px solid #e74c3c33;border-radius:4px;background:transparent;color:#e74c3c;cursor:pointer">
                    ✕
                  </button>
                </div>
              </div>`).join('')}
          </div>
        </div>`).join('');
    } catch (e) { console.error('[kanban-v2]', e); }
  }

  function nextCol(col) {
    const idx = COLUMNS.indexOf(col);
    return COLUMNS[Math.min(idx + 1, COLUMNS.length - 1)];
  }

  window.kanbanV2Load = kanbanV2Load;
  window.kanbanV2Move = async (id, toCol) => {
    await mcApi(`/api/kanban-v2/tasks/${id}/move`, { method: 'POST', body: { card_id: id, to_column: toCol } });
    kanbanV2Load();
  };
  window.kanbanV2Delete = async (id) => {
    if (!confirm('Supprimer cette tâche ?')) return;
    await mcApi(`/api/kanban-v2/tasks/${id}`, { method: 'DELETE' });
    kanbanV2Load();
  };
  window.kanbanV2NewTask = () => {
    const title = prompt('Titre de la tâche :');
    if (!title) return;
    mcApi('/api/kanban-v2/tasks', { method: 'POST', body: { title, column_name: 'Backlog' } })
      .then(() => kanbanV2Load());
  };

  // WS live update
  mcBus.on(msg => {
    if (['task.created','task.moved','task.deleted','task.updated'].includes(msg.event)) {
      kanbanV2Load();
    }
  });

  document.addEventListener('click', e => {
    if (e.target.closest('[data-view="kanban-v2"]')) kanbanV2Load();
  });
})();
