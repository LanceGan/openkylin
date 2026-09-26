import { evidence } from '../data/index.js'

export default function CrossDistro() {
  const { crossDistro } = evidence

  return (
    <div>
      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3" style={{ color: '#1d2421' }}>
          跨发行版启动基线对比（各发行版 n=4，标准差均为 0）
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse" style={{ borderColor: '#d1d3cf' }}>
            <thead>
              <tr style={{ backgroundColor: '#1F4E79', color: 'white' }}>
                <th className="px-3 py-2 text-left" style={{ border: '1px solid #d1d3cf' }}>发行版</th>
                <th className="px-3 py-2 text-right" style={{ border: '1px solid #d1d3cf' }}>总启动时间</th>
                <th className="px-3 py-2 text-right" style={{ border: '1px solid #d1d3cf' }}>内核</th>
                <th className="px-3 py-2 text-right" style={{ border: '1px solid #d1d3cf' }}>用户空间</th>
                <th className="px-3 py-2 text-left" style={{ border: '1px solid #d1d3cf' }}>最大瓶颈</th>
                <th className="px-3 py-2 text-center" style={{ border: '1px solid #d1d3cf' }}>显示管理器</th>
                <th className="px-3 py-2 text-center" style={{ border: '1px solid #d1d3cf' }}>因果图规模</th>
              </tr>
            </thead>
            <tbody>
              {crossDistro && [
                { ...crossDistro.openKylin, name: 'openKylin 2.0 SP2' },
                { ...crossDistro.ubuntu, name: 'Ubuntu 22.04 LTS' },
                { ...crossDistro.fedora, name: 'Fedora 41' },
              ].map((d, i) => (
                <tr key={d.name} style={{ backgroundColor: i % 2 === 0 ? '#fafafa' : '#f2f7fb' }}>
                  <td className="px-3 py-2 font-medium" style={{ border: '1px solid #d1d3cf' }}>{d.name}</td>
                  <td className="px-3 py-2 text-right font-bold" style={{ border: '1px solid #d1d3cf', color: '#1F4E79' }}>
                    {(d.os_total_s || 0).toFixed(1)}s
                  </td>
                  <td className="px-3 py-2 text-right" style={{ border: '1px solid #d1d3cf' }}>{(d.kernel_s || 0).toFixed(3)}s</td>
                  <td className="px-3 py-2 text-right" style={{ border: '1px solid #d1d3cf' }}>{(d.userspace_s || 0).toFixed(3)}s</td>
                  <td className="px-3 py-2 text-left text-xs" style={{ border: '1px solid #d1d3cf' }}>{d.max_bottleneck || '-'}</td>
                  <td className="px-3 py-2 text-center" style={{ border: '1px solid #d1d3cf' }}>{d.dm || '-'}</td>
                  <td className="px-3 py-2 text-center" style={{ border: '1px solid #d1d3cf' }}>{d.nodes || '?'} 节点/{d.edges || '?'} 边</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-8">
        <h2 className="text-lg font-bold mb-3" style={{ color: '#1d2421' }}>
          跨发行版关键发现
        </h2>
        <div className="space-y-3 text-sm" style={{ color: '#52605a' }}>
          <p>• <strong>Fedora 41 启动最快（9.7s）</strong>，得益于 dracut 精简 initramfs 和 systemd v256 的启动优化，仅为 openKylin 的 34%、Ubuntu 的 23%。</p>
          <p>• <strong>openKylin 瓶颈集中在发行版特有服务</strong>——kaiming.service（20.2s，关键路径上）和 kysdk-conf2.service（0.5s）均为 openKylin 独有，凸显了为本发行版定制优化工具的必要性。</p>
          <p>• <strong>Ubuntu 用户空间耗时最高（39.9s）</strong>，主要受 plymouth-quit-wait.service（19.8s）影响，为 VM 环境下的已知放大效应。</p>
          <p>• <strong>三发行版使用完全相同的 Python/Rust 代码</strong>，通过 adapters/ 模块和 observer DM 可配置（dm= 跨语言字段）实现零代码修改运行。</p>
        </div>
      </section>
    </div>
  )
}
