import { useEffect, useState } from 'react'
import { getTaskLogs } from './api'

type LogPageProps = {
  taskId: string
  onBack: () => void
}

type TaskLog = {
  log_id: string
  task_id: string
  level: string
  message: string
  created_at: string
}

export function LogPage({ taskId, onBack }: LogPageProps) {
  const [logs, setLogs] = useState<TaskLog[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void loadLogs()
  }, [taskId])

  async function loadLogs() {
    setLoading(true)
    setError(null)
    try {
      const result = await getTaskLogs(taskId)
      setLogs(result)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '加载日志失败')
    } finally {
      setLoading(false)
    }
  }

  function formatTime(value: string) {
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return ''
    return new Intl.DateTimeFormat('zh-CN', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }).format(date)
  }

  function levelColor(level: string) {
    const colors: Record<string, string> = {
      info: '#3b82f6',
      warning: '#f59e0b',
      error: '#ef4444',
      debug: '#6b7280',
    }
    return colors[level.toLowerCase()] || '#6b7280'
  }

  return (
    <div className="log-page">
      <div className="log-header">
        <button onClick={onBack} className="log-back">← 返回</button>
        <h1>任务日志</h1>
        <span className="log-task-id">任务 {taskId.slice(0, 8)}</span>
        <button onClick={loadLogs} disabled={loading} className="log-refresh">
          刷新
        </button>
      </div>

      {error && <p className="log-error">{error}</p>}

      {loading ? (
        <div className="log-loading">加载中...</div>
      ) : logs.length === 0 ? (
        <div className="log-empty">
          <p>暂无日志记录</p>
        </div>
      ) : (
        <div className="log-list">
          {logs.map((log) => (
            <div key={log.log_id} className="log-item">
              <span className="log-time">{formatTime(log.created_at)}</span>
              <span className="log-level" style={{ color: levelColor(log.level) }}>
                [{log.level.toUpperCase()}]
              </span>
              <span className="log-message">{log.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
