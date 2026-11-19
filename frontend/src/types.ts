export interface Condition {
  offered_tasks: number;
  correct: number;
  accuracy: number;
  wilson_95: [number, number];
  strict_format_violations: number;
  by_fault: Record<string, { n: number; correct: number }>;
}

export interface PairedComparison {
  delta_accuracy: number;
  paired_bootstrap_95: [number, number];
  wins: number;
  losses: number;
  ties: number;
}

export interface TraceRow {
  task_id: string;
  family: string;
  fault: string;
  correct: boolean;
  tool_calls: number;
  output_tokens: number;
  format_violations: number;
  trace: Array<{
    assistant: string;
    tool?: Record<string, unknown> & { error?: unknown };
    error?: unknown;
  }>;
}

export interface Pilot {
  dataset_sha256: string;
  training: Array<{ stage: string }>;
  results: {
    kind: string;
    complete: boolean;
    rl_updates: number;
    budget: { conservative_reserved_usd: number };
    conditions: Record<string, Condition>;
    paired_vs_base: Record<string, PairedComparison>;
  };
  rows: Record<string, TraceRow[]>;
  tasks: Record<string, { schema: string; question: string }>;
}
