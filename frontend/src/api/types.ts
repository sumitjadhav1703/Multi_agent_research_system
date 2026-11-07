export interface ResearchRun {
  run_id: string;
  status: string;
  topic: string;
  approval_status: string | null;
  stop_reason: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  attempts: number;
  cancel_requested: boolean;
  provider_work_started: boolean;
  error_code: string | null;
  budgets: Record<string, number>;
  reused?: boolean;
}

export interface RunEvent {
  sequence_id: number;
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface UsageSnapshot {
  identity_scope: string;
  one_use_consumed: boolean;
  one_use_refunded: boolean;
  run_ids: string[];
  global_max_active_runs: number;
  global_active_runs: number;
  global_daily_cap: number;
  global_daily_starts: number;
  limits: Record<string, number>;
  estimated_cost_usd: number | string | null;
  note: string;
}

export interface UsageFigures {
  llm_calls: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  search_calls: number | null;
  estimated_cost_usd: number | string | null;
}

export const EMPTY_USAGE: UsageFigures = {
  llm_calls: null,
  prompt_tokens: null,
  completion_tokens: null,
  total_tokens: null,
  search_calls: null,
  estimated_cost_usd: null,
};

export interface SnapshotSource {
  source_id: string;
  url: string;
  canonical_url: string;
  domain: string;
  title: string;
  excerpt: string | null;
  extraction_method: string;
  retrieved_at: string | null;
  content_hash: string;
}

export interface SnapshotPassage {
  evidence_id: string;
  source_id: string;
  subquestion_id: string | null;
  quote: string;
}

export interface SnapshotClaim {
  claim_id: string;
  text: string;
  status: string;
  verification_reason: string | null;
  evidence_ids: string[];
}

export interface StoredReport {
  version: number;
  markdown: string;
  approval_state: string;
  created_at: string;
}

export interface ArtifactSnapshot {
  run_id: string;
  wording: string;
  report: StoredReport | null;
  sources: SnapshotSource[];
  passages: SnapshotPassage[];
  claims: SnapshotClaim[];
  usage: UsageFigures;
}

export interface HealthReady {
  status: string;
  app_env?: string;
  allow_paid_models?: boolean;
  use_mock_provider?: boolean;
  roles?: string[];
  allowlist_size?: number;
  database?: string;
}

export type ConnectionState = "idle" | "live" | "reconnecting" | "closed";

export interface EventsPage {
  run_id: string;
  events: RunEvent[];
}
