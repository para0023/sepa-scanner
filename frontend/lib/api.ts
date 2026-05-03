import { supabase } from "./supabase";

function getApiBase(): string {
  return "/api";
}

async function getAuthHeaders(): Promise<Record<string, string>> {
  const { data: { session } } = await supabase.auth.getSession();
  if (session?.access_token) {
    return { Authorization: `Bearer ${session.access_token}` };
  }
  return {};
}

export async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${getApiBase()}${path}`, {
    ...options,
    headers: { ...headers, ...(options?.headers || {}) },
  });
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  return res.json();
}

/**
 * SSE 스트림 API 호출
 * onProgress: 진행률 콜백 (done, total)
 * 완료 시 최종 데이터 반환
 */
export function fetchSSE<T>(
  path: string,
  onProgress?: (done: number, total: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const es = new EventSource(`${getApiBase()}${path}`);

    es.addEventListener("progress", (e: MessageEvent) => {
      if (onProgress) {
        const { done, total } = JSON.parse(e.data);
        onProgress(done, total);
      }
    });

    es.addEventListener("done", (e: MessageEvent) => {
      es.close();
      resolve(JSON.parse(e.data) as T);
    });

    es.addEventListener("error", (e: any) => {
      es.close();
      if (e.data) {
        reject(new Error(JSON.parse(e.data).error));
      } else {
        reject(new Error("SSE 연결 실패"));
      }
    });
  });
}
