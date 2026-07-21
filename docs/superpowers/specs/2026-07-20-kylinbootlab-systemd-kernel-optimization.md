# KylinBootLab Phase 6 设计方案：Systemd 与内核优化

- 日期：2026-07-20
- 状态：已批准（对话中逐节确认）
- 对应赛题：开放原子开源大赛 openKylin 赛题第四题
- 前置阶段：Phase 1-5 均已完成并通过实机验收

## 1. 目标与范围

Phase 6 将 Phase 4 瓶颈分析和 Phase 5 ABBA 验证框架应用于系统级优化——在 systemd 依赖重排、内核启动参数和 initramfs 驱动裁剪三个层面上，选择五个高价值候选，独立 ABBA 验证后输出 `ACCEPTED`/`REJECTED` 判决和可竞赛展示的收益数据。

完成门槛：至少 3 个候选通过完整 ABBA（18 boots/candidate），其中至少 1 个达到 `ACCEPTED`。

### 范围裁剪

- **不做 UKUI 源码补丁**——Phase 7 前置需要 openKylin 编译环境，本阶段只做配置级优化
- **不做内核源码编译**——`mitigations=off` 通过 GRUB 启动参数已足够
- **不做跨发行版 initramfs 工具适配**——openKylin 用 `initramfs-tools`，mkinitcpio/dracut 留到 Phase 10

## 2. 关键决策（已确认）

| # | 决策 | 选项 |
|---|------|------|
| 1 | 优化层 | **systemd + 内核优先**，UKUI 源码延后 |
| 2 | 覆盖策略 | **广泛覆盖**：5 个独立候选，逐个 ABBA 验证 |
| 3 | 执行方式 | SSH systemd drop-in / grub config / initramfs-tools 配置 |
| 4 | 安全回滚 | Phase 2 baseline snapshot 兜底 |
| 5 | 验证框架 | Phase 5 ABBA 原封复用（Zero new ABBA code） |

## 3. 五候选总览

```
systemd 层                         内核层                      initramfs 层
─────────                          ─────                      ──────────
1. mask-strongswan                 4. mitigations=off         5. trim-unused-modules
   (mask IPSec)                       (grub cmdline)             (mkinitramfs config)
   
2. kaiming-stagger
   (After=graphical.target →
    After=multi-user.target)

3. parallel-kysdk
   (移除串行 After= 约束)
```

## 4. 候选详细设计

### 4.1 mask-strongswan

| 项 | 值 |
|------|-----|
| category | `service_mask` |
| 改动 | `systemctl mask strongswan-starter.service` |
| 预期收益 | ~450ms（Phase 4 关键路径上） |
| 风险 | 极低——strongswan 是 IPSec 守护进程，VM 无此网络需求 |
| 功能回归 | `systemctl is-active NetworkManager dbus lightdm`（三项均 active） |
| 回滚 | `systemctl unmask strongswan-starter.service` |

### 4.2 kaiming-stagger

**问题**：`org.kylin.kaiming.service` 当前 `After=graphical.target` + `WantedBy=graphical.target`——它等到了图形目标才启动，耗时 1.4s。但实际它是 dbus 激活服务，不需要等待图形桌面。

**改动**：drop-in 将 `After=` 清空后更改为 `After=multi-user.target`：

```ini
# /etc/systemd/system/org.kylin.kaiming.service.d/kbl-phase6.conf
[Unit]
After=
After=multi-user.target
```

| 项 | 值 |
|------|-----|
| category | `parallelize` |
| 预期收益 | ~1.4s（从 `graphical.target` 关键路径移除） |
| 风险 | 低——kaiming 由 dbus 按需激活，提前到 multi-user.target 阶段只优化了启动时 dbus 激活竞态 |
| 功能回归 | `systemctl is-active org.kylin.kaiming`、`busctl call org.kylin.kaiming /org/kylin/kaiming org.freedesktop.DBus.Introspectable Introspect` |
| 回滚 | `rm /etc/systemd/system/org.kylin.kaiming.service.d/kbl-phase6.conf && systemctl daemon-reload` |

