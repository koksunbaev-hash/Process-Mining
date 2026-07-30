/**
 * TypeScript client for the Process Mining Service.
 * Zero dependencies - works in Node 18+ and in the browser.
 */

export type Algorithm =
  | 'dfg_frequency'
  | 'dfg_performance'
  | 'petri_net_inductive'
  | 'petri_net_heuristics'
  | 'process_tree'
  | 'bpmn';

export type OutputFormat = 'json' | 'svg' | 'png' | 'dot';

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  frequency?: number | null;
  mean_duration_seconds?: number | null;
  metrics: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  frequency?: number | null;
  mean_duration_seconds?: number | null;
  median_duration_seconds?: number | null;
  metrics: Record<string, unknown>;
}

export interface ProcessGraph {
  algorithm: Algorithm;
  nodes: GraphNode[];
  edges: GraphEdge[];
  start_activities: Record<string, number>;
  end_activities: Record<string, number>;
  stats: Record<string, unknown>;
}

export interface DiscoverResponse {
  log_id?: string | null;
  algorithm: Algorithm;
  format: string;
  cached: boolean;
  computed_in_ms: number;
  graph?: ProcessGraph | null;
  image?: string | null;
  content_type?: string | null;
}

export interface LogFilters {
  date_from?: string;
  date_to?: string;
  activities_include?: string[];
  activities_exclude?: string[];
  variant_coverage?: number;
  activity_coverage?: number;
  min_case_length?: number;
  max_case_length?: number;
}

export class ProcessMiningError extends Error {
  constructor(public status: number, public body: unknown) {
    super(`HTTP ${status}: ${JSON.stringify(body)}`);
  }
}

export class ProcessMiningClient {
  constructor(private baseUrl: string, private apiKey?: string) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  private headers(extra: Record<string, string> = {}): Record<string, string> {
    return this.apiKey ? { 'X-API-Key': this.apiKey, ...extra } : extra;
  }

  private async handle<T>(response: Response): Promise<T> {
    const contentType = response.headers.get('content-type') || '';
    const body = contentType.includes('application/json')
      ? await response.json()
      : await response.text();
    if (!response.ok) throw new ProcessMiningError(response.status, body);
    return body as T;
  }

  /** Stateless: send a file, get the model back, nothing is stored server-side. */
  async mineFile(
    file: File | Blob,
    options: {
      algorithm?: Algorithm;
      format?: OutputFormat;
      mappingProfile?: string;
      columns?: Record<string, string>;
      filters?: LogFilters;
      includeStatistics?: boolean;
    } = {},
  ): Promise<{ result: DiscoverResponse; statistics?: unknown; bottlenecks?: unknown }> {
    const form = new FormData();
    form.append('file', file);
    form.append('algorithm', options.algorithm ?? 'dfg_frequency');
    form.append('format', options.format ?? 'json');
    form.append('include_statistics', String(options.includeStatistics ?? true));
    if (options.mappingProfile) form.append('mapping_profile', options.mappingProfile);
    if (options.columns) form.append('columns', JSON.stringify(options.columns));
    if (options.filters) form.append('filters', JSON.stringify(options.filters));

    const response = await fetch(`${this.baseUrl}/api/v1/mine`, {
      method: 'POST',
      headers: this.headers(),
      body: form,
    });
    return this.handle(response);
  }

  async uploadLog(file: File | Blob, options: { name?: string; tenant?: string; mappingProfile?: string } = {}) {
    const form = new FormData();
    form.append('file', file);
    if (options.name) form.append('name', options.name);
    if (options.tenant) form.append('tenant', options.tenant);
    if (options.mappingProfile) form.append('mapping_profile', options.mappingProfile);
    const response = await fetch(`${this.baseUrl}/api/v1/logs/upload`, {
      method: 'POST',
      headers: this.headers(),
      body: form,
    });
    return this.handle<{ log: Record<string, unknown>; warnings: string[] }>(response);
  }

  async appendEvents(logId: string, events: Array<Record<string, unknown>>) {
    const response = await fetch(`${this.baseUrl}/api/v1/logs/${logId}/events`, {
      method: 'POST',
      headers: this.headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ events }),
    });
    return this.handle(response);
  }

  async discover(logId: string, payload: Record<string, unknown> = {}): Promise<DiscoverResponse> {
    const response = await fetch(`${this.baseUrl}/api/v1/logs/${logId}/discover`, {
      method: 'POST',
      headers: this.headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    return this.handle<DiscoverResponse>(response);
  }

  /** URL you can drop straight into an <img> / <object> tag. */
  mapUrl(logId: string, algorithm: Algorithm = 'dfg_frequency', format: OutputFormat = 'svg'): string {
    return `${this.baseUrl}/api/v1/logs/${logId}/map?algorithm=${algorithm}&format=${format}`;
  }

  async statistics(logId: string) {
    return this.handle(await fetch(`${this.baseUrl}/api/v1/logs/${logId}/statistics`, { headers: this.headers() }));
  }

  async variants(logId: string, limit = 20) {
    return this.handle(await fetch(`${this.baseUrl}/api/v1/logs/${logId}/variants?limit=${limit}`, { headers: this.headers() }));
  }

  async bottlenecks(logId: string, limit = 10) {
    return this.handle(await fetch(`${this.baseUrl}/api/v1/logs/${logId}/bottlenecks?limit=${limit}`, { headers: this.headers() }));
  }
}
