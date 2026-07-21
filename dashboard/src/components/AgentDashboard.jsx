import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import { evidence } from '../data/index.js'

const MUTED = '#52605a'
const ACCENT = '#2a78d6'
const CRITICAL = '#dc2626'
const NON_CRITICAL = '#94a3b8'

function toSeconds(ns) {
  return +(ns / 1e9).toFixed(2)
}

function AgentDashboard() {
  // --- Top 5 bottlenecks sorted by blame_ns ---
  const topBottlenecks = [...evidence.bottlenecks]
    .sort((a, b) => b.blame_ns - a.blame_ns)
    .slice(0, 5)
    .map((b) => ({
      ...b,
      blame_s: toSeconds(b.blame_ns),
    }))

  return (
    <div>
      {/* Agent Skill Pipeline */}
      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-4" style={{ color: '#1d2421' }}>
          Agent Skill Pipeline
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {evidence.agentSkills.map((skill) => (
            <div
              key={skill.name}
              className="p-5 rounded-lg"
              style={{ backgroundColor: '#ffffff', border: '1px solid #d1d3cf' }}
            >
              <h3 className="font-semibold text-sm mb-2" style={{ color: '#1d2421' }}>
                {skill.name}
              </h3>
              <p className="text-xs leading-relaxed" style={{ color: MUTED }}>
                {skill.description}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* BootAgent Performance */}
      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-4" style={{ color: '#1d2421' }}>
          BootAgent Performance
        </h2>
        <div className="p-4 rounded-lg" style={{ backgroundColor: '#ffffff', border: '1px solid #d1d3cf' }}>
          <div className="flex flex-wrap gap-3">
            {evidence.benchmarkCases.map((bc) => (
              <div
                key={bc.id}
                className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm"
                style={{
                  backgroundColor: bc.status === 'pass' ? '#f0fdf4' : '#fef2f2',
                  border: `1px solid ${bc.status === 'pass' ? '#bbf7d0' : '#fecaca'}`,
                }}
              >
                <span
                  className="font-bold text-base"
                  style={{ color: bc.status === 'pass' ? '#16a34a' : '#dc2626' }}
                >
                  {bc.status === 'pass' ? '✓' : '✗'}
                </span>
                <span className="font-mono text-xs" style={{ color: MUTED }}>{bc.id}</span>
                <span style={{ color: '#1d2421' }}>{bc.name}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Top Bottlenecks */}
      <section>
        <h2 className="text-lg font-semibold mb-4" style={{ color: '#1d2421' }}>
          Top Bottlenecks
        </h2>
        <div className="p-4 rounded-lg" style={{ backgroundColor: '#ffffff', border: '1px solid #d1d3cf' }}>
          <ResponsiveContainer width="100%" height={320}>
            <BarChart
              data={topBottlenecks}
              layout="vertical"
              margin={{ top: 5, right: 30, left: 200, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
              <XAxis type="number" unit=" s" tick={{ fill: MUTED, fontSize: 12 }} />
              <YAxis
                type="category"
                dataKey="node"
                tick={{ fill: MUTED, fontSize: 11, fontFamily: 'monospace' }}
                width={190}
              />
              <Tooltip
                formatter={(value) => [`${value} s`]}
                contentStyle={{ backgroundColor: '#fff', border: '1px solid #d1d3cf', borderRadius: 6 }}
              />
              <Bar dataKey="blame_s" barSize={24} radius={[0, 4, 4, 0]}>
                {topBottlenecks.map((entry, index) => (
                  <Cell
                    key={entry.node}
                    fill={entry.on_critical_path ? CRITICAL : NON_CRITICAL}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>
    </div>
  )
}

export default AgentDashboard
