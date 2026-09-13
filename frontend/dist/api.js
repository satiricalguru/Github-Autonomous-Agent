/**
 * API Client for Autonomous GitHub Agent Backend
 */
export class ApiClient {
    baseUrl;
    constructor(baseUrl = '') {
        this.baseUrl = baseUrl;
    }
    async getStatus() {
        const res = await fetch(`${this.baseUrl}/api/status`, {
            headers: { 'Accept': 'application/json' }
        });
        if (!res.ok) {
            throw new Error(`Failed to fetch status: HTTP ${res.status}`);
        }
        return await res.json();
    }
    async toggleMode() {
        const res = await fetch(`${this.baseUrl}/api/toggle-mode`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        if (!res.ok) {
            throw new Error(`Failed to toggle mode: HTTP ${res.status}`);
        }
        return await res.json();
    }
    async markInboxDone(threadId) {
        const res = await fetch(`${this.baseUrl}/api/inbox-mark-done`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ thread_id: threadId })
        });
        if (!res.ok) {
            throw new Error(`Failed to mark notification done: HTTP ${res.status}`);
        }
        return await res.json();
    }
    async updateSettings(settings) {
        const res = await fetch(`${this.baseUrl}/api/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        if (!res.ok) {
            throw new Error(`Failed to update settings: HTTP ${res.status}`);
        }
        return await res.json();
    }
    async triggerWorker(workerType) {
        const res = await fetch(`${this.baseUrl}/api/trigger-${workerType}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        if (!res.ok) {
            throw new Error(`Failed to trigger ${workerType}: HTTP ${res.status}`);
        }
        return await res.json();
    }
}
export const api = new ApiClient();
//# sourceMappingURL=api.js.map