### 4.3 parallel-kysdk

**问题**：多个 kysdk 守护进程（`kysdk-conf2.service`、`kysdk-dbus.service`、`kysdk-timer.service` 等）互有串行 `After=` 约束，累计 ~500ms。

**改动**：为每个 kysdk 服务加 drop-in，宽松 `After=` 为仅依赖 `dbus.service` + `basic.target`，同时加 `Wants=` 依赖保证 dbus 先启动：

```ini
# 示例：/etc/systemd/system/kysdk-conf2.service.d/kbl-phase6.conf
[Unit]
After=dbus.service basic.target
Wants=dbus.service
```

**批量部署**：phase6 安装脚本遍历已知 kysdk 单元列表，为每个加相同 drop-in。

| 项 | 值 |
|------|-----|
| category | `parallelize` |
| 预期收益 | ~200-500ms |
| 风险 | 低-中——需验证所有 kysdk dbus 服务名仍可正确获取 |
| 功能回归 | `busctl list | grep -i kysdk` 返回非空、`systemctl is-active kysdk-*` 全部 active |
| 回滚 | 批量 `rm` 所有 drop-in + `daemon-reload` |

### 4.4 kernel-mitigations-off

**问题**：Spectre/Meltdown 等 CPU 漏洞缓解机制在 VM 竞赛环境中无安全意义，但增加内核启动开销。

**改动**：往 `/etc/default/grub.d/kbl-phase6.cfg` 写入：

```bash
GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT mitigations=off"
```

然后执行 `update-grub` → 重启。

| 项 | 值 |
|------|-----|
| category | `kernel_param` |
| 预期收益 | ~200-500ms |
| 风险 | 低——VM 环境无需漏洞防护 |
| 功能回归 | `systemctl is-system-running` = running |
| 回滚 | `rm /etc/default/grub.d/kbl-phase6.cfg && update-grub` |
| ⚠️ 特殊 | `update-grub` 只在 ABBA block 边界执行一次（A→B 切换时） |

### 4.5 initramfs-trim

**问题**：当前 initramfs 包含大量 VM 不需要的内核模块（蓝牙、声音、摄像头、文件系统驱动等），增加解压和加载时间。

**改动**：往 `/etc/initramfs-tools/conf.d/kbl-phase6` 写入：

```
MODULES=dep
```

`MODULES=dep` 告诉 `mkinitramfs` 只包含当前运行内核所需的最小模块闭包（追溯 `/sys/` 中已加载模块的依赖链），而非默认的 `MODULES=most`（拷贝大多数可用模块）。

然后执行 `update-initramfs -u -k all` → 重启。

| 项 | 值 |
|------|-----|
| category | `initramfs_trim` |
| 预期收益 | ~300-800ms（initramfs 镜像变小 + 解压更快 + 更少模块加载） |
| 风险 | **中**——如果 `/sys` 状态不完整（如 raid/加密/网络启动的模块可能未加载），`MODULES=dep` 可能遗漏关键模块。Phase 2 snapshot 兜底 |
| 验证 | 重启后 `dmesg` 无 "failed to load module" 错误 |
| 回滚 | `rm /etc/initramfs-tools/conf.d/kbl-phase6 && update-initramfs -u -k all` |
| ⚠️ 特殊 | `update-initramfs -u` 约需 30-60s，仅在 profile 切换时执行一次 |

## 5. 安全边界

### grub + initramfs 三项防护

| 防护层 | 说明 |
|------|------|
| Phase 2 baseline snapshot | 每候选 ABBA 前已存在干净快照。profile 切换只改当前配置：写文件 + `update-grub`/`update-initramfs` |
| 单候选隔离 | ABBA 跑完立即回滚（`rm` + 重建），不累积 |
| 改坏恢复 | 如果 `update-grub` 或 `update-initramfs` 后 VM 无法启动 → vmrun revertToSnapshot baseline → 恢复，候选标记 `REJECTED` |

