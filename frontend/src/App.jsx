import { useState, useEffect } from 'react'
import axios from 'axios'
import { sampleQuestions } from './mockData'
import ChatBrief from './ChatBrief'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || ''

/** Context-aware brief title from the user's question */
function getBriefTitle(messages, assistantIndex) {
  const prev = messages[assistantIndex - 1]
  const q = (prev?.text || '').toLowerCase()
  if (/product|feature|roadmap|platform/.test(q)) return "Today's Brief · Product"
  if (/sales|pricing|revenue|deal/.test(q)) return "Today's Brief · Sales"
  if (/company|team|people|who/.test(q)) return "Today's Brief · Company"
  if (/onboard|onboarding|getting started/.test(q)) return "Today's Brief · Onboarding"
  if (/engineer|tech stack|code|github|api/.test(q)) return "Today's Brief · Engineering"
  return "Today's Brief"
}

function App() {
  const [health, setHealth] = useState(null)
  const [syncStatus, setSyncStatus] = useState(null)
  const [syncTriggering, setSyncTriggering] = useState(false)
  const [intelFeed, setIntelFeed] = useState([])
  const [liveSearchQuery, setLiveSearchQuery] = useState('')
  const [liveSearchResults, setLiveSearchResults] = useState(null)
  const [liveSearchLoading, setLiveSearchLoading] = useState(false)
  const [renderUsage, setRenderUsage] = useState(null)
  const [intelRefreshing, setIntelRefreshing] = useState(false)
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [messages, setMessages] = useState([])
  const [briefLoading, setBriefLoading] = useState(false)

  useEffect(() => {
    axios.get(API_URL ? `${API_URL}/health` : '/health')
      .then(res => setHealth(res.data))
      .catch(() => setHealth({ status: 'disconnected', database: 'disconnected' }))
  }, [])

  useEffect(() => {
    axios.get(API_URL ? `${API_URL}/api/sync/status` : '/api/sync/status')
      .then(res => setSyncStatus(res.data))
      .catch(() => setSyncStatus(null))
  }, [])

  useEffect(() => {
    axios.get(API_URL ? `${API_URL}/api/intel/feed` : '/api/intel/feed')
      .then(res => setIntelFeed(Array.isArray(res.data) ? res.data : []))
      .catch(() => setIntelFeed([]))
  }, [])

  useEffect(() => {
    axios.get(API_URL ? `${API_URL}/api/render/usage` : '/api/render/usage')
      .then(res => setRenderUsage(res.data))
      .catch(() => setRenderUsage({ ok: false, error: 'Failed to load' }))
  }, [])

  const triggerSync = async () => {
    setSyncTriggering(true)
    try {
      const res = await axios.post(API_URL ? `${API_URL}/api/sync/trigger` : '/api/sync/trigger')
      setSyncStatus(prev => ({ ...prev, ...res.data, last_sync_at: res.data?.last_sync_at, next_sync_at: res.data?.next_sync_at }))
      const statusRes = await axios.get(API_URL ? `${API_URL}/api/sync/status` : '/api/sync/status')
      setSyncStatus(statusRes.data)
    } catch {
      setSyncStatus(prev => prev || {})
    } finally {
      setSyncTriggering(false)
    }
  }

  const refreshIntel = async () => {
    setIntelRefreshing(true)
    try {
      await axios.post(API_URL ? `${API_URL}/api/intel/refresh` : '/api/intel/refresh')
      const res = await axios.get(API_URL ? `${API_URL}/api/intel/feed` : '/api/intel/feed')
      setIntelFeed(Array.isArray(res.data) ? res.data : [])
    } catch {
      setIntelFeed([])
    } finally {
      setIntelRefreshing(false)
    }
  }

  const runLiveSearch = async (e) => {
    e?.preventDefault()
    const q = (typeof e?.target?.query?.value === 'string' ? e.target.query.value : liveSearchQuery).trim()
    if (!q) return
    setLiveSearchLoading(true)
    setLiveSearchResults(null)
    try {
      const res = await axios.get(API_URL ? `${API_URL}/api/intel/search` : '/api/intel/search', {
        params: { q, count: 8, freshness: 'month' },
      })
      setLiveSearchResults(res.data)
    } catch (err) {
      setLiveSearchResults({
        web: [],
        news: [],
        query: q,
        error: err.response?.data?.error || err.message || 'Search failed',
      })
    } finally {
      setLiveSearchLoading(false)
    }
  }

  const fetchDailyBrief = async () => {
    setBriefLoading(true)
    try {
      const res = await axios.get(API_URL ? `${API_URL}/api/brief` : '/api/brief', { timeout: 65000 })
      const brief = {
        summary: res.data?.summary ?? [],
        product: res.data?.product ?? [],
        sales: res.data?.sales ?? [],
        company: res.data?.company ?? [],
        onboarding: res.data?.onboarding ?? [],
        risks: res.data?.risks ?? [],
      }
      setMessages(prev => [...prev, { role: 'user', text: "Today's brief" }, { role: 'assistant', brief }])
    } catch (err) {
      const msg = err.response?.data?.detail ?? err.message ?? 'Brief request failed.'
      setMessages(prev => [...prev, { role: 'user', text: "Today's brief" }, { role: 'assistant', text: String(msg), citations: [] }])
    } finally {
      setBriefLoading(false)
    }
  }

  const handleAsk = async (q) => {
    const text = (typeof q === 'string' ? q : question).trim()
    if (!text) return
    setQuestion('')
    setMessages(prev => [...prev, { role: 'user', text }])
    setLoading(true)
    try {
      const res = await axios.post(
        API_URL ? `${API_URL}/api/ask` : '/api/ask',
        { question: text },
        { timeout: 50000 }
      )
      const answer = res.data?.answer ?? ''
      const citations = Array.isArray(res.data?.citations) ? res.data.citations : []
      const brief = res.data?.brief && typeof res.data.brief === 'object' ? res.data.brief : null
      setMessages(prev => [...prev, {
        role: 'assistant',
        text: brief ? '' : (answer || 'No answer was returned. Please try again.'),
        citations: brief ? [] : citations,
        brief: brief || undefined,
      }])
    } catch (err) {
      const isTimeout = err.code === 'ECONNABORTED' || err.message?.toLowerCase().includes('timeout')
      const serverMsg = err.response?.data?.detail ?? (Array.isArray(err.response?.data) ? err.response?.data[0]?.msg : null) ?? err.response?.data?.answer
      const message = isTimeout
        ? 'The request took too long. Please try again or ask a shorter question.'
        : (serverMsg && String(serverMsg).trim()) || 'Sorry, the service couldn\'t answer. Check that the API is running and GEMINI_API_KEY is set, then try again.'
      setMessages(prev => [...prev, {
        role: 'assistant',
        text: message,
        citations: [],
      }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="App">
      <header>
        <h1>OnboardAI</h1>
        <p>AI-powered onboarding — ask questions, get answers with citations</p>
        {health && (
          <div className="status-badge" data-ok={health.status === 'healthy'}>
            Backend: {health.status} · DB: {health.database}
          </div>
        )}
        {syncStatus && (
          <div className="sync-status">
            {syncStatus.last_sync_at && (
              <span>Last sync (Composio): {new Date(syncStatus.last_sync_at).toLocaleString()}</span>
            )}
            {syncStatus.next_sync_at && (
              <strong>Next sync: {new Date(syncStatus.next_sync_at).toLocaleString()}</strong>
            )}
            <button type="button" className="sync-trigger-btn" onClick={triggerSync} disabled={syncTriggering}>
              {syncTriggering ? 'Syncing…' : 'Trigger sync'}
            </button>
          </div>
        )}
      </header>

      <section className="chat">
        <div className="chat-messages">
          {messages.length === 0 && (
            <div className="chat-placeholder">
              <p>Ask anything about Velora: product, team, competitors, roadmap.</p>
              <button
                type="button"
                className="sample-q sample-q-brief"
                onClick={fetchDailyBrief}
                disabled={briefLoading}
              >
                {briefLoading ? 'Generating…' : "Today's brief"}
              </button>
              <div className="sample-questions">
                {sampleQuestions.slice(0, 6).map((q, i) => (
                  <button
                    key={i}
                    type="button"
                    className="sample-q"
                    onClick={() => handleAsk(q)}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`message message-${msg.role}`}>
              {msg.role === 'assistant' ? (
                <ChatBrief
                  answer={msg.text}
                  citations={msg.citations || []}
                  title={msg.brief ? "Today's Brief" : getBriefTitle(messages, i)}
                  sections={msg.brief || null}
                />
              ) : (
                <div className="message-text">{msg.text}</div>
              )}
            </div>
          ))}
          {(loading || briefLoading) && <div className="message message-assistant loading">Thinking…</div>}
        </div>
        <form
          className="chat-form"
          onSubmit={(e) => { e.preventDefault(); handleAsk(); }}
        >
          <input
            type="text"
            className="chat-input"
            placeholder="Ask a question about Velora…"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={loading}
          />
          <button type="submit" className="chat-submit" disabled={loading}>
            Ask
          </button>
        </form>
      </section>

      <section className="intel-feed">
        <h2>Competitive Intelligence</h2>
        <p className="intel-feed-sub">Live You.com web + news search and cached intel on Intercom, Zendesk, Gorgias. Set YOU_API_KEY for live search.</p>
        <form className="intel-live-search" onSubmit={runLiveSearch}>
          <input
            type="text"
            name="query"
            className="intel-live-input"
            placeholder="Search live: e.g. Intercom pricing, Zendesk AI…"
            value={liveSearchQuery}
            onChange={(e) => setLiveSearchQuery(e.target.value)}
            disabled={liveSearchLoading}
          />
          <button type="submit" className="intel-live-btn" disabled={liveSearchLoading}>
            {liveSearchLoading ? 'Searching…' : 'Search live'}
          </button>
        </form>
        {liveSearchResults && (
          <div className="intel-live-results">
            <h3 className="intel-live-heading">Live results for “{liveSearchResults.query}”</h3>
            {liveSearchResults.error && (
              <p className="intel-live-error">{liveSearchResults.error}</p>
            )}
            {!liveSearchResults.error && (
              <>
                {((liveSearchResults.web || []).length > 0 || (liveSearchResults.news || []).length > 0) ? (
                  <>
                    {(liveSearchResults.news || []).length > 0 && (
                      <div className="intel-live-block">
                        <h4>News</h4>
                        <ul className="intel-live-list">
                          {(liveSearchResults.news || []).map((item, i) => (
                            <li key={i} className="intel-live-item">
                              <span className="intel-live-title">{item.title}</span>
                              {item.source_name && <span className="intel-live-source">{item.source_name}</span>}
                              <p className="intel-live-content">{item.content}</p>
                              {item.url && (
                                <a href={item.url} target="_blank" rel="noopener noreferrer" className="intel-link">Read</a>
                              )}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {(liveSearchResults.web || []).length > 0 && (
                      <div className="intel-live-block">
                        <h4>Web</h4>
                        <ul className="intel-live-list">
                          {(liveSearchResults.web || []).map((item, i) => (
                            <li key={i} className="intel-live-item">
                              <span className="intel-live-title">{item.title}</span>
                              <p className="intel-live-content">{item.content}</p>
                              {item.url && (
                                <a href={item.url} target="_blank" rel="noopener noreferrer" className="intel-link">Source</a>
                              )}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </>
                ) : (
                  <p className="intel-empty">No live results. Try another query or check YOU_API_KEY.</p>
                )}
              </>
            )}
          </div>
        )}
        <div className="intel-cached-heading">
          <span>Cached feed</span>
          <button type="button" className="intel-refresh-btn" onClick={refreshIntel} disabled={intelRefreshing}>
            {intelRefreshing ? 'Refreshing…' : 'Refresh intel'}
          </button>
        </div>
        {intelFeed.length > 0 ? (
          <ul className="intel-list">
            {intelFeed.slice(0, 10).map((item) => (
              <li key={item.id} className="intel-item">
                <span className="intel-competitor">{item.competitor}</span>
                <span className="intel-type">{item.type}</span>
                <p className="intel-content">{item.content}</p>
                {item.timestamp && (
                  <span className="intel-time">{new Date(item.timestamp).toLocaleString()}</span>
                )}
                {item.source_url && (
                  <a href={item.source_url} target="_blank" rel="noopener noreferrer" className="intel-link">Source</a>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="intel-empty">No competitive intelligence data yet. Click Refresh to update (requires YOU_API_KEY).</p>
        )}
      </section>

      {renderUsage && (
        <section className="render-usage">
          <h2>Platform Usage</h2>
          <p className="render-usage-sub">Workspaces, services, and bandwidth</p>
          {!renderUsage.ok ? (
            <div className="render-usage-error">
              {renderUsage.error || 'Platform usage unavailable. Configure RENDER_API_KEY to enable.'}
            </div>
          ) : (
            <>
              {renderUsage.owners?.length > 0 && (
                <div className="render-usage-block">
                  <h3>Workspaces</h3>
                  <ul className="render-usage-list">
                    {renderUsage.owners.map((o) => (
                      <li key={o.id}><span className="render-usage-label">{o.name || o.id}</span></li>
                    ))}
                  </ul>
                </div>
              )}
              {renderUsage.services?.length > 0 && (
                <div className="render-usage-block">
                  <h3>Services</h3>
                  <ul className="render-usage-list">
                    {renderUsage.services.map((s) => (
                      <li key={s.id}>
                        <span className="render-usage-name">{s.name}</span>
                        <span className="render-usage-type">{s.type || '—'}</span>
                        {s.serviceDetails && (
                          <a href={s.serviceDetails} target="_blank" rel="noopener noreferrer" className="render-usage-link">Open</a>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {renderUsage.bandwidth?.length > 0 && (
                <div className="render-usage-block">
                  <h3>Bandwidth / metrics</h3>
                  <ul className="render-usage-list">
                    {renderUsage.bandwidth.map((b) => (
                      <li key={b.serviceId}>
                        <span className="render-usage-name">{b.serviceName}</span>
                        {b.error ? (
                          <span className="render-usage-muted">{b.error}</span>
                        ) : (
                          <span className="render-usage-muted">
                            {b.data ? `${Array.isArray(b.data) ? b.data.length : 0} data points` : '—'}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {renderUsage.ok && !renderUsage.owners?.length && !renderUsage.services?.length && (
                <p className="render-usage-muted">No workspaces or services returned.</p>
              )}
            </>
          )}
        </section>
      )}

      <footer className="app-footer">
        <span>Integrations</span>
        <a href="https://composio.dev" target="_blank" rel="noopener noreferrer">Composio</a>
        <span>·</span>
        <a href="https://you.com" target="_blank" rel="noopener noreferrer">You.com</a>
        <span>·</span>
        <a href="https://render.com" target="_blank" rel="noopener noreferrer">Render</a>
      </footer>
    </div>
  )
}

export default App
