/** Read-only browser contracts for pre_science.results; never execution authority. */
export type ScientificMetric = { name: string; value: number | null; role: string; observation_count?: number | null };
export type ScientificArtifact = { artifact_reference: string; artifact_type: string; mime_type: string; sha256: string; size_bytes: number };
export type ScientificAction = { action_id: string; title: string; description: string; action_type: string;
 eligible: boolean; reason: string; missing_inputs: string[]; required_inputs: string[];
 requires_approval: boolean; warnings: string[]; execution_authorized: false };
export type ScientificResult = {
 result_type: string; result_id: string | null; source_id: string | null; status: string; title: string; summary: string;
 freshness: 'unknown' | 'matching' | 'stale'; metrics: ScientificMetric[]; artifacts: ScientificArtifact[];
 parameters: Record<string, unknown> | null; warnings: string[]; limitations: string[];
 provenance: Record<string, unknown>; evidence: { completeness: string; [key: string]: unknown };
 dataset_references: unknown[]; source_version: unknown; created_at: string | null;
 original_payload: Record<string, unknown> | null; original_reference: string | null;
 next_actions: ScientificAction[]; all_next_actions: ScientificAction[];
};
export const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(item => typeof item === 'string');
export function isScientificResult(value: unknown): value is ScientificResult {
 if (!object(value)) return false;
 const actions = (items: unknown) => Array.isArray(items) && items.every(item => object(item) &&
  ['action_id','title','description','action_type','reason'].every(key => typeof item[key] === 'string') &&
  typeof item.eligible === 'boolean' && typeof item.requires_approval === 'boolean' && item.execution_authorized === false &&
  strings(item.missing_inputs) && strings(item.required_inputs) && strings(item.warnings));
 return ['result_type','status','title','summary'].every(key => typeof value[key] === 'string') &&
  ['result_id','source_id','created_at','original_reference'].every(key => value[key] === null || typeof value[key] === 'string') &&
  ['unknown','matching','stale'].includes(String(value.freshness)) &&
  Array.isArray(value.metrics) && value.metrics.every(item => object(item) && typeof item.name === 'string' &&
   typeof item.role === 'string' && (item.value === null || typeof item.value === 'number' && Number.isFinite(item.value)) &&
   (item.observation_count == null || typeof item.observation_count === 'number' && Number.isFinite(item.observation_count) && item.observation_count >= 0)) &&
  Array.isArray(value.artifacts) && value.artifacts.every(item => object(item) &&
   typeof item.artifact_reference === 'string' && /^[a-f0-9]{32}-[a-f0-9]{32}$/.test(item.artifact_reference) &&
   typeof item.artifact_type === 'string' && typeof item.mime_type === 'string' && typeof item.sha256 === 'string' && typeof item.size_bytes === 'number' && Number.isFinite(item.size_bytes) && item.size_bytes >= 0) &&
  strings(value.warnings) && strings(value.limitations) && object(value.evidence) && typeof value.evidence.completeness === 'string' &&
  object(value.provenance) && (value.parameters === null || object(value.parameters)) && Array.isArray(value.dataset_references) &&
  (value.original_payload === null || object(value.original_payload)) && actions(value.next_actions) && actions(value.all_next_actions);
}
export function formatMetric(value: number | null): string {
 if (value === null || !Number.isFinite(value)) return 'Unavailable';
 if (value === 0) return '0';
 return Math.abs(value) < 0.0001 || Math.abs(value) >= 1e7 ? value.toExponential(4) : value.toLocaleString('en-US', {maximumSignificantDigits: 7});
}
export function pdfUploadError(file: {name: string; type: string; size: number}): string | null {
 if (!/\.pdf$/i.test(file.name) || (file.type && file.type !== 'application/pdf')) return 'Choose a PDF file. Scanned papers need a searchable PDF version.';
 if (file.size === 0) return 'This file is empty. Choose a readable PDF.';
 if (file.size > 15_000_000) return 'Use a PDF under 15 MB.';
 return null;
}
/** Notebook images are actual returned data URLs. Never resolve opaque IDs into guessed URLs. */
export function safeFigureUrl(value: unknown): value is string {
 if(typeof value !== 'string')return false;
 if(/^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/]+=*$/.test(value))return true;
 if(/^\/(?!\/)[^\\\s]*$/.test(value)&&!value.includes('..')&&!value.includes(':')&&!/%(?:2e|2f|5c)/i.test(value))return true;
 try {const url=new URL(value);return !url.username&&!url.password&&(url.protocol==='https:'||url.protocol==='http:'&&['localhost','127.0.0.1'].includes(url.hostname));} catch{return false;}
}