### grub 切换细节

ABBA block 边界（A→B 或 B→A）的 profile 切换流程：

1. VM 已在线（前一个 block 的最后一个 boot 刚完成）
2. 如果需要切换到 B：写 `/etc/default/grub.d/kbl-phase6.cfg` → `update-grub` → `poweroff`
3. 如果需要切换到 A：删文件 → `update-grub` → `poweroff`
4. 下一次 `poweron` 时新参数生效

由于每次 profile 切换都有 `poweroff`→`poweron` 循环，grub 和 initramfs 的"每次重启生效"特性与 ABBA 的自然边界完全对齐——**不增加额外重启**。

### initramfs 特殊防护

- 执行 `update-initramfs -u` 前先备份当前 initramfs 镜像（`cp /boot/initrd.img-$(uname -r) /boot/initrd.img-$(uname -r).kbl-backup`）
- `MODULES=dep` 不修改内核命令行或 grub——只是 initramfs 内容变了
- Phase 2 snapshot 是终极保障

## 6. 与 Phase 5 的复用

Phase 6 不新增任何 ABBA 或统计代码。全部复用 Phase 5：

| Phase 5 组件 | Phase 6 复用方式 |
|-------------|-----------------|
| `OptimizationPlan` | 新增 5 个 factory 函数 + `category` 增加 `kernel_param`/`initramfs_trim` |
| `ProfileExecutor` | 新增 `kernel_param`（grub）和 `initramfs_trim`（mkinitramfs）分支 |
| `ABBAScheduler` | 原封不动（4 blocks × 4 boots） |
| `compute_statistics` + `verdict` | 原封不动 |
| `abba_direct.py` | 参数化候选名称 |

**Phase 6 约 80% 的代码是配置文件内容，20% 是 executor 分支扩展。**

## 7. 错误处理

| 场景 | 处理 |
|------|------|
| `update-grub` 失败 | 立即标记候选 `REJECTED`（无法可靠切换 profile） |
| `update-initramfs -u` 失败 | 回滚到备份 initramfs → 标记候选 `REJECTED` |
| grub/initramfs 改动后 VM 无法启动 | vmrun revertToSnapshot baseline → 标记候选 `REJECTED`（功能回归） |
| Phase 5 executor SSH 超时 | Phase 5 已有 retry 逻辑——重试 3 次，间隔 5s |
| kaiming dbus method call 超时 | 降级为进程存活检查（`systemctl is-active`） |

## 8. 测试策略

| 层 | 内容 | 数量 |
|---|---|---|
| Python 单元 | `OptimizationPlan` category `kernel_param`/`initramfs_trim` 验证 | 3 |
| Python 单元 | Executor grub cmd 构造 + initramfs 备份/恢复 cmd 构造 | 8 |
| Python 单元 | `parallelize` 类型 drop-in 批量生成验证 | 4 |
| Phase 5 复用 | ABBA scheduler / validator 零改动 | 0 |
| 实机 ABBA | 5 候选 × 18 boots | ~90 boots (约 3 小时) |

## 9. 新增文件

```
src/kylinbootlab/optimization/plan.py   # +5 factory functions (phase6_*)
src/kylinbootlab/optimization/executor.py  # +kernel_param / +initramfs_trim branches
tests/test_optimization_plan.py          # +category + command construction tests
profiles/phase6/                         # +5 .toml profiles
scripts/abba_direct.py                   # 参数化 target profile switch
```

## 10. 明确不做

- UKUI 源码编译与补丁（→ Phase 7）
- 内核源码编译
- kylin-kaiming 源码调试（剥离二进制，Phase 7 需源码环境）
- 跨发行版 initramfs 工具适配（→ Phase 10）
- GRUB 超时优化（赛题明确不计 GRUB）
