import type {
  AnalysisResponse,
  AnalysisTaskAccepted,
  AnalysisTaskDetail,
  AnalysisTaskSummary,
  ConversationSummary,
  AppUser,
  ChatDetail,
  ChatStreamEvent,
  ChatTaskAccepted,
  WorkspaceAttachment,
} from './types'

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? '/api/v1').replace(/\/$/, '')
const workbenchBaseUrl = (import.meta.env.VITE_WORKBENCH_API_BASE_URL ?? '/api').replace(/\/$/, '')

function readError(payload: unknown): string {
  if (typeof payload === 'object' && payload !== null) {
    const detail = (payload as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map((item) => item?.msg ?? String(item)).join('；')
  }
  return '服务暂时不可用，请检查后端是否已启动。'
}

export async function runAnalysis(question: string, conversationId: string): Promise<AnalysisResponse> {
  const response = await fetch(`${apiBaseUrl}/analysis/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, conversation_id: conversationId }),
    credentials: 'include',
  })

  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(readError(payload))
  }
  return payload as AnalysisResponse
}

export async function createAnalysisTask(question: string, conversationId: string): Promise<AnalysisTaskAccepted> {
  const response = await fetch(`${apiBaseUrl}/analysis/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, conversation_id: conversationId }),
    credentials: 'include',
  })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(readError(payload))
  }
  return payload as AnalysisTaskAccepted
}

export function taskStreamUrl(taskId: string): string {
  const explicitBase = import.meta.env.VITE_WS_BASE_URL?.replace(/\/$/, '')
  if (explicitBase) return `${explicitBase}/analysis/tasks/${encodeURIComponent(taskId)}/stream`

  if (apiBaseUrl.startsWith('http://') || apiBaseUrl.startsWith('https://')) {
    const backend = new URL(apiBaseUrl)
    backend.protocol = backend.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${backend.toString().replace(/\/$/, '')}/analysis/tasks/${encodeURIComponent(taskId)}/stream`
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${apiBaseUrl}/analysis/tasks/${encodeURIComponent(taskId)}/stream`
}

async function fetchApi<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, { credentials: 'include' })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(readError(payload))
  }
  return payload as T
}

export function listConversations(): Promise<ConversationSummary[]> {
  return fetchApi<ConversationSummary[]>('/conversations')
}

export function listConversationTasks(conversationId: string): Promise<AnalysisTaskSummary[]> {
  return fetchApi<AnalysisTaskSummary[]>(`/conversations/${encodeURIComponent(conversationId)}/tasks`)
}

export function getTask(taskId: string): Promise<AnalysisTaskDetail> {
  return fetchApi<AnalysisTaskDetail>(`/tasks/${encodeURIComponent(taskId)}`)
}

