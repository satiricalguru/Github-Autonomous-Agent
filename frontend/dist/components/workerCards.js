/**
 * Worker Cards Component
 */
import { store } from '../state.js';
import { api } from '../api.js';
import { sound } from '../audio.js';
export class WorkerCards {
    containerEl = null;
    constructor() {
        this.init();
    }
    init() {
        this.containerEl = document.getElementById('workersContainer');
        store.subscribe((state) => {
            if (state.status?.workers) {
                this.render(state.status.workers);
            }
        });
    }
    render(workers) {
        if (!this.containerEl)
            return;
        const workerList = Object.entries(workers);
        if (workerList.length === 0) {
            this.containerEl.innerHTML = `
        <div style="grid-column: 1/-1; text-align:center; padding: 2rem; color: var(--text-dim);">
          No active background workers registered.
        </div>
      `;
            return;
        }
        this.containerEl.innerHTML = workerList.map(([key, worker]) => {
            const isRunning = worker.status === 'running';
            const badgeClass = isRunning ? 'badge-active' : 'badge-idle';
            let triggerAction = '';
            if (key.includes('inbox')) {
                triggerAction = `<button class="btn btn-sm trigger-worker-btn" data-worker="inbox">Trigger Inbox Scan</button>`;
            }
            else if (key.includes('hunt') || key.includes('issue')) {
                triggerAction = `<button class="btn btn-sm trigger-worker-btn" data-worker="hunt">Trigger Issue Hunter</button>`;
            }
            else if (key.includes('solve')) {
                triggerAction = `<button class="btn btn-sm trigger-worker-btn" data-worker="solve">Trigger Solver</button>`;
            }
            return `
        <div class="glass-card worker-card">
          <div class="worker-top">
            <div class="worker-info-group">
              <div class="worker-avatar">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
                  <line x1="8" y1="21" x2="16" y2="21"></line>
                  <line x1="12" y1="17" x2="12" y2="21"></line>
                </svg>
              </div>
              <div>
                <div class="worker-name">${worker.name || key}</div>
                <div class="worker-role">${worker.role || 'Background Autonomous Task'}</div>
              </div>
            </div>
            <span class="badge ${badgeClass}">
              <span class="status-dot ${isRunning ? 'pulse' : ''}"></span>
              ${worker.status}
            </span>
          </div>

          <div class="worker-status-banner">
            <div class="worker-status-text">
              <span style="color:var(--text-dim);">Task:</span>
              <span>${worker.current_task || 'Idle / Listening for events'}</span>
            </div>
            ${isRunning ? '<div class="radar-spinner"></div>' : ''}
          </div>

          <div style="display:flex; justify-content:space-between; font-size:0.75rem; color:var(--text-dim);">
            <div>Last Run: <span style="color:var(--text-main);">${worker.last_run || 'Recently'}</span></div>
            <div>Iterations: <span style="color:var(--text-main); font-weight:700;">${worker.iteration || 1}</span></div>
          </div>

          <div style="display:flex; justify-content:flex-end; gap:0.5rem; margin-top:0.25rem;">
            ${triggerAction}
          </div>
        </div>
      `;
        }).join('');
        // Attach trigger event listeners
        this.containerEl.querySelectorAll('.trigger-worker-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const workerKey = e.currentTarget.getAttribute('data-worker');
                const button = e.currentTarget;
                sound.playClick();
                button.disabled = true;
                const originalText = button.textContent;
                button.textContent = 'Triggering...';
                try {
                    await api.triggerWorker(workerKey);
                    sound.playSuccess();
                    button.textContent = '✓ Triggered';
                    setTimeout(() => {
                        button.textContent = originalText;
                        button.disabled = false;
                    }, 2000);
                }
                catch {
                    sound.playAlert();
                    button.textContent = 'Error';
                    setTimeout(() => {
                        button.textContent = originalText;
                        button.disabled = false;
                    }, 2000);
                }
            });
        });
    }
}
//# sourceMappingURL=workerCards.js.map