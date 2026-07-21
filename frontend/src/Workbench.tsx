import { ChangeEvent, FormEvent, useEffect, useRef, useState } from 'react'
import {
  attachmentDownloadUrl,
  cancelWorkbenchTask,
  chatStreamUrl,
  createChat,
  deleteAttachment,
  deleteChat,
  getChat,
  getCurrentUser,
  getWorkbenchTask,
  getWsToken,
  listChats,
  login,
  logout,
  renameChat,
  resultExportUrl,
  sendChatMessage,
  uploadAttachment,
} from './api'
import type {
  AnalysisResponse,
  AnalysisTaskDetail,
  AppUser,
  ChatDetail,
  ChatStreamEvent,
  CompletedResponse,
  ConversationSummary,
  TaskStatus,
} from './types'
import { ConfigPage } from './ConfigPage'
import { LogPage } from './LogPage'

const EXAMPLES = [
  '为什么本期整体转化率比基准期下降？',
  '请按渠道拆解 2026 年 7 月与 6 月前两周的转化变化。',
  '哪个设备和漏斗环节对下单转化率下降影响最大？',
]

function taskLabel(status?: TaskStatus | null) {
  return ({ running: '分析中', clarify: '待补充', completed: '已完成', failed: '失败', cancelled: '已取消' })[status ?? 'running']
}

function dateLabel(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '' : new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(parsed)
}

function responseFromTask(task: AnalysisTaskDetail): AnalysisResponse | null {
  if (task.status === 'completed' && task.report) {
    return { status: 'completed', conversation_id: task.conversation_id, task_id: task.task_id, report: task.report, key_findings: task.key_findings, analysis_result: task.analysis_result, evidence: task.evidence, matched_events: task.matched_events }
  }
  if (task.status === 'clarify' && task.clarification_question) return { status: 'clarify', conversation_id: task.conversation_id, task_id: task.task_id, clarification_question: task.clarification_question }
  if (task.status === 'failed') return { status: 'failed', conversation_id: task.conversation_id, task_id: task.task_id, errors: task.errors }
  if (task.status === 'cancelled') return { status: 'cancelled', conversation_id: task.conversation_id, task_id: task.task_id }
  return null
}

function ReportText({ report }: { report: string }) {
  return <div className="wb-report">{report.split('\n').map((line, index) => {
    if (!line.trim()) return <div key={index} className="wb-spacer" />
    if (line.startsWith('### ')) return <h4 key={index}>{line.slice(4)}</h4>
    if (line.startsWith('## ')) return <h3 key={index}>{line.slice(3)}</h3>
    if (line.startsWith('# ')) return <h2 key={index}>{line.slice(2)}</h2>
    if (line.startsWith('- ')) return <p className="wb-list" key={index}>• {line.slice(2)}</p>
    return <p key={index}>{line}</p>
  })}</div>
}

function LoginCard({ onLoggedIn }: { onLoggedIn: (user: AppUser) => void }) {
  const [username, setUsername] = useState('analyst')
  const [displayName, setDisplayName] = useState('分析用户')
  const [error, setError] = useState<string | null>(null)
  async function submit(event: FormEvent) {
    event.preventDefault()
    try {
      const result = await login(username, displayName)
      onLoggedIn(result.user)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '登录失败') }
  }
  return <main className="login-page"><form className="login-card" onSubmit={submit}>
    <span className="login-mark">A</span><p className="eyebrow">Analysis Studio</p><h1>进入经营归因工作台</h1>
    <p>本地课程环境使用独立的演示账号；生产环境可将此页替换为企业 OAuth 登录。</p>
    <label>账号<input value={username} onChange={(event) => setUsername(event.target.value)} minLength={2} required /></label>
    <label>显示名称<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label>
    {error && <p className="login-error">{error}</p>}<button type="submit">登录工作台</button>
  </form></main>
}

