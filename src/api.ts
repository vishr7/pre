export type Cell = {
  id: string;
  type: 'markdown' | 'latex' | 'python' | 'javascript';
  source: string;
  output?: string;
  error?: string;
  images?: string[];
  durationMs?: number;
  executionCount?: number;
  status?: 'running' | 'success' | 'error';
};
export type ExecutionResult = { stdout: string; stderr?: string; error?: string; images?: string[]; durationMs?: number; executionCount?: number };
export type ProjectFile = { path: string; content: string };
export async function request<T>(base: string, path: string, body: unknown): Promise<T> {
  const response = await fetch(`${base.replace(/\/$/, '')}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...(base ? {} : { 'X-PRE-Runtime': '1' }) },
    body: JSON.stringify(body), signal: AbortSignal.timeout(120000),
  });
  if (!response.ok) {
    const text = await response.text();
    let message = text;
    try { message = JSON.parse(text).error || text; } catch { /* Non-JSON external backend error. */ }
    throw new Error(message || `Request failed (${response.status}).`);
  }
  return response.json();
}
