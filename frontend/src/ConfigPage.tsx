import { useEffect, useState } from 'react'
import { getAdminConfig, setAdminConfig, reloadAdminConfig } from './api'

type ConfigPageProps = {
  onBack: () => void
  userRole: 'analyst' | 'admin'
}

export function ConfigPage({ onBack, userRole }: ConfigPageProps) {
  const [runtime, setRuntime] = useState<Record<string, string>>({})
  const [overrides, setOverrides] = useState<Record<string, string>>({})
  const [editKey, setEditKey] = useState('')
  const [editValue, setEditValue] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    void loadConfig()
  }, [])

  async function loadConfig() {
    setLoading(true)
    try {
      const result = await getAdminConfig()
      setRuntime(result.runtime)
      setOverrides(result.overrides)
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : '加载配置失败')
    } finally {
      setLoading(false)
    }
  }

  async function handleSave() {
    if (!editKey.trim()) {
      setNotice('请输入配置键名')
      return
    }
    setSaving(true)
    setNotice(null)
    try {
      await setAdminConfig(editKey.trim(), editValue)
      setNotice('配置已保存')
      setEditKey('')
      setEditValue('')
      await loadConfig()
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : '保存配置失败')
    } finally {
      setSaving(false)
    }
  }

  async function handleReload() {
    setSaving(true)
    setNotice(null)
    try {
      await reloadAdminConfig()
      setNotice('配置已重新加载')
      await loadConfig()
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : '重新加载失败')
    } finally {
      setSaving(false)
    }
  }

  if (userRole !== 'admin') {
    return (
      <div className="config-page">
        <div className="config-header">
          <button onClick={onBack} className="config-back">← 返回</button>
          <h1>系统配置</h1>
        </div>
        <div className="config-empty">
          <p>仅管理员可访问配置页面</p>
        </div>
      </div>
    )
  }

  return (
    <div className="config-page">
      <div className="config-header">
        <button onClick={onBack} className="config-back">← 返回</button>
        <h1>系统配置</h1>
        <button onClick={handleReload} disabled={saving} className="config-reload">
          重新加载
        </button>
      </div>

      {notice && <p className="config-notice">{notice}</p>}

      {loading ? (
        <div className="config-loading">加载中...</div>
      ) : (
        <>
          <section className="config-section">
            <h2>当前运行配置</h2>
            <div className="config-list">
              {Object.entries(runtime).map(([key, value]) => (
                <div key={key} className="config-item">
                  <strong>{key}</strong>
                  <span>{value || '(未设置)'}</span>
                </div>
              ))}
              {Object.keys(runtime).length === 0 && (
                <p className="config-empty-hint">暂无运行配置</p>
              )}
            </div>
          </section>

          <section className="config-section">
            <h2>自定义覆盖</h2>
            <div className="config-list">
              {Object.entries(overrides).map(([key, value]) => (
                <div key={key} className="config-item override">
                  <strong>{key}</strong>
                  <span>{value}</span>
                </div>
              ))}
              {Object.keys(overrides).length === 0 && (
                <p className="config-empty-hint">暂无自定义覆盖</p>
              )}
            </div>
          </section>

          <section className="config-section config-edit">
            <h2>添加/修改配置</h2>
            <div className="config-form">
              <input
                type="text"
                placeholder="配置键名（如 RAG_VECTOR_BACKEND）"
                value={editKey}
                onChange={(e) => setEditKey(e.target.value)}
                disabled={saving}
              />
              <input
                type="text"
                placeholder="配置值"
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                disabled={saving}
              />
              <button onClick={handleSave} disabled={saving || !editKey.trim()}>
                {saving ? '保存中...' : '保存配置'}
              </button>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
