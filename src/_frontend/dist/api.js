export class ApiClient {
    baseUrl;
    constructor(baseUrl = '') {
        this.baseUrl = baseUrl;
    }
    async request(path, method = 'GET', payload) {
        const res = await fetch(this.baseUrl + path, {
            method, credentials: 'same-origin', signal: AbortSignal.timeout(method === 'POST' ? 45000 : 15000),
            headers: method === 'POST' ? { 'Content-Type': 'application/json', 'X-Agent-Control': '1' } : { Accept: 'application/json' },
            body: method === 'POST' ? JSON.stringify(payload ?? {}) : undefined
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.status === 'error')
            throw new Error(data.error || `Request failed: HTTP ${res.status}`);
        return data;
    }
    getStatus() { return this.request('/api/status'); }
    toggleMode() { return this.request('/api/toggle-mode', 'POST'); }
    updateSettings(settings) { return this.request('/api/settings', 'POST', settings); }
    triggerWorker(worker) { return this.request(`/api/trigger-${worker}`, 'POST'); }
    pauseResume() { return this.request('/api/pause-resume', 'POST'); }
    stop() { return this.request('/api/stop', 'POST'); }
    markInboxDone(threadId) { return this.request('/api/inbox-mark-done', 'POST', { thread_id: threadId }); }
}
export const api = new ApiClient();
//# sourceMappingURL=api.js.map