async function fetchWorkbench<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${workbenchBaseUrl}${path}`, {
    credentials: 'include',
    ...init,
    headers: { ...(init?.headers ?? {}) },
  })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) throw new Error(readError(payload))
  return payload as T
}

export function getCurrentUser(): Promise<AppUser> {
  return fetch('/auth/me', { credentials: 'include' }).then(async (response) => {
    const payload: unknown = await response.json().catch(() => null)
    if (!response.ok) throw new Error(readError(payload))
    return payload as AppUser
  })
}

export function login(username: string, displayName?: string, role: 'analyst' | 'admin' = 'analyst'): Promise<{ user: AppUser }> {
  return fetch('/auth/login', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, display_name: displayName || undefined, role }),
  }).then(async (response) => {
    const payload: unknown = await response.json().catch(() => null)
    if (!response.ok) throw new Error(readError(payload))
    return payload as { user: AppUser }
  })
}

export function logout(): Promise<void> {
  return fetch('/auth/logout', { method: 'POST', credentials: 'include' }).then(() => undefined)
}

export function listChats(): Promise<ConversationSummary[]> {
  return fetchWorkbench<ConversationSummary[]>('/chat/ls')
}

export function createChat(title?: string): Promise<ConversationSummary> {
  return fetchWorkbench<ConversationSummary>('/chat/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
}

export function getChat(conversationId: string): Promise<ChatDetail> {
  return fetchWorkbench<ChatDetail>(`/chat/ls/${encodeURIComponent(conversationId)}`)
}

export function renameChat(conversationId: string, title: string): Promise<ConversationSummary> {
  return fetchWorkbench<ConversationSummary>(`/chat/${encodeURIComponent(conversationId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
}

export function deleteChat(conversationId: string): Promise<void> {
  return fetchWorkbench(`/chat/${encodeURIComponent(conversationId)}`, {
    method: 'DELETE',
  }).then(() => undefined)
}

export function sendChatMessage(conversationId: string, content: string): Promise<ChatTaskAccepted> {
  return fetchWorkbench<ChatTaskAccepted>(`/chat/${encodeURIComponent(conversationId)}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
}

export function getWorkbenchTask(taskId: string): Promise<AnalysisTaskDetail> {
  return fetchWorkbench<AnalysisTaskDetail>(`/tasks/${encodeURIComponent(taskId)}`)
}

export function cancelWorkbenchTask(taskId: string): Promise<unknown> {
  return fetchWorkbench(`/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
}

export function getWsToken(taskId: string): Promise<{ token: string }> {
  return fetchWorkbench('/chat/ws-token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId }),
  })
}

export function chatStreamUrl(taskId: string, token: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${workbenchBaseUrl}/chat/ws/chat?task_id=${encodeURIComponent(taskId)}&token=${encodeURIComponent(token)}`
}

export async function uploadAttachment(conversationId: string, file: File): Promise<WorkspaceAttachment> {
  const form = new FormData()
  form.append('conversation_id', conversationId)
  form.append('file', file)
  // 使用规范接口路径 /api/attachment/upload
  const response = await fetch(`${workbenchBaseUrl}/attachment/upload`, {
    method: 'POST', credentials: 'include', body: form,
  })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) throw new Error(readError(payload))
  // 规范接口返回 attachment_id, file_name, file_path
  const result = payload as { attachment_id: string; file_name: string; file_path: string; status: string }
  return {
    id: result.attachment_id,
    conversation_id: conversationId,
    filename: result.file_name,
    file_type: file.type || 'application/octet-stream',
    file_size: file.size,
    parse_status: 'uploaded',
    parse_summary: {},
    created_at: new Date().toISOString(),
  }
}

export function deleteAttachment(attachmentId: string): Promise<void> {
  return fetch(`${apiBaseUrl}/attachments/${encodeURIComponent(attachmentId)}`, {
    method: 'DELETE', credentials: 'include',
  }).then(async (response) => {
    if (!response.ok) throw new Error(readError(await response.json().catch(() => null)))
  })
}

export function attachmentDownloadUrl(attachmentId: string): string {
  return `${apiBaseUrl}/attachments/${encodeURIComponent(attachmentId)}/download`
}

export function resultExportUrl(taskId: string): string {
  return `${workbenchBaseUrl}/results/${encodeURIComponent(taskId)}/export`
}

// 配置管理 API
export function getAdminConfig(): Promise<{ runtime: Record<string, string>; overrides: Record<string, string> }> {
  return fetchWorkbench('/admin/config')
}

export function setAdminConfig(key: string, value: string): Promise<{ status: string; key: string; runtime: Record<string, string> }> {
  return fetchWorkbench('/admin/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, value }),
  })
}

export function reloadAdminConfig(): Promise<{ status: string; config: Record<string, string> }> {
  return fetchWorkbench('/admin/reload', { method: 'POST' })
}

// 任务日志 API
export function getTaskLogs(taskId: string): Promise<Array<{ log_id: string; task_id: string; level: string; message: string; created_at: string }>> {
  return fetchWorkbench(`/tasks/${encodeURIComponent(taskId)}/logs`)
}

export type { ChatStreamEvent }
