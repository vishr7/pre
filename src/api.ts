export type Cell = { id: string; type: 'markdown' | 'latex' | 'python'; source: string; output?: string };
export type ProjectFile = { path: string; content: string };
export async function request<T>(base: string, path: string, body: unknown): Promise<T> {
  if (!base) throw new Error('Connect a backend in Settings to use this feature. Your work is saved locally.');
  const response = await fetch(`${base.replace(/\/$/, '')}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(120000) });
  if (!response.ok) throw new Error(`Request failed (${response.status}): ${await response.text()}`);
  return response.json();
}
