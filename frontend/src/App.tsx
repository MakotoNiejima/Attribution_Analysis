import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from 'react'
import Workbench from './Workbench'
import { createAnalysisTask, getTask, listConversationTasks, listConversations, taskStreamUrl } from './api'
import type {
  AnalysisResponse,
  AnalysisTaskDetail,
  AnalysisTaskSummary,
  CompletedResponse,
  ConversationSummary,
  Finding,
  TaskProgressEvent,
  TaskStatus,
} from './types'

const EXAMPLE_QUESTIONS = [
  '为什么本月整体转化率比上月下降了？',
  '请分析 2026 年 7 月与 6 月的转化率变化。',
  '本月哪些渠道对整体转化率下降影响最大？',
  '各渠道的 ROI 表现如何？',
  '哪个渠道的投放效率下降最大？',
]

const ACTIVE_CONVERSATION_KEY = 'attribution-analysis-active-conversation'
type ViewState = 'idle' | 'loading' | 'completed' | 'clarify' | 'failed' | 'cancelled'

function createConversationId() {
  return globalThis.crypto?.randomUUID?.() ?? `analysis-${Date.now()}`
}

function initialConversationId() {
  return globalThis.localStorage?.getItem(ACTIVE_CONVERSATION_KEY) || createConversationId()
}

function formatPercent(value?: number, digits = 2) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

function formatEffect(value?: number) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—'
  const direction = value < 0 ? '拉低' : '抬升'
  return `${direction} ${Math.abs(value * 100).toFixed(2)} 个百分点`
}

function formatROI(value?: number) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—'
  return value.toFixed(2)
}

