import { evidence } from '../data/index.js'

const MUTED = '#52605a'

function verdictColor(verdict) {
  switch (verdict) {
    case 'ACCEPTED':
      return { bg: '#f0fdf4', text: '#16a34a', border: '#bbf7d0' }
    case 'PROMISING':
      return { bg: '#fefce8', text: '#ca8a04', border: '#fef08a' }
    case 'REJECTED':
      return { bg: '#fef2f2', text: '#dc2626', border: '#fecaca' }
    default:
      return { bg: '#f4f5f2', text: MUTED, border: '#d1d3cf' }
  }
}

function OptimizationCard({ result }) {
  const vc = verdictColor(result.verdict)
  const aPct = 50
  const maxVal = Math.max(result.a_median_s, result.b_median_s) * 1.1
  const bPct = (result.b_median_s / maxVal) * 100
  const aBarPct = (result.a_median_s / maxVal) * 100

  return (
    <div className="p-5 rounded-lg mb-4" style={{ backgroundColor: '#ffffff', border: '1px solid #d1d3cf' }}>
      <div className="flex flex-col sm:flex-row sm:items-start gap-4">
        {/* Left: plan_id + verdict */}
        <div className="flex flex-col gap-2 min-w-[180px]">
          <span className="font-mono text-sm font-semibold" style={{ color: '#1d2421' }}>
            {result.plan_id}
          </span>
          <span
            className="inline-block px-3 py-1 text-xs font-semibold rounded-full w-fit"
            style={{ backgroundColor: vc.bg, color: vc.text, border: `1px solid ${vc.border}` }}
          >
            {result.verdict}
          </span>
        </div>

        {/* Right: A/B comparison bars */}
        <div className="flex-1 space-y-3">
          {/* A bar */}
          <div className="flex items-center gap-3">
            <span className="text-xs font-medium w-8" style={{ color: MUTED }}>A</span>
            <div className="flex-1 h-6 rounded" style={{ backgroundColor: '#f4f5f2', position: 'relative' }}>
              <div
                className="h-6 rounded"
                style={{
                  width: `${aBarPct}%`,
                  backgroundColor: '#94a3b8',
                }}
              />
            </div>
            <span className="text-xs font-mono w-14 text-right" style={{ color: '#1d2421' }}>
              {result.a_median_s.toFixed(2)} s
            </span>
          </div>
          {/* B bar */}
          <div className="flex items-center gap-3">
            <span className="text-xs font-medium w-8" style={{ color: MUTED }}>B</span>
            <div className="flex-1 h-6 rounded" style={{ backgroundColor: '#f4f5f2', position: 'relative' }}>
              <div
                className="h-6 rounded"
                style={{
                  width: `${bPct}%`,
                  backgroundColor: '#2a78d6',
                }}
              />
            </div>
            <span className="text-xs font-mono w-14 text-right" style={{ color: '#1d2421' }}>
              {result.b_median_s.toFixed(2)} s
            </span>
          </div>
          {/* Delta and CI */}
          <div className="flex flex-wrap items-center gap-4 text-xs">
            <span style={{ color: result.improvement_pct > 0 ? '#16a34a' : '#dc2626', fontWeight: 600 }}>
              {result.improvement_pct > 0 ? '▲' : '▼'} {Math.abs(result.improvement_pct).toFixed(1)}%
            </span>
            <span style={{ color: MUTED }}>
              CI [{result.ci_lower_s.toFixed(2)} s, {result.ci_upper_s.toFixed(2)} s]
            </span>
            {result.functional_passed !== undefined && (
              <span
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium"
                style={{
                  backgroundColor: result.functional_passed ? '#f0fdf4' : '#fef2f2',
                  color: result.functional_passed ? '#16a34a' : '#dc2626',
                }}
              >
                {result.functional_passed ? '✓' : '✗'} functional
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function Optimization() {
  const cal = evidence.calibration

  return (
    <div>
      {/* ABBA Validation Results */}
      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-4" style={{ color: '#1d2421' }}>
          ABBA Validation Results
        </h2>
        {evidence.abbaResults.map((result) => (
          <OptimizationCard key={result.plan_id} result={result} />
        ))}
      </section>

      {/* Calibration Overhead */}
      <section>
        <h2 className="text-lg font-semibold mb-4" style={{ color: '#1d2421' }}>
          Calibration Overhead
        </h2>
        <div className="p-5 rounded-lg" style={{ backgroundColor: '#ffffff', border: '1px solid #d1d3cf' }}>
          <div className="flex flex-wrap items-center gap-6">
            {/* Passed/Failed badge */}
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium" style={{ color: MUTED }}>Status</span>
              <span
                className="inline-block px-3 py-1 text-xs font-semibold rounded-full"
                style={{
                  backgroundColor: cal.passed ? '#f0fdf4' : '#fef2f2',
                  color: cal.passed ? '#16a34a' : '#dc2626',
                  border: `1px solid ${cal.passed ? '#bbf7d0' : '#fecaca'}`,
                }}
              >
                {cal.passed ? 'PASSED' : 'FAILED'}
              </span>
            </div>

            {/* OS Total Delta */}
            <div className="text-center">
              <div className="text-2xl font-bold" style={{ color: cal.os_total_delta_percent < 0 ? '#16a34a' : '#dc2626' }}>
                {cal.os_total_delta_percent.toFixed(1)}%
              </div>
              <div className="text-xs" style={{ color: MUTED }}>OS Total Delta</div>
            </div>

            {/* Graphical Delta */}
            <div className="text-center">
              <div className="text-2xl font-bold" style={{ color: cal.graphical_delta_percent < 0 ? '#16a34a' : '#dc2626' }}>
                {cal.graphical_delta_percent.toFixed(1)}%
              </div>
              <div className="text-xs" style={{ color: MUTED }}>Graphical Delta</div>
            </div>

            {/* Bare vs Benchmark summary */}
            <div className="flex-1 min-w-[200px]">
              <div className="flex items-center gap-2 text-xs" style={{ color: MUTED }}>
                <span>Bare: {cal.bare.runs} runs, median OS total {(cal.bare.os_total_median_ns / 1e9).toFixed(2)} s</span>
              </div>
              <div className="flex items-center gap-2 text-xs mt-1" style={{ color: MUTED }}>
                <span>Benchmark: {cal.benchmark.runs} runs, median OS total {(cal.benchmark.os_total_median_ns / 1e9).toFixed(2)} s</span>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}

export default Optimization
