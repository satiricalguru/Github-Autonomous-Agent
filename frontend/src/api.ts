import { AgentStatusResponse, AgentConfig } from './types.js';

export class ApiClient {
  constructor(private baseUrl = '') {}

  private async request(path: string, method = 'GET', payload?: unknown): Promise<any> {
    const res = await fetch(this.baseUrl + path, {
      method, credentials: 'same-origin', signal: AbortSignal.timeout(method === 'POST' ? 45000 : 15000),
      headers: method === 'POST' ? { 'Content-Type': 'application/json', 'X-Agent-Control': '1' } : { Accept: 'application/json' },
      body: method === 'POST' ? JSON.stringify(payload ?? {}) : undefined
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.status === 'error') throw new Error(data.error || `Request failed: HTTP ${res.status}`);
    return data;
  }
  getStatus(): Promise<AgentStatusResponse> { return this.request('/api/status'); }
  toggleMode(): Promise<{ status: string; mode: string }> { return this.request('/api/toggle-mode', 'POST'); }
  updateSettings(settings: Partial<AgentConfig>): Promise<any> { return this.request('/api/settings', 'POST', settings); }
  triggerWorker(worker: 'inbox' | 'hunt' | 'solve'): Promise<any> { return this.request(`/api/trigger-${worker}`, 'POST'); }
  pauseResume(): Promise<any> { return this.request('/api/pause-resume', 'POST'); }
  stop(): Promise<any> { return this.request('/api/stop', 'POST'); }
  markInboxDone(threadId: string): Promise<any> { return this.request('/api/inbox-mark-done', 'POST', { thread_id: threadId }); }
}
export const api = new ApiClient();
