import { useState, useMemo } from 'react'

/** Map citation source to domain tabs (for adaptable context) */
const SOURCE_TO_DOMAINS = {
  notion: ['Product', 'Company'],
  github: ['Engineering'],
  slack: ['Company', 'Onboarding'],
  you_com: ['Product', 'Sales'],
}

const DOMAIN_TABS = ['Overview', 'Product', 'Sales', 'Company', 'Onboarding', 'Engineering']

/** Detect if answer is a raw source dump (not a synthesized summary) */
function isAnswerDump(text) {
  if (!text || typeof text !== 'string') return false
  const t = text.trim()
  if (/^Based on the (available|following) sources?\s*:?\s*/i.test(t)) return true
  const bulletLines = t.split(/\n/).filter((l) => /^[•\-*]\s+\[[\w\s]+\]/.test(l.trim()))
  if (bulletLines.length >= 3) return true
  return false
}

/** Extract 3–5 short key points from a synthesized answer (not from a dump) */
function extractKeyPoints(text) {
  if (!text || typeof text !== 'string' || isAnswerDump(text)) return []
  const lines = text.split(/\n/).map((l) => l.trim()).filter(Boolean)
  const bullets = lines.filter(
    (l) => /^[•\-*]\s+/.test(l) && !/^[•\-*]\s+\[[\w\s]+\]/.test(l)
  )
  if (bullets.length > 0) {
    const points = bullets
      .map((b) => b.replace(/^[•\-*]\s+/, '').replace(/^\d+\.\s+/, '').trim())
      .filter((p) => p.length > 15 && p.length < 200)
    return points.slice(0, 5)
  }
  return []
}

/** Get domains that have at least one citation (for this response) */
function getRelevantDomains(citations) {
  const domains = new Set(['Overview'])
  for (const c of citations || []) {
    const source = (c.source || '').toLowerCase().replace(/\s+/g, '_')
    const mapped = SOURCE_TO_DOMAINS[source] || []
    mapped.forEach((d) => domains.add(d))
  }
  return DOMAIN_TABS.filter((tab) => domains.has(tab))
}

/** Get citations for a given domain tab */
function getCitationsForDomain(citations, domain) {
  if (!citations?.length) return []
  if (domain === 'Overview') return citations
  return citations.filter((c) => {
    const source = (c.source || '').toLowerCase().replace(/\s+/g, '_')
    const mapped = SOURCE_TO_DOMAINS[source] || []
    return mapped.includes(domain)
  })
}

/** Collapsible Sources block */
function SourcesBlock({ citations, defaultCollapsed = true }) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)
  const hasCitations = citations?.length > 0
  return (
    <div className="brief-sources-block">
      <button
        type="button"
        className="brief-sources-toggle"
        onClick={() => hasCitations && setCollapsed((c) => !c)}
        aria-expanded={hasCitations ? !collapsed : undefined}
      >
        <span className="brief-sources-label">Sources</span>
        <span className="brief-sources-count">({hasCitations ? citations.length : 0})</span>
        {hasCitations && (
          <span className="brief-sources-chevron" aria-hidden>{collapsed ? '▼' : '▲'}</span>
        )}
      </button>
      {hasCitations && !collapsed && (
        <ul className="brief-sources-list">
          {citations.map((c, j) => (
            <li key={j} className="brief-citation">
              <span className="brief-citation-source">{c.source}</span>
              <span className="brief-citation-title">{c.title}</span>
              {c.snippet && <span className="brief-citation-snippet">{c.snippet}</span>}
            </li>
          ))}
        </ul>
      )}
      {!hasCitations && <p className="brief-muted brief-sources-empty">No sources for this tab.</p>}
    </div>
  )
}

/** Section labels for structured daily brief (no sources) */
const BRIEF_SECTION_ORDER = [
  { key: 'summary', label: 'Summary' },
  { key: 'product', label: 'Product' },
  { key: 'sales', label: 'Sales' },
  { key: 'company', label: 'Company' },
  { key: 'onboarding', label: 'Onboarding' },
  { key: 'risks', label: 'Risks' },
]

