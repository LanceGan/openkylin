import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  LabelList,
} from 'recharts'
import { evidence } from '../data/index.js'

const MUTED = '#52605a'
const ACCENT = '#2a78d6'
const KERNEL = '#4a90d9'
const INITRD = '#f0a060'
const USERSPACE = '#60b070'

function toSeconds(ns) {
  return +(ns / 1e9).toFixed(2)
}

function BootTimeline() {
  // --- Boot Phase Breakdown ---
  const bareGraphics = evidence.calibration.bare.graphical_median_ns
  const benchGraphics = evidence.calibration.benchmark.graphical_median_ns

  const bootPhaseData = [
    {
      name: 'Bare',
      Kernel: 2.5,
      Initrd: 3.5,
      Userspace: +(toSeconds(bareGraphics) - 6.0).toFixed(1),
    },
    {
      name: 'Benchmark',
      Kernel: 2.0,
      Initrd: 2.8,
      Userspace: +(toSeconds(benchGraphics) - 4.8).toFixed(1),
    },
  ]

  // --- Readiness Events ---
  const keyKinds = ['greeter_ready', 'session_opened', 'usable']
  const readinessData = evidence.readinessEvents
    .filter((e) => keyKinds.includes(e.kind))
    .map((e) => ({
      kind: e.kind,
      seconds: toSeconds(e.monotonic_ns),
    }))

  // --- Top 5 bottlenecks ---
  const topBottlenecks = [...evidence.bottlenecks]
    .sort((a, b) => b.blame_ns - a.blame_ns)
    .slice(0, 5)

  return (
    <div>
      {/* Boot Phase Breakdown */}
      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-4" style={{ color: '#1d2421' }}>
          Boot Phase Breakdown
        </h2>
        <div className="p-4 rounded-lg" style={{ backgroundColor: '#ffffff', border: '1px solid #d1d3cf' }}>
          <ResponsiveContainer width="100%" height={320}>
            <BarChart
              data={bootPhaseData}
              layout="vertical"
              margin={{ top: 5, right: 30, left: 60, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
              <XAxis type="number" unit=" s" tick={{ fill: MUTED, fontSize: 12 }} />
              <YAxis type="category" dataKey="name" tick={{ fill: MUTED, fontSize: 13 }} width={80} />
              <Tooltip
                formatter={(value) => [`${value} s`]}
                contentStyle={{ backgroundColor: '#fff', border: '1px solid #d1d3cf', borderRadius: 6 }}
              />
              <Legend wrapperStyle={{ fontSize: 12, color: MUTED }} />
              <Bar dataKey="Kernel" stackId="a" fill={KERNEL} barSize={32} radius={[0, 0, 0, 0]} />
              <Bar dataKey="Initrd" stackId="a" fill={INITRD} barSize={32} />
              <Bar dataKey="Userspace" stackId="a" fill={USERSPACE} barSize={32} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* User-Perceived Readiness Timeline */}
      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-4" style={{ color: '#1d2421' }}>
          User-Perceived Readiness Timeline
        </h2>
        <div className="p-4 rounded-lg" style={{ backgroundColor: '#ffffff', border: '1px solid #d1d3cf' }}>
          <ResponsiveContainer width="100%" height={180}>
            <ScatterChart margin={{ top: 25, right: 30, left: 30, bottom: 5 }}>
              <XAxis
                type="number"
                dataKey="seconds"
                name="Time"
                unit=" s"
                domain={[0, 'auto']}
                tick={{ fill: MUTED, fontSize: 12 }}
              />
              <YAxis type="number" dataKey="y" hide domain={[0, 1]} />
              <Tooltip
                formatter={(value, name) => [name === 'seconds' ? `${value} s` : value]}
                contentStyle={{ backgroundColor: '#fff', border: '1px solid #d1d3cf', borderRadius: 6 }}
              />
              <Scatter
                data={readinessData.map((e) => ({ ...e, y: 0 }))}
                fill={ACCENT}
                shape="circle"
              >
                <LabelList
                  dataKey="kind"
                  position="top"
                  style={{ fill: MUTED, fontSize: 11, fontWeight: 500 }}
                  offset={10}
                />
              </Scatter>
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* Longest Units */}
      <section>
        <h2 className="text-lg font-semibold mb-4" style={{ color: '#1d2421' }}>
          Longest Units
        </h2>
        <div className="rounded-lg overflow-hidden" style={{ border: '1px solid #d1d3cf' }}>
          <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ backgroundColor: '#f4f5f2' }}>
                <th className="text-left px-4 py-3 font-medium" style={{ color: MUTED }}>Service Unit</th>
                <th className="text-right px-4 py-3 font-medium" style={{ color: MUTED }}>Blame</th>
                <th className="text-right px-4 py-3 font-medium" style={{ color: MUTED }}>Slack</th>
                <th className="text-center px-4 py-3 font-medium" style={{ color: MUTED }}>Critical Path</th>
              </tr>
            </thead>
            <tbody>
              {topBottlenecks.map((b) => (
                <tr key={b.node} className="border-t" style={{ borderColor: '#d1d3cf' }}>
                  <td className="px-4 py-3 font-mono text-xs" style={{ color: '#1d2421' }}>{b.node}</td>
                  <td className="px-4 py-3 text-right font-mono" style={{ color: '#1d2421' }}>
                    {toSeconds(b.blame_ns).toFixed(2)} s
                  </td>
                  <td className="px-4 py-3 text-right font-mono" style={{ color: MUTED }}>
                    {b.slack_ns > 0 ? `${toSeconds(b.slack_ns).toFixed(2)} s` : '—'}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {b.on_critical_path ? (
                      <span className="inline-block px-2 py-0.5 text-xs rounded font-medium" style={{ backgroundColor: '#fef2f2', color: '#dc2626' }}>
                        Yes
                      </span>
                    ) : (
                      <span className="inline-block px-2 py-0.5 text-xs rounded" style={{ backgroundColor: '#f0fdf4', color: '#16a34a' }}>
                        No
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

export default BootTimeline
