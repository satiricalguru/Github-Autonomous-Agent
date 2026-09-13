/**
 * Autonomous GitHub Agent - Mission Control App
 * Pure Vanilla TypeScript/HTML/CSS Frontend Entry Point
 */
import { api } from './api.js';
import { store } from './state.js';
import { sound } from './audio.js';
import { TaskDrawer } from './components/taskDrawer.js';
import { TasksTable } from './components/tasksTable.js';
import { WorkerCards } from './components/workerCards.js';
import { LogStream } from './components/logStream.js';
class MissionControlApp {
    pollIntervalId = null;
    taskDrawer;
    tasksTable;
    workerCards;
    logStream;
    constructor() {
        this.init();
    }
    async init() {
        this.applyTheme(store.getState().theme);
        this.setupNavigation();
        this.setupHeaderActions();
        this.setupKeyboardShortcuts();
        this.setupSettingsForm();
        // Initialize Components
        this.taskDrawer = new TaskDrawer();
        this.tasksTable = new TasksTable();
        this.workerCards = new WorkerCards();
        this.logStream = new LogStream();
        // Subscribe to state changes for global UI updates
        store.subscribe((state) => {
            if (state.status) {
                this.updateHeaderAndMetrics(state.status);
            }
        });
        // Initial Fetch & Polling
        await this.refreshStatus();
        this.startPolling();
    }
    setupNavigation() {
        const navItems = document.querySelectorAll('.nav-item[data-tab]');
        navItems.forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const tab = item.getAttribute('data-tab');
                this.switchTab(tab);
            });
        });
    }
    switchTab(tabId) {
        sound.playClick();
        store.setState({ currentTab: tabId });
        // Update nav links
        document.querySelectorAll('.nav-item[data-tab]').forEach(item => {
            if (item.getAttribute('data-tab') === tabId) {
                item.classList.add('active');
            }
            else {
                item.classList.remove('active');
            }
        });
        // Update tab view panels
        document.querySelectorAll('.tab-view').forEach(panel => {
            if (panel.id === `view-${tabId}`) {
                panel.classList.add('active');
            }
            else {
                panel.classList.remove('active');
            }
        });
    }
    setupHeaderActions() {
        // Mode Toggle Button
        const modeBtn = document.getElementById('modeToggleBtn');
        if (modeBtn) {
            modeBtn.addEventListener('click', async () => {
                sound.playToggle();
                try {
                    modeBtn.textContent = 'Switching...';
                    const res = await api.toggleMode();
                    sound.playSuccess();
                    this.showToast(`Mode switched to ${res.mode}`, 'success');
                    await this.refreshStatus();
                }
                catch (err) {
                    sound.playAlert();
                    this.showToast(`Failed to switch mode: ${err.message}`, 'error');
                }
            });
        }
        // Theme Toggle Button
        const themeBtn = document.getElementById('themeToggleBtn');
        if (themeBtn) {
            themeBtn.addEventListener('click', () => {
                sound.playClick();
                const nextTheme = store.getState().theme === 'dark' ? 'light' : 'dark';
                this.applyTheme(nextTheme);
            });
        }
        // Sound Toggle Button
        const soundBtn = document.getElementById('soundToggleBtn');
        if (soundBtn) {
            this.updateSoundIcon(sound.isEnabled());
            soundBtn.addEventListener('click', () => {
                const enabled = sound.toggle();
                this.updateSoundIcon(enabled);
                this.showToast(`Sound FX ${enabled ? 'Enabled' : 'Disabled'}`, 'info');
            });
        }
        // Refresh Now Button
        const refreshBtn = document.getElementById('refreshBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', async () => {
                sound.playClick();
                refreshBtn.classList.add('animate-spin');
                await this.refreshStatus();
                setTimeout(() => refreshBtn.classList.remove('animate-spin'), 600);
            });
        }
        // Shortcuts Modal
        const shortcutsBtn = document.getElementById('shortcutsBtn');
        const shortcutsModal = document.getElementById('shortcutsModal');
        const closeShortcutsBtn = document.getElementById('shortcutsCloseBtn');
        if (shortcutsBtn && shortcutsModal) {
            shortcutsBtn.addEventListener('click', () => {
                sound.playClick();
                shortcutsModal.classList.add('open');
            });
        }
        if (closeShortcutsBtn && shortcutsModal) {
            closeShortcutsBtn.addEventListener('click', () => {
                sound.playClick();
                shortcutsModal.classList.remove('open');
            });
        }
        if (shortcutsModal) {
            shortcutsModal.addEventListener('click', (e) => {
                if (e.target === shortcutsModal) {
                    shortcutsModal.classList.remove('open');
                }
            });
        }
    }
    updateSoundIcon(enabled) {
        const soundBtn = document.getElementById('soundToggleBtn');
        if (!soundBtn)
            return;
        soundBtn.innerHTML = enabled
            ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"></path></svg>`
            : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><line x1="23" y1="9" x2="17" y2="15"></line><line x1="17" y1="9" x2="23" y2="15"></line></svg>`;
    }
    applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);
        store.setState({ theme });
        const themeBtn = document.getElementById('themeToggleBtn');
        if (themeBtn) {
            themeBtn.innerHTML = theme === 'dark'
                ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`
                : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`;
        }
    }
    setupKeyboardShortcuts() {
        window.addEventListener('keydown', (e) => {
            // Ignore if typing in an input
            const active = document.activeElement;
            if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT')) {
                return;
            }
            if (e.key === '1')
                this.switchTab('overview');
            else if (e.key === '2')
                this.switchTab('tasks');
            else if (e.key === '3')
                this.switchTab('workers');
            else if (e.key === '4')
                this.switchTab('terminal');
            else if (e.key === '5')
                this.switchTab('settings');
            else if (e.key === 'd' || e.key === 'D') {
                const modeBtn = document.getElementById('modeToggleBtn');
                modeBtn?.click();
            }
            else if (e.key === 'm' || e.key === 'M') {
                const soundBtn = document.getElementById('soundToggleBtn');
                soundBtn?.click();
            }
            else if (e.key === 'c' || e.key === 'C') {
                const themeBtn = document.getElementById('themeToggleBtn');
                themeBtn?.click();
            }
            else if (e.key === 'r' || e.key === 'R') {
                const refreshBtn = document.getElementById('refreshBtn');
                refreshBtn?.click();
            }
            else if (e.key === '?') {
                const shortcutsBtn = document.getElementById('shortcutsBtn');
                shortcutsBtn?.click();
            }
            else if (e.key === 'Escape') {
                this.taskDrawer.close();
                document.getElementById('shortcutsModal')?.classList.remove('open');
            }
        });
    }
    setupSettingsForm() {
        const form = document.getElementById('settingsForm');
        if (!form)
            return;
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            sound.playClick();
            const modelSelect = document.getElementById('modelSelect');
            const maxTasksInput = document.getElementById('maxTasksInput');
            const inboxIntervalInput = document.getElementById('inboxIntervalInput');
            const issuesIntervalInput = document.getElementById('issuesIntervalInput');
            const payload = {
                model: modelSelect.value,
                max_concurrent_tasks: parseInt(maxTasksInput.value, 10),
                polling_interval_inbox: parseInt(inboxIntervalInput.value, 10),
                polling_interval_issues: parseInt(issuesIntervalInput.value, 10)
            };
            try {
                await api.updateSettings(payload);
                sound.playSuccess();
                this.showToast('Settings saved successfully', 'success');
                await this.refreshStatus();
            }
            catch (err) {
                sound.playAlert();
                this.showToast(`Error saving settings: ${err.message}`, 'error');
            }
        });
    }
    async refreshStatus() {
        try {
            const status = await api.getStatus();
            store.setState({ status, lastError: null });
        }
        catch (err) {
            store.setState({ lastError: err.message });
        }
    }
    startPolling() {
        if (this.pollIntervalId) {
            clearInterval(this.pollIntervalId);
        }
        this.pollIntervalId = window.setInterval(async () => {
            await this.refreshStatus();
        }, 3000);
    }
    updateHeaderAndMetrics(status) {
        // Mode Badge & Toggle
        const modeBadge = document.getElementById('headerModeBadge');
        const modeToggleBtn = document.getElementById('modeToggleBtn');
        if (modeBadge) {
            modeBadge.className = `badge ${status.mode === 'LIVE' ? 'badge-live' : 'badge-dry'}`;
            modeBadge.innerHTML = `<span class="status-dot ${status.mode === 'LIVE' ? 'pulse' : ''}"></span>${status.mode}`;
        }
        if (modeToggleBtn) {
            modeToggleBtn.textContent = status.mode === 'LIVE' ? 'Switch to DRY RUN' : 'Switch to LIVE Mode';
        }
        // Header Meta
        const modelTag = document.getElementById('headerModelTag');
        if (modelTag) {
            modelTag.textContent = status.model;
        }
        const accountTag = document.getElementById('headerAccountTag');
        if (accountTag) {
            accountTag.textContent = status.account || 'Unknown';
        }
        // Metrics Cards
        const valTasks = document.getElementById('valTasksCompleted');
        if (valTasks)
            valTasks.textContent = String(status.metrics?.tasks_completed ?? 0);
        const valPrs = document.getElementById('valPrsOpened');
        if (valPrs)
            valPrs.textContent = String(status.metrics?.prs_opened ?? 0);
        const valInbox = document.getElementById('valInboxProcessed');
        if (valInbox)
            valInbox.textContent = String(status.metrics?.inbox_processed ?? 0);
        const valWorkers = document.getElementById('valActiveWorkers');
        if (valWorkers)
            valWorkers.textContent = String(status.metrics?.active_workers ?? Object.keys(status.workers || {}).length);
        const valUptime = document.getElementById('valUptime');
        if (valUptime) {
            const sec = status.metrics?.uptime_seconds || 0;
            const hrs = Math.floor(sec / 3600);
            const mins = Math.floor((sec % 3600) / 60);
            const s = sec % 60;
            valUptime.textContent = `${hrs}h ${mins}m ${s}s`;
        }
        // Populate Settings Select if models available
        const modelSelect = document.getElementById('modelSelect');
        if (modelSelect && status.config?.allowed_models) {
            const currentSelected = modelSelect.value || status.model;
            modelSelect.innerHTML = status.config.allowed_models.map(m => `
        <option value="${m}" ${m === currentSelected ? 'selected' : ''}>${m}</option>
      `).join('');
        }
    }
    showToast(message, type) {
        const container = document.getElementById('toastContainer');
        if (!container)
            return;
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `
      <span>${type === 'success' ? '✓' : type === 'error' ? '⚠️' : 'ℹ️'}</span>
      <span>${message}</span>
    `;
        container.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(20px)';
            toast.style.transition = 'all 0.25s ease';
            setTimeout(() => toast.remove(), 250);
        }, 3200);
    }
}
// Bootstrap on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    new MissionControlApp();
});
//# sourceMappingURL=app.js.map