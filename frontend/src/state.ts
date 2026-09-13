/**
 * State Management Store for Mission Control
 */

import { AgentStatusResponse, AgentTask, TabId } from './types.js';

export type StateListener = (state: AppState) => void;

export interface AppState {
  currentTab: TabId;
  status: AgentStatusResponse | null;
  selectedTask: AgentTask | null;
  isDrawerOpen: boolean;
  isShortcutsOpen: boolean;
  theme: 'dark' | 'light';
  taskFilter: string;
  searchQuery: string;
  autoscrollTerminal: boolean;
  isLoading: boolean;
  lastError: string | null;
}

class Store {
  private state: AppState = {
    currentTab: 'overview',
    status: null,
    selectedTask: null,
    isDrawerOpen: false,
    isShortcutsOpen: false,
    theme: (localStorage.getItem('theme') as 'dark' | 'light') || 'dark',
    taskFilter: 'all',
    searchQuery: '',
    autoscrollTerminal: true,
    isLoading: false,
    lastError: null
  };

  private listeners: Set<StateListener> = new Set();

  public getState(): AppState {
    return this.state;
  }

  public setState(patch: Partial<AppState>): void {
    this.state = { ...this.state, ...patch };
    this.notify();
  }

  public subscribe(listener: StateListener): () => void {
    this.listeners.add(listener);
    listener(this.state);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify(): void {
    for (const listener of this.listeners) {
      listener(this.state);
    }
  }
}

export const store = new Store();
