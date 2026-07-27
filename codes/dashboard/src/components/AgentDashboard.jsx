import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { evidence } from '../data/index.js'

const MUTED = '#52605a'
const CRITICAL = '#dc2626'
const NON_CRITICAL = '#94a3b8'

function toSeconds(ns) { return +(ns / 1e9).toFixed(2) }

function AgentDashboard() {
  const topBottlenecks = [...evidence.bottlenecks]
    .sort((a, b) => b.blame_ns - a.blame_ns).slice(0, 7)
    .map((b) => ({ ...b, blame_s: toSeconds(b.blame_ns) }))

  return (
    <div>
      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-4" style={{ color: '#1d2421' }}>BootAgent 四角色技能流水线</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {(evidence.agentSkills || []).map((skill) => (
            <div key={skill.name} className="p-5 rounded-lg" style={{ backgroundColor: '#ffffff', border: '1px solid #d1d3cf' }}>
              <h3 className="font-semibold text-sm mb-2" style={{ color: '#1F4E79' }}>{skill.name}</h3>
              <p className="text-xs leading-relaxed" style={{ color: MUTED }}>{skill.description}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-4" style={{ color: '#1d2421' }}>BootAgent 基准测试 (Benchmark B1-B5)</h2>
        <div className="p-4 rounded-lg" style={{ backgroundColor: '#ffffff', border: '1px solid #d1d3cf' }}>
          <div className="flex flex-wrap gap-3">
            {(evidence.benchmarkCases || []).map((bc) => (
              <div key={bc.id} className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm"
                style={{ backgroundColor: bc.status === 'pass' ? '#f0fdf4' : '#fef2f2', border: `1px solid ${bc.status === 'pass' ? '#bbf7d0' : '#fecaca'}` }}>
                <span className="font-bold text-base" style={{ color: bc.status === 'pass' ? '#16a34a' : '#dc2626' }}>
                  {bc.status === 'pass' ? '✓' : '✗'}
                </span>
                <span className="text-xs" style={{ color: MUTED }}>{bc.id}</span>
                <span style={{ color: '#1d2421' }}>{bc.name}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section>
        <h2 className="text-lg font-semibold mb-4" style={{ color: '#1d2421' }}>瓶颈服务排名（按 blame 排序）</h2>
        <div className="p-4 rounded-lg" style={{ backgroundColor: '#ffffff', border: '1px solid #d1d3cf' }}>
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={topBottlenecks} layout="vertical" margin={{ top: 5, right: 30, left: 220, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
              <XAxis type="number" unit=" s" tick={{ fill: MUTED, fontSize: 12 }} />
              <YAxis type="category" dataKey="node" tick={{ fill: MUTED, fontSize: 11 }} width={210} />
              <Tooltip formatter={(value) => [`${value}s`]} />
              <Bar dataKey="blame_s" barSize={24} radius={[0, 4, 4, 0]} name="耗时">
                {topBottlenecks.map((entry) => (
                  <Cell key={entry.node} fill={entry.on_critical_path ? CRITICAL : NON_CRITICAL} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div className="flex gap-6 mt-3 text-xs" style={{ color: MUTED }}>
            <span><span className="inline-block w-3 h-3 rounded mr-1" style={{ backgroundColor: CRITICAL }} /> 在关键路径上</span>
            <span><span className="inline-block w-3 h-3 rounded mr-1" style={{ backgroundColor: NON_CRITICAL }} /> 不在关键路径上</span>
          </div>
        </div>
      </section>
    </div>
  )
}

export default AgentDashboard
