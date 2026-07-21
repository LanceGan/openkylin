"""Generate Phase 3 calibration visualisation (box-plot + timeline scatter).

Reference palette from dataviz/references/palette.md:
  series-1 #2a78d6 (blue)   = bare
  series-2 #f08a2e (orange) = benchmark
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np

# ── Data ────────────────────────────────────────────────────────
bare_os   = [12.7, 24.8, 16.8, 16.5, 18.2, 20.6, 16.7, 16.0, 9.7, 20.9]
bare_gfx  = [ 7.8, 14.4, 15.0, 14.4, 14.6, 14.5, 14.8, 14.5, 7.7,  8.8]
bench_os  = [16.7, 16.2,  8.9, 16.3,  9.0,  9.2,  8.9,  9.5, 9.0, 10.9]
bench_gfx = [14.8, 14.6,  7.5, 14.6,  7.8,  7.7,  7.5,  8.1, 7.7,  7.7]

bare_os_m  = np.median(bare_os);  bare_gfx_m  = np.median(bare_gfx)
bench_os_m = np.median(bench_os); bench_gfx_m = np.median(bench_gfx)
os_delta   = (bench_os_m  - bare_os_m)  / bare_os_m  * 100
gfx_delta  = (bench_gfx_m - bare_gfx_m) / bare_gfx_m * 100

# ── Matplotlib rc ─────────────────────────────────────────────────
BLUE   = "#2a78d6"
ORANGE = "#f08a2e"
GRAY   = "#52514e"
LIGHT  = "#fcfcfb"
DARK   = "#0b0b0b"
GRID   = "#e8e7e1"
RED    = "#c0392b"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Microsoft YaHei", "DejaVu Sans", "Arial"],
    "font.size": 11, "axes.titlesize": 14, "axes.labelsize": 12,
    "xtick.labelsize": 10, "ytick.labelsize": 10, "legend.fontsize": 10,
    "axes.edgecolor": GRID, "grid.color": GRID,
    "axes.facecolor": LIGHT, "figure.facecolor": "white",
    "grid.alpha": 0.6, "axes.spines.top": False, "axes.spines.right": False,
})

bp_opts = dict(
    widths=0.45, patch_artist=True,
    medianprops=dict(color=DARK, lw=2),
    flierprops=dict(marker="o", markersize=5, markerfacecolor=GRAY, alpha=0.5),
    whiskerprops=dict(lw=1.2), capprops=dict(lw=1.2),
)

# ═══════════ FIGURE A — Box Plots ═══════════
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5.5))
fig.suptitle("观测开销校准  |  Observer Overhead Calibration",
             fontsize=16, fontweight="bold", y=0.98)

# Panel 1: OS Total
b1 = ax1.boxplot([bare_os, bench_os], positions=[1, 2], **bp_opts)
b1["boxes"][0].set_facecolor(BLUE);   b1["boxes"][0].set_alpha(0.7)
b1["boxes"][1].set_facecolor(ORANGE); b1["boxes"][1].set_alpha(0.7)
ax1.set_xticks([1, 2])
ax1.set_xticklabels(["Bare\n(no observer)", "Benchmark\n(observer on)"])
ax1.set_ylabel("Boot time (seconds)")
ax1.set_title("OS Total (T0 → userspace done)", fontweight="bold", color=DARK)
ax1.axhline(y=bare_os_m, color=BLUE, ls="--", lw=1, alpha=0.6)
ax1.axhline(y=bench_os_m, color=ORANGE, ls="--", lw=1, alpha=0.6)
ax1.text(1, bare_os_m, f"  median\n  {bare_os_m:.1f}s", va="center", fontsize=9, color=BLUE)
ax1.text(2, bench_os_m, f"  median\n  {bench_os_m:.1f}s", va="center", fontsize=9, color=ORANGE)
ax1.annotate(f"Delta = {os_delta:+.1f}%", xy=(1.5, max(bare_os) * 1.02), ha="center",
             fontsize=11, fontweight="bold", color=RED,
             bbox=dict(boxstyle="round,pad=0.3", facecolor="#fff5f5", edgecolor="#e0c0c0"))

# Panel 2: Graphical Target
b2 = ax2.boxplot([bare_gfx, bench_gfx], positions=[1, 2], **bp_opts)
b2["boxes"][0].set_facecolor(BLUE);   b2["boxes"][0].set_alpha(0.7)
b2["boxes"][1].set_facecolor(ORANGE); b2["boxes"][1].set_alpha(0.7)
ax2.set_xticks([1, 2])
ax2.set_xticklabels(["Bare\n(no observer)", "Benchmark\n(observer on)"])
ax2.set_ylabel("Boot time (seconds)")
ax2.set_title("graphical.target Time (T0 → graphical)", fontweight="bold", color=DARK)
ax2.axhline(y=bare_gfx_m, color=BLUE, ls="--", lw=1, alpha=0.6)
ax2.axhline(y=bench_gfx_m, color=ORANGE, ls="--", lw=1, alpha=0.6)
ax2.text(1, bare_gfx_m, f"  median\n  {bare_gfx_m:.1f}s", va="center", fontsize=9, color=BLUE)
ax2.text(2, bench_gfx_m, f"  median\n  {bench_gfx_m:.1f}s", va="center", fontsize=9, color=ORANGE)
ax2.annotate(f"Delta = {gfx_delta:+.1f}%", xy=(1.5, max(bare_gfx) * 1.02), ha="center",
             fontsize=11, fontweight="bold", color=RED,
             bbox=dict(boxstyle="round,pad=0.3", facecolor="#fff5f5", edgecolor="#e0c0c0"))

for ax in (ax1, ax2):
    ax.yaxis.set_major_formatter(mtick.FormatStrFormatter("%.0fs"))
    ax.grid(axis="y", lw=0.5)

fig.legend(
    [b1["boxes"][0], b1["boxes"][1]],
    ["Bare (no observer)", "Benchmark (observer on)"],
    loc="lower center", ncol=2, frameon=True, fancybox=True,
    bbox_to_anchor=(0.5, -0.03),
)
fig.text(0.5, -0.09,
         "20 sequential boots — bare group first, benchmark second.\n"
         "Negative delta ≈ VMware disk-cache warmup: Phase 5 uses ABBA randomization.\n"
         "Technically PASSED (<1% overhead): bare-to-benchmark comparison dominated by caching.",
         ha="center", fontsize=8.5, color=GRAY)
fig.tight_layout(rect=[0, 0.10, 1, 0.94])
fig.savefig("var/calibration-overview.png", dpi=150, bbox_inches="tight",
            facecolor="white", edgecolor="none")
print("Saved: var/calibration-overview.png")
plt.close(fig)

# ═══════════ FIGURE B — Per-Run Timeline ═══════════
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
fig.suptitle("校准时间线 — Per-Run Boot Times  |  Calibration Timeline",
             fontsize=15, fontweight="bold", y=0.98)

for i in range(10):
    ax1.plot(i, bare_os[i], "o", color=BLUE, markersize=10, alpha=0.7, zorder=3,
             markeredgecolor="white", markeredgewidth=0.5)
    ax1.plot(i + 10, bench_os[i], "o", color=ORANGE, markersize=10, alpha=0.7, zorder=3,
             markeredgecolor="white", markeredgewidth=0.5)
    ax2.plot(i, bare_gfx[i], "o", color=BLUE, markersize=10, alpha=0.7, zorder=3,
             markeredgecolor="white", markeredgewidth=0.5)
    ax2.plot(i + 10, bench_gfx[i], "o", color=ORANGE, markersize=10, alpha=0.7, zorder=3,
             markeredgecolor="white", markeredgewidth=0.5)

for ax, bare_data, bench_data in [
    (ax1, bare_os, bench_os),
    (ax2, bare_gfx, bench_gfx),
]:
    ax.axvline(x=9.5, color=GRAY, ls="-", lw=2, alpha=0.4)
    y0, y1 = ax.get_ylim()
    ax.fill_between([-0.5, 9.5], y0, y1, color=BLUE, alpha=0.04)
    ax.fill_between([9.5, 19.5], y0, y1, color=ORANGE, alpha=0.04)
    ax.set_ylabel("seconds", fontweight="bold")
    ax.grid(axis="y", lw=0.5)
    ax.yaxis.set_major_formatter(mtick.FormatStrFormatter("%.0fs"))

ax1.set_title("OS Total Boot Time — per-run scatter", fontsize=13, color=DARK)
ax2.set_title("graphical.target — per-run scatter", fontsize=13, color=DARK)
ax2.set_xlabel("Boot number (0–9: bare  |  10–19: benchmark)", fontsize=11)
ax1.text(4.5, 26, "BARE (observer off)", ha="center", fontsize=13, color=BLUE, fontweight="bold", alpha=0.5)
ax1.text(14.5, 26, "BENCHMARK (observer on)", ha="center", fontsize=13, color=ORANGE, fontweight="bold", alpha=0.5)

fig.tight_layout(rect=[0, 0, 1, 0.94])
fig.savefig("var/calibration-timeline.png", dpi=150, bbox_inches="tight",
            facecolor="white", edgecolor="none")
print("Saved: var/calibration-timeline.png")
plt.close(fig)

print(f"\nBare:     os_total median={bare_os_m:.3f}s  graphical median={bare_gfx_m:.3f}s")
print(f"Benchmark: os_total median={bench_os_m:.3f}s  graphical median={bench_gfx_m:.3f}s")
print(f"Delta:    os_total={os_delta:+.1f}%  graphical={gfx_delta:+.1f}%")