/** Structured daily brief: only these sections, no sources */
function StructuredBrief({ sections, title, className }) {
  const bullets = (arr) => (Array.isArray(arr) ? arr : []).filter((x) => x && String(x).trim())
  const totalBullets = BRIEF_SECTION_ORDER.reduce((n, { key }) => n + bullets(sections[key]).length, 0)
  return (
    <div className={`brief brief-structured ${className}`}>
      <div className="brief-header">
        <h3 className="brief-title">📋 {title}</h3>
        <p className="brief-subtitle">
          {totalBullets > 0 ? `${totalBullets} takeaway${totalBullets !== 1 ? 's' : ''} for leadership` : "Today's product brief"}
        </p>
      </div>
      <div className="brief-panel brief-panel-structured">
        {BRIEF_SECTION_ORDER.map(({ key, label }) => {
          const items = bullets(sections[key])
          if (items.length === 0) return null
          return (
            <section key={key} className="brief-section">
              <h4 className="brief-section-title">{label}</h4>
              <ul className="brief-key-changes">
                {items.map((point, i) => (
                  <li key={i}>{point}</li>
                ))}
              </ul>
            </section>
          )
        })}
      </div>
    </div>
  )
}

/**
 * Adaptable brief UI: structured daily brief (sections) OR Q&A (answer + citations with tabs).
 */
export default function ChatBrief({ answer = '', citations = [], title = "Today's Brief", className = '', sections: sectionsProp = null }) {
  const sections = sectionsProp && typeof sectionsProp === 'object' ? sectionsProp : null
  if (sections) {
    return <StructuredBrief sections={sections} title={title} className={className} />
  }

  const [activeTab, setActiveTab] = useState('Overview')
  const keyPoints = useMemo(() => extractKeyPoints(answer), [answer])
  const relevantTabs = useMemo(() => getRelevantDomains(citations), [citations])
  const tabCitations = useMemo(
    () => getCitationsForDomain(citations, activeTab),
    [citations, activeTab]
  )

  const keyUpdatesCount = Math.max(1, keyPoints.length || citations?.length || 1)

  const isOverview = activeTab === 'Overview'
  const summary = isOverview ? answer : null
  const keyChanges = isOverview ? keyPoints : []
  const showKeyChanges = isOverview
  const showRisks = isOverview

  return (
    <div className={`brief ${className}`}>
      <div className="brief-header">
        <h3 className="brief-title">🧠 {title}</h3>
        <p className="brief-subtitle">{keyUpdatesCount} key update{keyUpdatesCount !== 1 ? 's' : ''} you should know</p>
      </div>

      <div className="brief-tabs" role="tablist">
        {relevantTabs.map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={activeTab === tab}
            className={`brief-tab ${activeTab === tab ? 'brief-tab-active' : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="brief-panel" role="tabpanel">
        {isOverview ? (
          <>
            <section className="brief-section">
              <h4 className="brief-section-title">Summary</h4>
              <div className="brief-summary">{summary || '—'}</div>
            </section>
            {showKeyChanges && (
              <section className="brief-section">
                <h4 className="brief-section-title">Key changes</h4>
                {keyChanges.length > 0 ? (
                  <ul className="brief-key-changes">
                    {keyChanges.map((point, i) => (
                      <li key={i}>{point}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="brief-muted">{isAnswerDump(answer) ? 'See sources below for details.' : 'See summary above.'}</p>
                )}
              </section>
            )}
            {showRisks && (
              <section className="brief-section">
                <h4 className="brief-section-title">Risks</h4>
                <p className="brief-risks">None identified.</p>
              </section>
            )}
            <section className="brief-section">
              <SourcesBlock citations={tabCitations} defaultCollapsed />
            </section>
          </>
        ) : (
          <>
            <section className="brief-section">
              <h4 className="brief-section-title">Summary</h4>
              <p className="brief-summary brief-summary-muted">
                Relevant context from {activeTab.toLowerCase()} sources.
              </p>
            </section>
            <section className="brief-section">
              <h4 className="brief-section-title">Key changes</h4>
              <p className="brief-muted">—</p>
            </section>
            <section className="brief-section">
              <h4 className="brief-section-title">Risks</h4>
              <p className="brief-muted">—</p>
            </section>
            <section className="brief-section">
              <SourcesBlock citations={tabCitations} defaultCollapsed />
            </section>
          </>
        )}
      </div>
    </div>
  )
}