function Workbench() {
  const [user, setUser] = useState<AppUser | null>(null)
  const [authReady, setAuthReady] = useState(false)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [detail, setDetail] = useState<ChatDetail | null>(null)
  const [question, setQuestion] = useState(EXAMPLES[0])
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null)
  const [selectedResult, setSelectedResult] = useState<AnalysisResponse | null>(null)
  const [events, setEvents] = useState<ChatStreamEvent[]>([])
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [currentPage, setCurrentPage] = useState<'workbench' | 'config' | 'logs'>('workbench')
  const [logTaskId, setLogTaskId] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const socketRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    void getCurrentUser().then(setUser).catch(() => setUser(null)).finally(() => setAuthReady(true))
    return () => socketRef.current?.close()
  }, [])

  useEffect(() => {
    if (!user) return
    void initializeWorkspace()
  }, [user?.user_id])

  async function refreshConversations() {
    const rows = await listChats()
    setConversations(rows)
    return rows
  }

  async function loadConversation(id: string, preferredTaskId?: string | null) {
    const loaded = await getChat(id)
    setConversationId(id)
    setDetail(loaded)
    const taskId = preferredTaskId ?? loaded.tasks[0]?.task_id
    if (taskId) await selectTask(taskId)
    else setSelectedResult(null)
  }

  async function initializeWorkspace() {
    try {
      const rows = await refreshConversations()
      if (rows[0]) await loadConversation(rows[0].conversation_id, rows[0].last_task_id)
      else {
        const created = await createChat('我的归因分析')
        setConversations([created])
        await loadConversation(created.conversation_id)
      }
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : '无法初始化工作台') }
  }

  async function selectTask(taskId: string) {
    try {
      const task = await getWorkbenchTask(taskId)
      setSelectedResult(responseFromTask(task))
      if (task.status === 'running') {
        setActiveTaskId(taskId)
        void openStream(taskId)
      }
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : '无法加载任务结果') }
  }

  async function createConversation() {
    try {
      const created = await createChat('新的归因分析')
      await refreshConversations()
      await loadConversation(created.conversation_id)
      setQuestion(EXAMPLES[0])
      setEvents([])
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : '新建会话失败') }
  }

  async function reloadActiveConversation() {
    if (!conversationId) return
    const current = await getChat(conversationId)
    setDetail(current)
    await refreshConversations()
  }

  async function openStream(taskId: string) {
    socketRef.current?.close()
    let streamingContent = ''
    try {
      const { token } = await getWsToken(taskId)
      const socket = new WebSocket(chatStreamUrl(taskId, token))
      socketRef.current = socket
      socket.onmessage = (message) => {
        let event: ChatStreamEvent
        try { event = JSON.parse(message.data) as ChatStreamEvent } catch { return }
        setEvents((previous) => [...previous, event].slice(-30))
        
        // 处理流式文本增量
        if (event.type === 'message_delta' && event.delta_text) {
          streamingContent += event.delta_text
          // 创建一个临时的流式结果显示
          setSelectedResult({
            status: 'completed',
            conversation_id: '',
            task_id: taskId,
            report: streamingContent,
            key_findings: [],
            analysis_result: {},
            evidence: {},
            matched_events: []
          })
        }
        
        if (event.type === 'result_ready' && event.response) {
          setSelectedResult(event.response)
          streamingContent = '' // 重置流式内容
        }
        if (event.type === 'error') setNotice(event.message ?? '实时任务发生错误')
        if (event.type === 'done') {
          setActiveTaskId(null)
          void reloadActiveConversation().catch((reason) => setNotice(reason instanceof Error ? reason.message : '任务已完成，但历史刷新失败'))
        }
      }
      socket.onerror = () => setNotice('实时连接异常，正在保留后台任务并可稍后刷新查看')
      socket.onclose = () => { if (socketRef.current === socket) socketRef.current = null }
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : '无法连接实时任务') }
  }

  async function submit(event?: FormEvent) {
    event?.preventDefault()
    if (!conversationId || !question.trim() || busy || activeTaskId) return
    setBusy(true); setNotice(null); setSelectedResult(null); setEvents([])
    try {
      const task = await sendChatMessage(conversationId, question.trim())
      setQuestion('')
      setActiveTaskId(task.task_id)
      await reloadActiveConversation()
      await openStream(task.task_id)
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : '提交分析任务失败') }
    finally { setBusy(false) }
  }

  async function cancelTask() {
    if (!activeTaskId) return
    try {
      await cancelWorkbenchTask(activeTaskId)
      setNotice('已请求取消；当前节点完成后将停止并保存“已取消”状态。')
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : '取消请求失败') }
  }

  async function uploadFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file || !conversationId) return
    setBusy(true)
    try {
      await uploadAttachment(conversationId, file)
      await reloadActiveConversation()
      setNotice(`已解析附件：${file.name}`)
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : '附件上传失败') }
    finally { setBusy(false); event.target.value = '' }
  }

  async function removeAttachment(id: string) {
    try { await deleteAttachment(id); await reloadActiveConversation() }
    catch (reason) { setNotice(reason instanceof Error ? reason.message : '附件删除失败') }
  }

  async function signOut() {
    await logout(); setUser(null); setDetail(null); setConversationId(null); setAccountOpen(false)
  }

  function startRename(id: string, currentTitle: string) {
    setRenamingId(id)
    setRenameValue(currentTitle)
  }

  async function confirmRename() {
    if (!renamingId || !renameValue.trim()) { setRenamingId(null); return }
    try {
      await renameChat(renamingId, renameValue.trim())
      await refreshConversations()
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : '重命名失败') }
    finally { setRenamingId(null) }
  }

  function cancelRename() {
    setRenamingId(null)
    setRenameValue('')
  }

  async function removeConversation(id: string) {
    if (!window.confirm('确定要删除这个会话吗？所有相关消息和任务都将被删除。')) return
    try {
      await deleteChat(id)
      if (conversationId === id) {
        setConversationId(null)
        setDetail(null)
        setSelectedResult(null)
      }
      await refreshConversations()
      setNotice('会话已删除')
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : '删除失败') }
  }

  function copyResult() {
    if (!selectedResult || selectedResult.status !== 'completed') return
    const text = selectedResult.report
    navigator.clipboard.writeText(text).then(() => {
      setNotice('报告已复制到剪贴板')
    }).catch(() => {
      setNotice('复制失败，请手动选择文本复制')
    })
  }

  if (!authReady) return <main className="login-page"><p>正在加载工作台…</p></main>
  if (!user) return <LoginCard onLoggedIn={setUser} />

  // 配置页面
  if (currentPage === 'config') {
    return <ConfigPage onBack={() => setCurrentPage('workbench')} userRole={user.role} />
  }

  // 日志页面
  if (currentPage === 'logs' && logTaskId) {
    return <LogPage taskId={logTaskId} onBack={() => { setCurrentPage('workbench'); setLogTaskId(null) }} />
  }

  return <div className="wb-shell">
    <header className="wb-topbar"><div className="wb-brand"><span>▥</span><strong>经营归因分析</strong><small>Analysis Studio</small></div>
      <div className="wb-topbar-actions">
        {user.role === 'admin' && (
          <button className="wb-nav-btn" onClick={() => setCurrentPage('config')}>系统配置</button>
        )}
        <div className="wb-account"><button onClick={() => setAccountOpen(!accountOpen)}>{user.display_name} · {user.role === 'admin' ? '管理员' : '分析用户'}⌄</button>
          {accountOpen && <div className="wb-account-menu"><p>{user.username}</p><button onClick={() => void signOut()}>退出登录</button></div>}</div>
      </div>
    </header>
    <main className="wb-workspace">
      <aside className="wb-conversations"><button className="wb-new" onClick={() => void createConversation()} disabled={Boolean(activeTaskId)}>＋ 新建会话</button>
        <p className="wb-label">会话历史</p>
        <div className="wb-session-list">{conversations.map((item) => {
          const isActive = item.conversation_id === conversationId
          const isRenaming = item.conversation_id === renamingId
          return <div key={item.conversation_id} className={isActive ? 'wb-session active' : 'wb-session'} onClick={() => { if (!isRenaming) void loadConversation(item.conversation_id, item.last_task_id) }} onDoubleClick={() => startRename(item.conversation_id, item.title)}>
            {isRenaming ? (
              <input className="wb-rename-input" value={renameValue} onChange={(e) => setRenameValue(e.target.value)} onBlur={confirmRename} onKeyDown={(e) => { if (e.key === 'Enter') void confirmRename(); if (e.key === 'Escape') cancelRename() }} autoFocus onClick={(e) => e.stopPropagation()} />
            ) : (
              <strong>{item.title}</strong>
            )}
            <span><i className={`wb-dot ${item.last_task_status ?? 'running'}`} />{taskLabel(item.last_task_status)} · {item.task_count} 次</span>
            <button className="wb-delete-btn" onClick={(e) => { e.stopPropagation(); void removeConversation(item.conversation_id) }} title="删除会话">×</button>
          </div>
        })}</div>
        <div className="wb-data-note"><b>演示数据窗口</b><span>2026.04.01–07.31<br />可对比任意月份或周</span></div>
      </aside>
      <section className="wb-dialog">
        <div className="wb-dialog-head"><div><p className="eyebrow">Conversation</p><h1>{conversations.find((item) => item.conversation_id === conversationId)?.title ?? '分析会话'}</h1></div><button className="wb-refresh" onClick={() => void reloadActiveConversation()}>刷新</button></div>
        {notice && <p className="wb-notice">{notice}</p>}
        <div className="wb-messages">{detail?.messages.length ? detail.messages.map((message) => <article className={`wb-message ${message.role}`} key={message.message_id}>
          <span>{message.role === 'user' ? '你' : 'AI'}</span><div>{message.role === 'assistant' ? <ReportText report={message.content} /> : <p>{message.content}</p>}<time>{dateLabel(message.created_at)}</time></div>
        </article>) : <div className="wb-empty"><span>◌</span><h2>从一个经营问题开始</h2><p>可提问转化、渠道、设备或漏斗问题；上传表格后，分析器会把它当作补充证据。</p>{EXAMPLES.map((example) => <button key={example} onClick={() => setQuestion(example)}>{example}</button>)}</div>}</div>
        {activeTaskId && <div className="wb-live"><div><b>正在实时分析</b><span>{events.slice(-1)[0]?.message ?? events.slice(-1)[0]?.label ?? '正在进入分析流程'}</span></div><button onClick={() => void cancelTask()}>取消任务</button><ol>{events.filter((event) => event.type === 'tool_start' || event.type === 'tool_finish').slice(-5).map((event, index) => <li key={`${event.type}-${index}`} className={event.type === 'tool_finish' ? 'done' : ''}>{event.label || event.node || '分析步骤'}</li>)}</ol></div>}
        <form className="wb-composer" onSubmit={submit}><textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：为什么本期转化率下降？" disabled={Boolean(activeTaskId)} /><div><span>Ctrl / ⌘ + Enter 发送</span><button type="submit" disabled={!question.trim() || Boolean(activeTaskId) || busy}>{activeTaskId ? '分析中…' : '开始分析 →'}</button></div></form>
      </section>
      <aside className="wb-side">
        <section className="wb-side-card"><div className="wb-side-heading"><div><p className="eyebrow">Attachments</p><h2>会话附件</h2></div><button onClick={() => fileInputRef.current?.click()} disabled={!conversationId || busy}>上传</button></div>
          <input ref={fileInputRef} type="file" accept=".csv,.xlsx,.xls,.txt" onChange={uploadFile} hidden />
          <p className="wb-side-tip">支持 CSV、XLSX、XLS、TXT，解析后的表头与预览可作为本轮分析的补充证据。</p>
          <div className="wb-attachments">{detail?.attachments.length ? detail.attachments.map((attachment) => <article key={attachment.id}><div><strong>{attachment.filename}</strong><span>{attachment.parse_status} · {attachment.parse_summary.row_count ?? 0} 行</span></div><div><a href={attachmentDownloadUrl(attachment.id)}>下载</a><button onClick={() => void removeAttachment(attachment.id)}>删除</button></div></article>) : <p>还没有附件</p>}</div>
        </section>
        <section className="wb-side-card wb-result"><div className="wb-side-heading"><div><p className="eyebrow">Result</p><h2>分析结果</h2></div><div className="wb-result-actions">{selectedResult?.status === 'completed' && selectedResult.task_id && <><button onClick={copyResult} title="复制报告">复制</button><a href={resultExportUrl(selectedResult.task_id)}>导出</a></>}</div></div>
          {selectedResult?.status === 'completed' && <><span className="wb-verified">已通过证据校验</span><ReportText report={selectedResult.report} /></>}
          {selectedResult?.status === 'clarify' && <p className="wb-result-state">需要补充：{selectedResult.clarification_question}</p>}
          {selectedResult?.status === 'failed' && <p className="wb-result-state error">{selectedResult.errors.join('；')}</p>}
          {selectedResult?.status === 'cancelled' && <p className="wb-result-state">任务已取消。</p>}
          {!selectedResult && <p className="wb-result-state">选择一条历史任务，或发起新的分析后在此查看结构化结果与导出。</p>}
          {detail?.tasks.length ? <div className="wb-task-list"><p className="wb-label">本会话任务</p>{detail.tasks.slice(0, 6).map((task) => <div key={task.task_id} style={{display: 'flex', alignItems: 'center', gap: '4px'}}><button style={{flex: 1}} onClick={() => void selectTask(task.task_id)}><i className={`wb-dot ${task.status}`} />{taskLabel(task.status)}<time>{dateLabel(task.created_at)}</time></button><button className="wb-task-log-btn" onClick={() => { setLogTaskId(task.task_id); setCurrentPage('logs') }}>日志</button></div>)}</div> : null}
        </section>
      </aside>
    </main>
  </div>
}

export default Workbench
