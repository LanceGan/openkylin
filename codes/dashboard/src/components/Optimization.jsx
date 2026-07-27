import { evidence } from '../data/index.js'

const MUTED = '#52605a'

function verdictColor(verdict) {
  switch (verdict) {
    case 'ACCEPTED':
      return { bg: '#f0fdf4', text: '#16a34a', border: '#bbf7d0', label: '通过' }
    case 'PROMISING':
      return { bg: '#fefce8', text: '#ca8a04', border: '#fef08a', label: '有希望' }
    case 'REJECTED':
      return { bg: '#fef2f2', text: '#dc2626', border: '#fecaca', label: '未通过' }
    default:
      return { bg: '#f4f5f2', text: MUTED, border: '#d1d3cf', label: '未知' }
  }
}

// Normalize ABBA result to flat fields used by the card
function flat(r) {
  const s = r.statistics || {}
  const a = s.a_median_ns ? s.a_median_ns / 1e9 : 0
  const b = s.b_median_ns ? s.b_median_ns / 1e9 : 0
  const impPct = s.median_improvement_pct != null ? s.median_improvement_pct : 0
  const ciLo = s.ci_lower_95_ns != null ? s.ci_lower_95_ns / 1e9 : 0
  const ciHi = s.ci_upper_95_ns != null ? s.ci_upper_95_ns / 1e9 : 0
  return { ...r, a_median_s: a, b_median_s: b, improvement_pct: impPct, ci_lower_s: ciLo, ci_upper_s: ciHi }
}

function OptimizationCard({ result }) {
  const r = flat(result)
  const vc = verdictColor(r.verdict)
  const maxVal = Math.max(r.a_median_s, r.b_median_s, 1) * 1.1
  const aBarPct = (r.a_median_s / maxVal) * 100
  const bBarPct = (r.b_median_s / maxVal) * 100

  return (
    <div className="p-5 rounded-lg mb-4" style={{ backgroundColor: '#ffffff', border: '1px solid #d1d3cf' }}>
      <div className="flex flex-col sm:flex-row sm:items-start gap-4">
        <div className="flex flex-col gap-2 min-w-[220px]">
          <span className="text-sm font-semibold" style={{ color: '#1d2421' }}>
            {r.plan_id || r.distribution || ''}
          </span>
          {r.distribution && (
            <span className="text-xs" style={{ color: MUTED }}>{r.distribution}</span>
          )}
          {r.phase && (
            <span className="text-xs px-2 py-0.5 rounded inline-block w-fit" style={{ backgroundColor: '#f0f0f0', color: MUTED }}>
              {r.phase}
            </span>
          )}
          <span
            className="inline-block px-3 py-1 text-xs font-semibold rounded-full w-fit"
            style={{ backgroundColor: vc.bg, color: vc.text, border: `1px solid ${vc.border}` }}
          >
            {vc.label}
          </span>
        </div>

        <div className="flex-1 space-y-3">
          <div className="flex items-center gap-3">
            <span className="text-xs font-medium w-8" style={{ color: MUTED }}>A</span>
            <div className="flex-1 h-6 rounded" style={{ backgroundColor: '#f4f5f2', position: 'relative' }}>
              <div className="h-6 rounded" style={{ width: `${Math.max(aBarPct, 0.5)}%`, backgroundColor: '#94a3b8' }} />
            </div>
            <span className="text-xs w-16 text-right" style={{ color: '#1d2421' }}>
              {r.a_median_s.toFixed(2)}s
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs font-medium w-8" style={{ color: MUTED }}>B</span>
            <div className="flex-1 h-6 rounded" style={{ backgroundColor: '#f4f5f2', position: 'relative' }}>
              <div className="h-6 rounded" style={{ width: `${Math.max(bBarPct, 0.5)}%`, backgroundColor: '#2a78d6' }} />
            </div>
            <span className="text-xs w-16 text-right" style={{ color: '#1d2421' }}>
              {r.b_median_s.toFixed(2)}s
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-4 text-xs">
            <span style={{ color: r.improvement_pct > 0 ? '#16a34a' : '#dc2626', fontWeight: 600 }}>
              {r.improvement_pct > 0 ? '▲' : '▼'} {Math.abs(r.improvement_pct).toFixed(1)}%
            </span>
            <span style={{ color: MUTED }}>
              95%CI [{r.ci_lower_s.toFixed(3)}s, {r.ci_upper_s.toFixed(3)}s]
            </span>
            {r.verdict === 'REJECTED' && Math.abs(r.improvement_pct) < 2 && (
              <span className="text-xs px-2 py-0.5 rounded bg-red-50 text-red-600">改善幅度不足</span>
            )}
            {r.verdict === 'PROMISING' && (
              <span className="text-xs px-2 py-0.5 rounded bg-yellow-50 text-yellow-600">需更大样本量</span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function Optimization() {
  return (
    <div>
      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-4" style={{ color: '#1d2421' }}>
          ABBA 优化验证结果
        </h2>
        {(evidence.abbaResults || []).map((r, i) => (
          <OptimizationCard key={r.plan_id + (r.distribution || '') + i} result={r} />
        ))}
      </section>
    </div>
  )
}

export default Optimization
