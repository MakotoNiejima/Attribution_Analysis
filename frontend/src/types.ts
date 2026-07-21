export type Finding = {
  dimension: string
  group: string
  effect: number
  effect_type?: string
  description?: string
  evidence_ref?: string
  baseline_rate?: number
  current_rate?: number
}

export type BusinessEvent = {
  title?: string
  description?: string
  event_type?: string
  severity?: string
  event_date?: string
}

export type Funnel = {
  visit_sessions?: number
  cart_sessions?: number
  order_sessions?: number
  cart_rate?: number
  cart_to_order_rate?: number
  order_rate?: number
}

export type FunnelStage = {
  stage_name: string
  baseline_rate: number
  current_rate: number
  effect_on_overall: number
}

export type ChannelEfficiencyMetrics = {
  channel: string
  impressions: number
  clicks: number
  conversions: number
  revenue: number
  ad_spend: number
  roi: number
  cpc: number
  cpa: number
  ctr: number
  cvr: number
}

export type ChannelEfficiencyChange = {
  channel: string
  baseline: ChannelEfficiencyMetrics
  current: ChannelEfficiencyMetrics
  roi_change: number
  roi_change_rate: number
  cpc_change: number
  cpa_change: number
  revenue_change: number
  ad_spend_change: number
}

export type MarketAnalysisResult = {
  baseline_period: {
    start: string
    end: string
  }
  current_period: {
    start: string
    end: string
  }
  baseline_summary: {
    total_revenue: number
    total_ad_spend: number
    overall_roi: number
  }
  current_summary: {
    total_revenue: number
    total_ad_spend: number
    overall_roi: number
  }
  channel_changes: ChannelEfficiencyChange[]
  abnormal_channels: Array<{
    channel: string
    roi_change_rate: number
    roi_change: number
    baseline_roi: number
    current_roi: number
    ad_spend_change: number
    revenue_change: number
  }>
}

export type AnalysisResult = {
  baseline_funnel?: Funnel
  current_funnel?: Funnel
  funnel_change?: {
    order_rate_change?: number
  }
  stage_decomposition?: {
    stages?: FunnelStage[]
  }
  time_range?: {
    baseline_start?: string
    baseline_end?: string
    current_start?: string
    current_end?: string
  }
  // 市场表现分析字段
  baseline_period?: {
    start: string
    end: string
  }
  current_period?: {
    start: string
    end: string
  }
  baseline_summary?: {
    total_revenue: number
    total_ad_spend: number
    overall_roi: number
  }
  current_summary?: {
    total_revenue: number
    total_ad_spend: number
    overall_roi: number
  }
  channel_changes?: ChannelEfficiencyChange[]
  abnormal_channels?: Array<{
    channel: string
    roi_change_rate: number
    roi_change: number
    baseline_roi: number
    current_roi: number
    ad_spend_change: number
    revenue_change: number
  }>
}

type ResponseBase = {
  conversation_id: string
  task_id?: string | null
}

export type ClarifyResponse = ResponseBase & {
  status: 'clarify'
  clarification_question: string
}

export type CompletedResponse = ResponseBase & {
  status: 'success'
  report: string
  key_findings: Finding[]
  analysis_result: AnalysisResult
  matched_events: BusinessEvent[]
  evidence: Record<string, unknown>
}

export type FailedResponse = ResponseBase & {
  status: 'failed'
  errors: string[]
}

export type CancelledResponse = ResponseBase & {
  status: 'cancelled'
  message?: string
}

export type AnalysisResponse = ClarifyResponse | CompletedResponse | FailedResponse | CancelledResponse

export type AnalysisTaskAccepted = {
  task_id: string
  conversation_id: string
  status: 'running'
}

export type TaskProgressEvent = {
  type: 'connected' | 'task_started' | 'node_started' | 'node_completed' | 'detail' | 'terminal' | 'snapshot' | 'stream_error'
  task_id?: string
  timestamp?: string
  node?: string
  stage?: string
  label?: string
  message?: string
  status?: TaskStatus | 'running'
  response?: AnalysisResponse
  task?: AnalysisTaskDetail
}

export type TaskStatus = 'queued' | 'running' | 'clarify' | 'success' | 'failed' | 'cancelled'

export type ConversationSummary = {
  conversation_id: string
  title: string
  task_count: number
  last_task_id?: string | null
  last_task_status?: TaskStatus | null
  created_at: string
  updated_at: string
}

export type AnalysisTaskSummary = {
  task_id: string
  conversation_id: string
  question: string
  status: TaskStatus
  created_at: string
  started_at?: string | null
  finished_at?: string | null
}

export type KeyMetric = {
  metric_name: string
  metric_value: number
  metric_unit: string
  metric_period: string
}

export type EvidenceItem = {
  source_type: string
  source_name: string
  evidence_text: string
  related_metric: string
  confidence: number
}

export type AnalysisTaskDetail = AnalysisTaskSummary & {
  clarification_question?: string | null
  errors: string[]
  report?: string | null
  key_findings: Finding[]
  analysis_result: AnalysisResult
  evidence: Record<string, unknown>
  matched_events: BusinessEvent[]
  // 规范六段结构
  problem_definition?: string | null
  key_metrics?: KeyMetric[]
  evidence_list?: EvidenceItem[]
  conclusion_text?: string | null
  missing_data_text?: string | null
  next_action_text?: string | null
}

export type AppUser = {
  user_id: string
  username: string
  display_name: string
  role: 'analyst' | 'admin'
  is_active: boolean
}

export type ChatMessage = {
  message_id: string
  task_id?: string | null
  role: 'user' | 'assistant' | 'system'
  content: string
  metadata: Record<string, unknown>
  created_at: string
}

export type WorkspaceAttachment = {
  id: string
  conversation_id: string
  filename: string
  file_type: string
  file_size: number
  parse_status: string
  parse_summary: {
    row_count?: number
    columns?: Array<{ name: string }>
    preview?: Array<Record<string, string>>
  }
  created_at: string
}

export type ChatDetail = {
  conversation_id: string
  messages: ChatMessage[]
  tasks: AnalysisTaskSummary[]
  attachments: WorkspaceAttachment[]
}

export type ChatTaskAccepted = {
  task_id: string
  conversation_id: string
  status: 'running'
}

export type ChatStreamEvent = {
  type: 'message_start' | 'task_status' | 'tool_start' | 'tool_finish' | 'message_delta' | 'result_ready' | 'error' | 'done'
  task_id?: string
  conversation_id?: string
  task_status?: TaskStatus | 'running'
  current_step?: string
  tool_name?: string
  tool_result_summary?: string
  delta_text?: string
  result_id?: string
  error_message?: string
  finished_at?: string
  status?: TaskStatus | 'running'
  node?: string
  label?: string
  message?: string
  response?: AnalysisResponse
  timestamp?: string
}
