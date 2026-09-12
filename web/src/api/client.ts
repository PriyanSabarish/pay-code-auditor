import type { components } from './types';

export type AuditJob = components['schemas']['AuditJob'];
export type Verdict = components['schemas']['Verdict'];
export type Decision = components['schemas']['Decision'];
export type Question = components['schemas']['Question'];
export type Award = components['schemas']['Award'];
export type Letter = components['schemas']['Letter'];
export type Answer = components['schemas']['Answer'];

export class ApiError extends Error {
  constructor(message: string, public status: number, public fields: Record<string,string> = {}) { super(message); }
}

export function parseError(payload: unknown, status: number): ApiError {
  const detail = payload && typeof payload === 'object' && 'detail' in payload ? payload.detail : null;
  if (typeof detail === 'string') return new ApiError(detail, status);
  const fields: Record<string,string> = {};
  if (Array.isArray(detail)) {
    for (const error of detail) {
      if (error && typeof error === 'object' && Array.isArray(error.loc) && typeof error.msg === 'string') {
        fields[String(error.loc[error.loc.length-1])] = error.msg;
      }
    }
  }
  return new ApiError(Object.values(fields).join(' ') || `The request could not be completed (${status}). Please try again.`,status,fields);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try { response = await fetch(path, { ...init, signal: init.signal ?? AbortSignal.timeout(30_000) }); }
  catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('The audit service could not be reached. Check that the backend is running, then retry.',0);
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw parseError(payload,response.status);
  if (payload === null) throw new ApiError('The service returned an unexpected response. Check the API connection.',response.status);
  return payload as T;
}

const json = (body: unknown): RequestInit => ({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const auditPath = (id: string) => `/api/audits/${encodeURIComponent(id)}`;
export const api = {
  awards: (signal?: AbortSignal) => request<Award[]>('/api/awards',{signal}),
  create: (files: {paycodes:File;payruns:File;award_id:string}) => {
    const form = new FormData();
    form.append('paycodes', files.paycodes); form.append('payruns', files.payruns);
    form.append('award_id', files.award_id); form.append('mode','full');
    return request<components['schemas']['AuditCreated']>('/api/audits',{method:'POST',body:form});
  },
  job: (id: string, signal?: AbortSignal) => request<AuditJob>(auditPath(id),{signal}),
  answer: (id: string, body: Answer) => request<AuditJob>(`${auditPath(id)}/answer`,json(body)),
  decide: (id: string, code: string, body: Decision) => request<Verdict>(`${auditPath(id)}/verdicts/${encodeURIComponent(code)}`,json(body)),
  letter: (id:string,code:string,signal?:AbortSignal) => request<Letter>(`${auditPath(id)}/letter/${encodeURIComponent(code)}`,{signal}),
  reportUrl: (id: string) => `${auditPath(id)}/report.csv`,
  letterUrl: (id:string,code:string) => `${auditPath(id)}/letter/${encodeURIComponent(code)}?download=true`,
};

export function fileError(file:File | null): string | undefined {
  if (!file) return undefined;
  if (!file.name.toLowerCase().endsWith('.csv')) return 'Choose a .csv file.';
  if (!file.size) return 'This file is empty. Choose a file containing data.';
  if (file.size > 5 * 1024 * 1024) return 'This file is too large. The limit is 5 MB.';
  return undefined;
}

export function pollInterval(status: AuditJob['status'] | undefined): number | false {
  return status === 'queued' || status === 'running' ? 1000 : false;
}

export function safeSource(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  try { const value = new URL(url); return ['https:','http:'].includes(value.protocol) ? value.href : undefined; } catch { return undefined; }
}

export const money = (value:number) => new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD',maximumFractionDigits:2}).format(value);
export const statusLabels: Record<Verdict['status'],string> = {correct:'Correct',under:'Should count but does not',over:'Counts but should not',review:'Needs review'};