function formatCurrency(value?: number) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—'
  return `¥${value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatTaskTime(value?: string | null) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(date)
}

function statusLabel(status?: TaskStatus | null) {
  return { running: '进行中', clarify: '待补充', completed: '已完成', failed: '失败', cancelled: '已取消' }[status ?? 'running']
}

function findingTone(effect: number) {
  if (effect < 0) return 'negative'
  if (effect > 0) return 'positive'
  return 'neutral'
}

function toStoredResponse(task: AnalysisTaskDetail): AnalysisResponse | null {
  if (task.status === 'completed' && task.report) {
    return {
      status: 'completed',
      conversation_id: task.conversation_id,
      task_id: task.task_id,
      report: task.report,
      key_findings: task.key_findings,
      analysis_result: task.analysis_result,
      evidence: task.evidence,
      matched_events: task.matched_events,
    }
  }
  if (task.status === 'clarify' && task.clarification_question) {
    return {
      status: 'clarify',
      conversation_id: task.conversation_id,
      task_id: task.task_id,
      clarification_question: task.clarification_question,
    }
  }
  if (task.status === 'failed') {
    return {
      status: 'failed',
      conversation_id: task.conversation_id,
      task_id: task.task_id,
      errors: task.errors,
    }
  }
  return null
}

const PROCESS_STEPS = [
  ['parse_question', '解析问题'],
  ['build_request', '构造分析请求'],
  ['run_analysis', '计算归因'],
  ['extract_findings', '提取关键发现'],
  ['generate_report', '生成报告'],
  ['validate_report', '校验证据'],
  ['finalize', '整理最终结果'],
] as const

function ProgressPanel({ events, streamIssue }: { events: TaskProgressEvent[], streamIssue: string | null }) {
  const nodeState = new Map<string, 'active' | 'done'>()
  for (const event of events) {
    if (!event.node) continue
    if (event.type === 'node_started') nodeState.set(event.node, 'active')
    if (event.type === 'node_completed') nodeState.set(event.node, 'done')
  }
  const details = events.filter((event) => event.type === 'detail').slice(-4)
  const activeMessage = [...events].reverse().find((event) => event.type === 'detail' || event.type === 'node_started' || event.type === 'task_started')?.message

  return (
    <section className="progress-panel">
      <div className="progress-head">
        <div className="loading-orbit"><i /><i /><i /></div>
        <div>
          <p className="eyebrow">Live analysis</p>
          <h2>{activeMessage || '正在建立实时分析连接'}</h2>
          <p>任务正在后台运行，离开页面后仍会保存最终结果。</p>
        </div>
      </div>
      <div className="process-steps">
        {PROCESS_STEPS.map(([node, label]) => {
          const state = nodeState.get(node) ?? 'pending'
          return <div className={`process-step ${state}`} key={node}><i /> <span>{label}</span></div>
        })}
      </div>
      {details.length > 0 && (
        <div className="progress-details">
          {details.map((event, index) => <p key={`${event.stage}-${index}`}><span>·</span>{event.message}</p>)}
        </div>
      )}
      {streamIssue && <p className="stream-issue">{streamIssue}</p>}
    </section>
  )
}

function ReportContent({ report }: { report: string }) {
  return (
    <div className="report-content">
      {report.split('\n').map((line, index) => {
        const content = line.replace(/^#+\s*/, '').trim()
        if (!content) return <div className="report-spacer" key={`space-${index}`} />
        if (line.startsWith('# ')) return <h2 key={index}>{content}</h2>
        if (line.startsWith('## ')) return <h3 key={index}>{content}</h3>
        if (line.startsWith('- ') || line.startsWith('* ')) return <p className="report-list-item" key={index}>• {content}</p>
        if (line.startsWith('---')) return <hr key={index} />
        return <p key={index}>{content}</p>
      })}
    </div>
  )
}

function Findings({ findings }: { findings: Finding[] }) {
  if (!findings.length) return null

  return (
    <section className="card findings-card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Attribution</p>
          <h2>关键归因</h2>
        </div>
        <span className="subtle-label">按影响绝对值排序</span>
      </div>
      <div className="finding-list">
        {findings.map((finding, index) => (
          <article className="finding" key={`${finding.dimension}-${finding.group}-${index}`}>
            <span className={`finding-rank ${findingTone(finding.effect)}`}>{String(index + 1).padStart(2, '0')}</span>
            <div className="finding-copy">
              <p><strong>{finding.dimension}</strong><span className="dot">·</span>{finding.group}</p>
              <span>{finding.description || '该维度对整体转化率产生显著影响'}</span>
            </div>
            <strong className={`effect ${findingTone(finding.effect)}`}>{formatEffect(finding.effect)}</strong>
          </article>
        ))}
      </div>
    </section>
  )
}

function FunnelSummary({ response }: { response: CompletedResponse }) {
  const baseline = response.analysis_result.baseline_funnel
  const current = response.analysis_result.current_funnel
  const stages = response.analysis_result.stage_decomposition?.stages ?? []
  const timeRange = response.analysis_result.time_range

  if (!baseline || !current) return null

  return (
    <section className="card funnel-card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Funnel</p>
          <h2>核心漏斗</h2>
        </div>
        {timeRange?.baseline_start && timeRange?.current_start && (
          <span className="subtle-label">{timeRange.baseline_start} 对比 {timeRange.current_start}</span>
        )}
      </div>
      <div className="conversion-hero">
        <div>
          <span>整体转化率</span>
          <strong>{formatPercent(current.order_rate)}</strong>
        </div>
        <div className="conversion-delta">
          <span>较基准期</span>
          <strong>{formatEffect(response.analysis_result.funnel_change?.order_rate_change)}</strong>
        </div>
      </div>
      <div className="funnel-grid">
        {[
          ['访问会话', baseline.visit_sessions, current.visit_sessions, '个'],
          ['加购率', baseline.cart_rate, current.cart_rate, '%'],
          ['加购→下单', baseline.cart_to_order_rate, current.cart_to_order_rate, '%'],
          ['下单会话', baseline.order_sessions, current.order_sessions, '个'],
        ].map(([label, previous, latest, unit]) => {
          const isPercent = unit === '%'
          return (
            <div className="metric" key={String(label)}>
              <span>{label}</span>
              <strong>{isPercent ? formatPercent(latest as number) : Number(latest).toLocaleString()}</strong>
              <small>基准期 {isPercent ? formatPercent(previous as number) : Number(previous).toLocaleString()}</small>
            </div>
          )
        })}
      </div>
      {stages.length > 0 && (
        <div className="stage-list">
          {stages.map((stage) => (
            <div className="stage-row" key={stage.stage_name}>
              <span>{stage.stage_name}</span>
              <div className="stage-track"><i style={{ width: `${Math.max(7, stage.current_rate * 100)}%` }} /></div>
              <strong>{formatPercent(stage.current_rate)}</strong>
              <small>{formatEffect(stage.effect_on_overall)}</small>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function Events({ response }: { response: CompletedResponse }) {
  if (!response.matched_events.length) return null
  return (
    <section className="card events-card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Evidence</p>
          <h2>关联经营事件</h2>
        </div>
        <span className="subtle-label">仅表示关联，不代表因果</span>
      </div>
      <div className="event-list">
        {response.matched_events.map((event, index) => (
          <article className="event" key={`${event.title}-${index}`}>
            <span className={`severity severity-${event.severity ?? 'medium'}`} />
            <div>
              <strong>{event.title || '未命名事件'}</strong>
              <p>{event.description || '暂无事件描述'}</p>
            </div>
            {event.event_type && <span className="event-type">{event.event_type}</span>}
          </article>
        ))}
      </div>
    </section>
  )
}

function MarketSummary({ response }: { response: CompletedResponse }) {
  const baseline = response.analysis_result.baseline_summary
  const current = response.analysis_result.current_summary
  const timeRange = {
    baseline: response.analysis_result.baseline_period,
    current: response.analysis_result.current_period,
  }

  if (!baseline || !current) return null

  const roiChange = current.overall_roi - baseline.overall_roi
  const revenueChange = current.total_revenue - baseline.total_revenue
  const spendChange = current.total_ad_spend - baseline.total_ad_spend

  return (
    <section className="card funnel-card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Market Performance</p>
          <h2>市场表现概览</h2>
        </div>
        {timeRange.baseline?.start && timeRange.current?.start && (
          <span className="subtle-label">{timeRange.baseline.start} 对比 {timeRange.current.start}</span>
        )}
      </div>
      <div className="conversion-hero">
        <div>
          <span>整体 ROI</span>
          <strong>{formatROI(current.overall_roi)}</strong>
        </div>
        <div className="conversion-delta">
          <span>较基准期</span>
          <strong className={roiChange < 0 ? 'negative' : 'positive'}>
            {roiChange >= 0 ? '+' : ''}{formatROI(roiChange)}
          </strong>
        </div>
      </div>
      <div className="funnel-grid">
        <div className="metric">
          <span>基准期收入</span>
          <strong>{formatCurrency(baseline.total_revenue)}</strong>
          <small>广告花费 {formatCurrency(baseline.total_ad_spend)}</small>
        </div>
        <div className="metric">
          <span>当前期收入</span>
          <strong>{formatCurrency(current.total_revenue)}</strong>
          <small>广告花费 {formatCurrency(current.total_ad_spend)}</small>
        </div>
        <div className="metric">
          <span>收入变化</span>
          <strong className={revenueChange < 0 ? 'negative' : 'positive'}>
            {revenueChange >= 0 ? '+' : ''}{formatCurrency(revenueChange)}
          </strong>
          <small>花费变化 {spendChange >= 0 ? '+' : ''}{formatCurrency(spendChange)}</small>
        </div>
      </div>
    </section>
  )
}

function ChannelEfficiencyTable({ response }: { response: CompletedResponse }) {
  const channelChanges = response.analysis_result.channel_changes
  const abnormalChannels = response.analysis_result.abnormal_channels

  if (!channelChanges || channelChanges.length === 0) return null

  return (
    <section className="card events-card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Channel Efficiency</p>
          <h2>渠道效率对比</h2>
        </div>
        <span className="subtle-label">按 ROI 变化排序</span>
      </div>
      <div className="event-list">
        {channelChanges
          .sort((a, b) => a.roi_change_rate - b.roi_change_rate)
          .map((change, index) => {
            const isAbnormal = abnormalChannels?.some((ch) => ch.channel === change.channel)
            return (
              <article className="event" key={change.channel}>
                <span className={`severity ${isAbnormal ? 'severity-high' : 'severity-low'}`} />
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                    <strong>{change.channel}</strong>
                    {isAbnormal && (
                      <span style={{
                        fontSize: '11px',
                        padding: '2px 6px',
                        background: 'rgba(239, 68, 68, 0.1)',
                        color: '#dc2626',
                        borderRadius: '4px',
                      }}>
                        异常
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', fontSize: '13px' }}>
                    <div>
                      <span style={{ color: 'var(--text-secondary, #6b7280)' }}>ROI</span>
                      <div>
                        {formatROI(change.baseline.roi)} → {formatROI(change.current.roi)}
                        <span style={{ marginLeft: '4px', color: change.roi_change < 0 ? '#dc2626' : '#16a34a' }}>
                          ({change.roi_change >= 0 ? '+' : ''}{formatROI(change.roi_change)})
                        </span>
                      </div>
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-secondary, #6b7280)' }}>广告花费</span>
                      <div>{formatCurrency(change.current.ad_spend)}</div>
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-secondary, #6b7280)' }}>收入</span>
                      <div>{formatCurrency(change.current.revenue)}</div>
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-secondary, #6b7280)' }}>转化率</span>
                      <div>{formatPercent(change.current.cvr * 100)}</div>
                    </div>
                  </div>
                </div>
              </article>
            )
          })}
      </div>
    </section>
  )
}

function CompletedView({ response }: { response: CompletedResponse }) {
  // 判断是否为市场表现分析
  const isMarketAnalysis = response.analysis_result.baseline_summary && 
                           response.analysis_result.channel_changes

  return (
    <div className="result-layout">
      <div className="primary-column">
        <section className="card report-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Validated report</p>
              <h2>归因分析报告</h2>
            </div>
            <span className="validated">已通过证据校验</span>
          </div>
          <ReportContent report={response.report} />
        </section>
        {isMarketAnalysis ? (
          <ChannelEfficiencyTable response={response} />
        ) : (
          <Events response={response} />
        )}
      </div>
      <aside className="insight-column">
        {isMarketAnalysis ? (
          <>
            <MarketSummary response={response} />
            <Findings findings={response.key_findings} />
          </>
        ) : (
          <>
            <FunnelSummary response={response} />
            <Findings findings={response.key_findings} />
          </>
        )}
      </aside>
    </div>
  )
}

function LegacyApp() {
  const [question, setQuestion] = useState(EXAMPLE_QUESTIONS[0])
  const [conversationId, setConversationId] = useState(initialConversationId)
  const [viewState, setViewState] = useState<ViewState>('idle')
  const [response, setResponse] = useState<AnalysisResponse | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [tasks, setTasks] = useState<AnalysisTaskSummary[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [isRestoringTask, setIsRestoringTask] = useState(false)
  const [progressEvents, setProgressEvents] = useState<TaskProgressEvent[]>([])
  const [streamIssue, setStreamIssue] = useState<string | null>(null)
  const socketRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    globalThis.localStorage?.setItem(ACTIVE_CONVERSATION_KEY, conversationId)
  }, [conversationId])

  useEffect(() => () => {
    socketRef.current?.close()
  }, [])

  useEffect(() => {
    async function hydrateHistory() {
      try {
        const savedConversations = await listConversations()
        setConversations(savedConversations)
        const activeConversation = savedConversations.find((item) => item.conversation_id === conversationId)
        if (activeConversation?.last_task_id) {
          await restoreTask(activeConversation.last_task_id)
          const savedTasks = await listConversationTasks(activeConversation.conversation_id)
          setTasks(savedTasks)
        }
      } catch (error) {
        setHistoryError(error instanceof Error ? error.message : '无法读取历史记录。')
      } finally {
        setHistoryLoading(false)
      }
    }
    void hydrateHistory()
  }, [])

  async function refreshHistory(activeConversationId: string) {
    const [savedConversations, savedTasks] = await Promise.all([
      listConversations(),
      listConversationTasks(activeConversationId),
    ])
    setConversations(savedConversations)
    setTasks(savedTasks)
    setHistoryError(null)
  }

  function closeTaskStream() {
    if (socketRef.current) {
      socketRef.current.onclose = null
      socketRef.current.close()
      socketRef.current = null
    }
  }

  async function restoreTerminalTask(taskId: string) {
    try {
      const detail = await getTask(taskId)
      const savedResponse = toStoredResponse(detail)
      if (savedResponse) {
        setResponse(savedResponse)
        setViewState(savedResponse.status)
        setStreamIssue(null)
      } else {
        setStreamIssue('实时连接已关闭，但任务仍在运行；可从历史任务中稍后刷新查看。')
      }
    } catch (error) {
      setStreamIssue(error instanceof Error ? error.message : '无法恢复任务最终状态。')
    }
  }

  function openTaskStream(taskId: string, activeConversationId: string) {
    closeTaskStream()
    let terminalReceived = false
    let socket: WebSocket

    try {
      socket = new WebSocket(taskStreamUrl(taskId))
    } catch (error) {
      setStreamIssue(error instanceof Error ? error.message : '无法创建实时连接。')
      void restoreTerminalTask(taskId)
      return
    }

    socketRef.current = socket
    socket.onmessage = (messageEvent) => {
      let event: TaskProgressEvent
      try {
        event = JSON.parse(messageEvent.data) as TaskProgressEvent
      } catch {
        return
      }
      setProgressEvents((previous) => [...previous, event].slice(-40))

      if (event.type === 'terminal' && event.response) {
        terminalReceived = true
        socketRef.current = null
        setResponse(event.response)
        setViewState(event.response.status)
        setStreamIssue(null)
        void refreshHistory(activeConversationId).catch((error) => {
          setHistoryError(error instanceof Error ? error.message : '分析完成，但历史记录刷新失败。')
        })
      }

      if (event.type === 'snapshot' && event.task) {
        terminalReceived = true
        socketRef.current = null
        const savedResponse = toStoredResponse(event.task)
        if (savedResponse) {
          setQuestion(event.task.question)
          setResponse(savedResponse)
          setViewState(savedResponse.status)
          setStreamIssue(null)
        }
      }

      if (event.type === 'stream_error') {
        setStreamIssue(event.message || '实时连接不可用，正在尝试读取已保存的任务状态。')
      }
    }
    socket.onerror = () => {
      setStreamIssue('实时连接出现异常；任务仍会继续在后台执行。')
    }
    socket.onclose = () => {
      if (!terminalReceived) {
        void restoreTerminalTask(taskId)
      }
      if (socketRef.current === socket) socketRef.current = null
    }
  }

  async function restoreTask(taskId: string) {
    setIsRestoringTask(true)
    try {
      const detail = await getTask(taskId)
      const savedResponse = toStoredResponse(detail)
      setQuestion(detail.question)
      setConversationId(detail.conversation_id)
      if (savedResponse) {
        setResponse(savedResponse)
        setViewState(savedResponse.status)
        setStreamIssue(null)
      } else if (detail.status === 'running') {
        setResponse(null)
        setViewState('loading')
        setProgressEvents([{ type: 'task_started', task_id: detail.task_id, message: '正在恢复后台任务的实时连接' }])
        setStreamIssue(null)
        openTaskStream(detail.task_id, detail.conversation_id)
      } else {
        setResponse(null)
        setViewState('idle')
      }
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : '无法加载任务详情。')
    } finally {
      setIsRestoringTask(false)
    }
  }

  async function selectConversation(nextConversationId: string, taskId?: string | null) {
    if (nextConversationId === conversationId && taskId) {
      await restoreTask(taskId)
      return
    }
    setConversationId(nextConversationId)
    setResponse(null)
    setViewState('idle')
    setHistoryError(null)
    setIsRestoringTask(true)
    try {
      const savedTasks = await listConversationTasks(nextConversationId)
      setTasks(savedTasks)
      const targetTask = taskId ?? savedTasks[0]?.task_id
      if (targetTask) await restoreTask(targetTask)
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : '无法读取此会话的任务记录。')
    } finally {
      setIsRestoringTask(false)
    }
  }

  function startNewConversation() {
    if (viewState === 'loading') return
    closeTaskStream()
    const nextConversationId = createConversationId()
    setConversationId(nextConversationId)
    setQuestion(EXAMPLE_QUESTIONS[0])
    setResponse(null)
    setRequestError(null)
    setViewState('idle')
    setTasks([])
    setHistoryError(null)
    setProgressEvents([])
    setStreamIssue(null)
  }

  async function submitAnalysis(event?: FormEvent) {
    event?.preventDefault()
    const trimmedQuestion = question.trim()
    if (!trimmedQuestion || viewState === 'loading') return

    closeTaskStream()
    setViewState('loading')
    setResponse(null)
    setRequestError(null)
    setStreamIssue(null)
    setProgressEvents([{ type: 'task_started', message: '正在创建后台分析任务' }])

    try {
      const accepted = await createAnalysisTask(trimmedQuestion, conversationId)
      setConversationId(accepted.conversation_id)
      setProgressEvents([{ type: 'task_started', task_id: accepted.task_id, message: '任务已创建，正在连接实时进度' }])
      openTaskStream(accepted.task_id, accepted.conversation_id)
      void refreshHistory(accepted.conversation_id).catch((historyError) => {
        setHistoryError(historyError instanceof Error ? historyError.message : '任务已创建，但历史记录刷新失败。')
      })
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : '请求失败，请稍后重试。')
      setViewState('failed')
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      void submitAnalysis()
    }
  }

  const isLoading = viewState === 'loading'

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="经营归因分析首页">
          <span className="brand-mark"><i /><i /><i /></span>
          <span>经营归因分析<span className="brand-suffix">/ Analysis Studio</span></span>
        </a>
        <div className={`system-status ${historyError ? 'warning' : ''}`}><span /> {historyError ? '历史暂不可用' : '持久化已启用'}</div>
      </header>

      <main id="top" className="workspace">
        <aside className="sidebar">
          <div className="side-intro">
            <p className="eyebrow">Analysis agent</p>
            <h1>让数据解释<br />经营变化</h1>
            <p>基于漏斗拆解、维度归因与经营事件，生成带证据校验的分析结论。</p>
          </div>

          <button className="new-conversation" onClick={startNewConversation} type="button" disabled={isLoading}><span>＋</span> 新建会话</button>

          <div className="history-block">
            <div className="history-heading"><span className="side-label">会话历史</span>{historyLoading && <small>加载中</small>}</div>
            {conversations.length > 0 ? conversations.map((item) => (
              <button
                className={item.conversation_id === conversationId ? 'conversation active' : 'conversation'}
                key={item.conversation_id}
                onClick={() => { void selectConversation(item.conversation_id, item.last_task_id) }}
                type="button"
                disabled={isLoading}
              >
                <strong>{item.title}</strong>
                <span><i className={`status-dot ${item.last_task_status ?? 'running'}`} />{statusLabel(item.last_task_status)} · {item.task_count} 条任务</span>
              </button>
            )) : !historyLoading && <p className="history-empty">首个问题提交后，会在这里保存为可回放会话。</p>}
            {historyError && <p className="history-error">{historyError}</p>}
          </div>

          {tasks.length > 0 && (
            <div className="task-block">
              <span className="side-label">当前会话任务</span>
              {tasks.map((task) => (
                <button className="task-record" key={task.task_id} onClick={() => { void restoreTask(task.task_id) }} type="button" disabled={isLoading}>
                  <span><i className={`status-dot ${task.status}`} />{statusLabel(task.status)}</span>
                  <small>{formatTaskTime(task.created_at)}</small>
                </button>
              ))}
            </div>
          )}

          <div className="data-window">
            <span className="window-icon">⌁</span>
            <div>
              <strong>演示数据窗口</strong>
              <p>2026.04.01–07.31<br />可对比任意月份或周</p>
            </div>
          </div>

          <div className="example-block">
            <span className="side-label">可以这样问</span>
            {EXAMPLE_QUESTIONS.map((example) => (
              <button
                className={question === example ? 'example active' : 'example'}
                key={example}
                onClick={() => setQuestion(example)}
                type="button"
                disabled={isLoading}
              >
                {example}
              </button>
            ))}
          </div>
          <p className="sidebar-footnote">结论均需通过证据校验；经营事件仅用于关联提示。</p>
        </aside>

        <section className="analysis-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">New analysis</p>
              <h2>从一个经营问题开始</h2>
            </div>
            <span className="conversation-tag">会话 {conversationId.slice(0, 8)} {isRestoringTask && '· 正在回放'}</span>
          </div>

          <form className="question-card" onSubmit={submitAnalysis}>
            <label htmlFor="question">你想了解什么？</label>
            <textarea
              id="question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder="例如：为什么本月整体转化率比上月下降了？"
              maxLength={1000}
              rows={3}
              disabled={isLoading}
            />
            <div className="composer-footer">
              <span>⌘ / Ctrl + Enter 发送</span>
              <button className="submit-button" type="submit" disabled={isLoading || !question.trim()}>
                {isLoading ? <><i className="spinner" />分析中</> : <>开始分析 <b>↗</b></>}
              </button>
            </div>
          </form>

          <div className="results" aria-live="polite">
            {viewState === 'idle' && (
              <section className="empty-state">
                <span className="empty-orbit"><i /><i /><i /></span>
                <h2>准备好了</h2>
                <p>输入一个关于转化、渠道、设备或漏斗的问题，开始生成归因分析。</p>
              </section>
            )}

            {isLoading && <ProgressPanel events={progressEvents} streamIssue={streamIssue} />}

            {viewState === 'clarify' && response?.status === 'clarify' && (
              <section className="state-card clarify-card">
                <span className="state-icon">?</span>
                <div>
                  <p className="eyebrow">Need more context</p>
                  <h2>还需要补充一点信息</h2>
                  <p>{response.clarification_question}</p>
                  <small>在上方补充完整问题后再次提交即可；这次追问已保存到任务历史。</small>
                </div>
              </section>
            )}

            {viewState === 'failed' && (
              <section className="state-card failed-card">
                <span className="state-icon">!</span>
                <div>
                  <p className="eyebrow">Analysis unavailable</p>
                  <h2>这次分析没有完成</h2>
                  <ul>
                    {response?.status === 'failed'
                      ? response.errors.map((error) => <li key={error}>{error}</li>)
                      : <li>{requestError || '请求失败，请稍后重试。'}</li>}
                  </ul>
                  <small>失败原因也会写入任务记录；请确认后端服务、数据库与模型配置后重试。</small>
                </div>
              </section>
            )}

            {viewState === 'completed' && response?.status === 'completed' && <CompletedView response={response} />}
          </div>
        </section>
      </main>
    </div>
  )
}

function App() {
  return <Workbench />
}

export default App
