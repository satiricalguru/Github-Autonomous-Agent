import { escapeHtml } from '../dom.js';
/**
 * Tasks Table Component
 */
import { store } from '../state.js';
import { sound } from '../audio.js';
export class TasksTable {
    lastPayload = "";
    containerEl = null;
    searchInputEl = null;
    filterPillsEl = null;
    constructor() {
        this.init();
    }
    init() {
        this.containerEl = document.getElementById('tasksTableBody');
        this.searchInputEl = document.getElementById('taskSearchInput');
        this.filterPillsEl = document.getElementById('taskFilterPills');
        if (this.searchInputEl) {
            this.searchInputEl.addEventListener('input', (e) => {
                store.setState({ searchQuery: e.target.value.toLowerCase() });
            });
        }
        if (this.filterPillsEl) {
            this.filterPillsEl.addEventListener('click', (e) => {
                const target = e.target.closest('.filter-pill');
                if (!target)
                    return;
                sound.playClick();
                const filter = target.dataset.filter || 'all';
                this.filterPillsEl?.querySelectorAll('.filter-pill').forEach(el => el.classList.remove('active'));
                target.classList.add('active');
                store.setState({ taskFilter: filter });
            });
        }
        store.subscribe((state) => {
            this.render(state.status?.tasks || [], state.taskFilter, state.searchQuery);
        });
    }
    render(tasks, filter, query) {
        if (!this.containerEl)
            return;
        const payload = JSON.stringify([tasks, filter, query]);
        if (payload === this.lastPayload)
            return;
        this.lastPayload = payload;
        const focusedId = document.activeElement?.dataset.taskId;
        let filtered = tasks;
        if (filter !== 'all') {
            filtered = filtered.filter(t => t.status === filter);
        }
        if (query) {
            filtered = filtered.filter(t => (t.id && t.id.toLowerCase().includes(query)) ||
                (t.type && t.type.toLowerCase().includes(query)) ||
                (t.target && t.target.toLowerCase().includes(query)) ||
                (t.status && t.status.toLowerCase().includes(query)));
        }
        if (filtered.length === 0) {
            this.containerEl.innerHTML = `
        <tr>
          <td colspan="5" style="text-align:center; padding: 2.5rem; color: var(--text-dim); font-style: italic;">
            No tasks found matching current filter or search criteria.
          </td>
        </tr>
      `;
            return;
        }
        this.containerEl.innerHTML = filtered.map(task => {
            let badgeClass = 'badge-idle';
            if (task.status === 'completed')
                badgeClass = 'badge-success';
            else if (task.status === 'running')
                badgeClass = 'badge-active';
            else if (task.status === 'failed')
                badgeClass = 'badge-error';
            return `
        <tr data-task-id="${escapeHtml(task.id)}" tabindex="0" role="button" aria-label="Inspect task ${escapeHtml(task.id)}">
          <td style="font-family:monospace; font-weight:600; color:var(--accent-blue);">
            ${escapeHtml(task.id)}
          </td>
          <td>
            <span style="font-weight:600;">${escapeHtml(task.type)}</span>
          </td>
          <td style="max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
            ${escapeHtml(task.target || '-')}
          </td>
          <td>
            <span class="badge ${badgeClass}">
              <span class="status-dot ${task.status === 'running' ? 'pulse' : ''}"></span>
              ${escapeHtml(task.status)}
            </span>
          </td>
          <td style="color:var(--text-dim); font-size:0.75rem;">
            ${escapeHtml(task.created_at || 'Recently')}
          </td>
        </tr>
      `;
        }).join('');
        if (focusedId)
            Array.from(this.containerEl.querySelectorAll("tr[data-task-id]")).find(row => row.dataset.taskId === focusedId)?.focus();
        // Add click listeners to rows
        this.containerEl.querySelectorAll('tr[data-task-id]').forEach(row => {
            const open = () => {
                const taskId = row.getAttribute('data-task-id');
                const task = tasks.find(t => t.id === taskId);
                if (task) {
                    sound.playClick();
                    store.setState({ selectedTask: task, isDrawerOpen: true });
                }
            };
            row.addEventListener('click', open);
            row.addEventListener('keydown', (event) => {
                const e = event;
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    open();
                }
            });
        });
    }
}
//# sourceMappingURL=tasksTable.js.map