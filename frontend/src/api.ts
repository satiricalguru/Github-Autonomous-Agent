/**
 * API Client for Autonomous GitHub Agent Backend
 */

import { AgentStatusResponse, AgentConfig } from './types.js';

export class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = '') {
    this.baseUrl = baseUrl;
  }

  public async getStatus(): Promise<AgentStatusResponse> {
    const res = await fetch(`${this.baseUrl}/api/status`, {
      headers: { 'Accept': 'application/json' }
    });
    if (!res.ok) {
      throw new Error(`Failed to fetch status: HTTP ${res.status}`);
    }
    return await res.json();
  }

  public async toggleMode(): Promise<{ status: string; mode: string }> {
    const res = await fetch(`${this.baseUrl}/api/toggle-mode`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    if (!res.ok) {
      throw new Error(`Failed to toggle mode: HTTP ${res.status}`);
    }
    return await res.json();
  }

  public async markInboxDone(threadId: string): Promise<{ status: string; thread_id: string }> {
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

  public async updateSettings(settings: Partial<AgentConfig>): Promise<any> {
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

  public async triggerWorker(workerType: 'inbox' | 'hunt' | 'solve'): Promise<{ status: string; message: string }> {
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
