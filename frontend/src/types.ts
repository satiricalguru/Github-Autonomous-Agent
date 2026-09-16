/**
 * Autonomous GitHub Agent - Type Definitions
 */

export type AgentMode = 'LIVE' | 'DRY_RUN';

export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'skipped' | 'rejected';

export interface AgentTask {
  id: string;
  type: string;
  target: string;
  status: TaskStatus;
  created_at?: string;
  completed_at?: string;
  error?: string;
  pr_url?: string;
  diff_preview?: string;
  details?: Record<string, any>;
}

export interface WorkerState {
  name: string;
  role: string;
  status: 'idle' | 'running' | 'error' | 'stopped';
  current_task?: string;
  last_run?: string;
  next_run?: string;
  iteration?: number;
}

export interface TelemetryEvent {
  timestamp: string;
  level: 'INFO' | 'WARN' | 'ERROR' | 'SUCCESS';
  component: string;
  message: string;
}

export interface SystemMetrics {
  uptime_seconds: number;
  tasks_completed: number;
  prs_opened: number;
  inbox_processed: number;
  active_workers: number;
  rate_limit_remaining?: number | null;
  rate_limit_limit?: number | null;
  rate_limit_reset?: string;
}

export interface AgentConfig {
  dry_run: boolean;
  ai_provider?: string;
  sync_ide_model?: boolean;
  account: string;
  model: string;
  max_concurrent_tasks: number;
  polling_interval_inbox: number;
  polling_interval_issues: number;
  allowed_models?: string[];
}

export interface AgentStatusResponse {
  status: string;
  mode: AgentMode;
  account: string;
  model: string;
  config: AgentConfig;
  metrics: SystemMetrics;
  workers: Record<string, WorkerState>;
  tasks: AgentTask[];
  recent_logs: string[];
  ai_health?: { provider: string; model: string; state: string; configured: boolean; last_error?: string };
}

export type TabId = 'overview' | 'tasks' | 'workers' | 'terminal' | 'settings';
