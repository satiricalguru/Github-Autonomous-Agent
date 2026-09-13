/**
 * Terminal Log Stream Component
 */

import { store } from '../state.js';
import { sound } from '../audio.js';

export class LogStream {
  private bodyEl: HTMLElement | null = null;
  private autoscrollCheckbox: HTMLInputElement | null = null;
  private clearBtn: HTMLElement | null = null;
  private localLogs: string[] = [];

  constructor() {
    this.init();
  }

  private init(): void {
    this.bodyEl = document.getElementById('terminalBody');
    this.autoscrollCheckbox = document.getElementById('autoscrollToggle') as HTMLInputElement;
    this.clearBtn = document.getElementById('terminalClearBtn');

    if (this.autoscrollCheckbox) {
      this.autoscrollCheckbox.addEventListener('change', (e) => {
        store.setState({ autoscrollTerminal: (e.target as HTMLInputElement).checked });
      });
    }

    if (this.clearBtn) {
      this.clearBtn.addEventListener('click', () => {
        sound.playClick();
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

  private updateLogs(incomingLogs: string[], autoscroll: boolean): void {
    if (!this.bodyEl) return;

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

  private formatLogLine(raw: string): string {
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

  private escapeHtml(str: string): string {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }
}
