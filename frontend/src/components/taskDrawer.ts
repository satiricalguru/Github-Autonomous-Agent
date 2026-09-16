import { githubPrUrl, escapeHtml } from '../dom.js';
/**
 * Task Details Inspection Drawer
 */

import { store } from '../state.js';
import { sound } from '../audio.js';

export class TaskDrawer {
  private previousFocus: HTMLElement | null = null;
  private opened = false;
  private lastPayload = "";
  private backdropEl: HTMLElement | null = null;
  private panelEl: HTMLElement | null = null;

  constructor() {
    this.init();
  }

  private init(): void {
    this.backdropEl = document.getElementById('drawerBackdrop');
    this.panelEl = document.getElementById('drawerPanel');

    if (this.backdropEl) {
      this.backdropEl.addEventListener('click', () => this.close());
    }

    this.panelEl?.setAttribute('role', 'dialog');
    this.panelEl?.setAttribute('aria-modal', 'true');
    this.panelEl?.setAttribute('aria-labelledby', 'drawerTaskTitle');
    this.panelEl?.addEventListener('keydown', event => {
      if (event.key !== 'Tab') return;
      const elements = Array.from(this.panelEl!.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input, [tabindex="0"]'));
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    });
    const closeBtn = document.getElementById('drawerCloseBtn');
    if (closeBtn) {
      closeBtn.addEventListener('click', () => this.close());
    }

    store.subscribe((state) => {
      if (this.backdropEl && this.panelEl) {
        if (state.isDrawerOpen && state.selectedTask) {
          const task = state.status?.tasks.find(t => t.id === state.selectedTask?.id) || state.selectedTask;
          if (JSON.stringify(task) !== this.lastPayload) {
            this.renderTask(task);
            this.lastPayload = JSON.stringify(task);
          }
          if (!this.opened) this.previousFocus = document.activeElement as HTMLElement;
          this.backdropEl.classList.add('open');
          this.panelEl.classList.add('open');
          if (!this.opened) document.getElementById('drawerCloseBtn')?.focus();
          this.opened = true;
        } else {
          this.backdropEl.classList.remove('open');
          this.panelEl.classList.remove('open');
          if (this.opened) this.previousFocus?.focus();
          this.opened = false;
        }
      }
    });
  }

  public close(): void {
    sound.playClick();
    store.setState({ isDrawerOpen: false, selectedTask: null });
  }

  private renderTask(task: any): void {
    const titleEl = document.getElementById('drawerTaskTitle');
    const bodyEl = document.getElementById('drawerTaskBody');
    if (!titleEl || !bodyEl) return;

    titleEl.textContent = `Task: ${task.id}`;

    let prSection = '';
    const prUrl = githubPrUrl(task.pr_url);
    if (prUrl && !task.details?.dry_run) {
      prSection = `
        <div class="drawer-section">
          <div class="drawer-section-title">Created Pull Request</div>
          <a href="${escapeHtml(prUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary" style="display:inline-flex; width:fit-content; gap:0.5rem; text-decoration:none;">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
            Open PR #${escapeHtml(prUrl.split('/').pop())} on GitHub
          </a>
        </div>
      `;
    }

    let diffSection = '';
    if (task.diff_preview) {
      diffSection = `
        <div class="drawer-section">
          <div class="drawer-section-title">Code Diff Preview</div>
          <pre class="code-snippet">${this.escapeHtml(task.diff_preview)}</pre>
        </div>
      `;
    }

    let errorSection = '';
    if (task.error) {
      errorSection = `
        <div class="drawer-section">
          <div class="drawer-section-title" style="color:var(--accent-rose);">Execution Error</div>
          <div style="background:rgba(244,63,94,0.1); border:1px solid rgba(244,63,94,0.3); border-radius:8px; padding:0.85rem; color:#fca5a5; font-size:0.8rem; font-family:monospace;">
            ${this.escapeHtml(task.error)}
          </div>
        </div>
      `;
    }

    bodyEl.innerHTML = `
      <div class="drawer-section">
        <div class="drawer-section-title">Overview</div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:0.75rem; font-size:0.82rem;">
          <div><span style="color:var(--text-dim);">Type:</span> <strong style="color:var(--text-main);">${escapeHtml(task.type)}</strong></div>
          <div><span style="color:var(--text-dim);">Status:</span> <span class="badge badge-${task.status === 'completed' ? 'success' : task.status === 'failed' ? 'error' : 'active'}">${escapeHtml(task.status)}</span></div>
          <div><span style="color:var(--text-dim);">Created:</span> ${escapeHtml(task.created_at || 'Just now')}</div>
          <div><span style="color:var(--text-dim);">Completed:</span> ${escapeHtml(task.completed_at || '-')}</div>
        </div>
      </div>

      <div class="drawer-section">
        <div class="drawer-section-title">Target Resource</div>
        <div style="background:var(--card-inner); padding:0.75rem; border-radius:8px; border:1px solid var(--border); font-family:monospace; font-size:0.82rem;">
          ${this.escapeHtml(task.target || 'N/A')}
        </div>
      </div>

      ${prSection}
      ${diffSection}
      ${errorSection}

      <div class="drawer-section">
        <div class="drawer-section-title">Raw Task Payload</div>
        <pre class="code-snippet">${this.escapeHtml(JSON.stringify(task, null, 2))}</pre>
      </div>
    `;

  }

  private escapeHtml(str: string): string {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }
}
