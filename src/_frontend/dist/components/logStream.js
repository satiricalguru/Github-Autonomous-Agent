/**
 * Terminal Log Stream Component
 */
import { store } from '../state.js';
import { sound } from '../audio.js';
export class LogStream {
    bodyEl = null;
    autoscrollCheckbox = null;
    clearBtn = null;
    clearedLogs = new Set();
    localLogs = [];
    constructor() {
        this.init();
    }
    init() {
        this.bodyEl = document.getElementById('terminalBody');
        this.autoscrollCheckbox = document.getElementById('autoscrollToggle');
        this.clearBtn = document.getElementById('terminalClearBtn');
        if (this.autoscrollCheckbox) {
            this.autoscrollCheckbox.addEventListener('change', (e) => {
                store.setState({ autoscrollTerminal: e.target.checked });
            });
        }
        if (this.clearBtn) {
            this.clearBtn.addEventListener('click', () => {
                sound.playClick();
                this.localLogs.forEach(line => this.clearedLogs.add(line));
                this.localLogs = [];
                if (this.bodyEl) {
                    this.bodyEl.innerHTML = `<div class="log-empty">Logs cleared. Waiting for new stream events...</div>`;
                }
            });
        }
        store.subscribe((state) => {
            if (state.status?.recent_logs && state.status.recent_logs.length > 0) {
                this.updateLogs(state.status.recent_logs, state.autoscrollTerminal);
            }
        });
    }
    updateLogs(incomingLogs, autoscroll) {
        if (!this.bodyEl)
            return;
        incomingLogs = incomingLogs.filter(line => !this.clearedLogs.has(line));
        // Check if logs changed
        if (JSON.stringify(this.localLogs) === JSON.stringify(incomingLogs)) {
            return;
        }
        this.localLogs = [...incomingLogs];
        this.bodyEl.innerHTML = this.localLogs.map(line => this.formatLogLine(line)).join('');
        if (autoscroll) {
            this.bodyEl.scrollTop = this.bodyEl.scrollHeight;
        }
    }
    formatLogLine(raw) {
        // Expected format: HH:MM:SS [LEVEL] module: message or raw string
        const match = raw.match(/^(\d{2}:\d{2}:\d{2})\s+\[(INFO|WARN|ERROR|SUCCESS)\]\s+(.*)$/);
        if (match) {
            const [, time, level, rest] = match;
            const levelClass = level.toLowerCase();
            return `
        <div class="log-entry">
          <span class="log-time">${time}</span>
          <span class="log-tag ${levelClass}">${level}</span>
          <span class="log-msg">${this.escapeHtml(rest)}</span>
        </div>
      `;
        }
        // Fallback format
        return `
      <div class="log-entry">
        <span class="log-msg">${this.escapeHtml(raw)}</span>
      </div>
    `;
    }
    escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
}
//# sourceMappingURL=logStream.js.map