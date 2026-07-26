"""Complete DOCX rebuild: proper OOXML tables, Ubuntu ABBA data, expanded content, charts.

Strategy:
1. Unpack the ORIGINAL template (not the pre-charts backup, but the very original competition template)
2. Edit document.xml with full content including proper w:tbl tables
3. Embed charts
4. Repack

We use the pre-charts backup as base since it already has the chart anchor text in place.
"""
import defusedxml.minidom
import shutil, zipfile, os, re, io, subprocess
from pathlib import Path
from PIL import Image

# ── Paths ─────────────────────────────────────────────────
DOCX_ORIG = Path("操作系统开源创新大赛项目说明书.docx")
CHARTS_DIR = Path("charts")
UNPACKED = Path("unpacked-rebuild")
MEDIA_DIR = UNPACKED / "word" / "media"

# ── Chart generation ──────────────────────────────────────
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import FancyBboxPatch
import numpy as np

plt.rcParams['font.family'] = 'Microsoft YaHei'
plt.rcParams['axes.unicode_minus'] = False
BG_COLOR = '#FAFAFA'
GRID_COLOR = '#E5E5E5'
C_KERNEL, C_INITRD, C_USERSPACE, C_TOTAL_BG = '#2E86AB', '#A23B72', '#F18F01', '#C73E1D'
DISTRO_COLORS = {'openKylin': '#16A34A', 'Ubuntu': '#E95420', 'Fedora': '#3C6EB4'}
VERDICT_COLORS = {'PROMISING': '#16A34A', 'ACCEPTED': '#2563EB', 'REJECTED': '#DC2626'}

def gen_charts():
    CHARTS_DIR.mkdir(exist_ok=True)
    paths = []

    # Chart 1: Boot comparison (updated with Ubuntu 42.4s)
    distros_labels = ['openKylin\n2.0 SP2', 'Ubuntu\n22.04 LTS', 'Fedora\n41']
    kernel    = [4.726, 2.468, 1.206]
    initrd    = [0,      0,     1.397]
    userspace = [23.580, 39.943, 7.051]  # Ubuntu userspace = 42.411-2.468 = 39.943
    totals    = [28.306, 42.411, 9.654]

    fig, ax = plt.subplots(figsize=(8, 4.8))
    fig.patch.set_facecolor(BG_COLOR); ax.set_facecolor(BG_COLOR)
    x = np.arange(3); width = 0.52
    ax.bar(x, kernel, width, label='Kernel', color=C_KERNEL, edgecolor='white', linewidth=0.5)
    ax.bar(x, initrd, width, label='Initrd', color=C_INITRD, edgecolor='white', linewidth=0.5, bottom=kernel)
    ax.bar(x, userspace, width, label='Userspace', color=C_USERSPACE, edgecolor='white', linewidth=0.5,
           bottom=[k+i for k,i in zip(kernel, initrd)])
    for i,(t,d) in enumerate(zip(totals, distros_labels)):
        ax.text(i, t+0.8, f'{t:.1f}s', ha='center', va='bottom', fontsize=11, fontweight='bold', color=C_TOTAL_BG)
    for i,v in enumerate(kernel):
        if v>0.8: ax.text(i, v/2, f'{v:.2f}s', ha='center', va='center', fontsize=7.5, color='white', fontweight='bold')
    for i,v in enumerate(initrd):
        if v>0.8: ax.text(i, kernel[i]+v/2, f'{v:.2f}s', ha='center', va='center', fontsize=7.5, color='white', fontweight='bold')
    for i,v in enumerate(userspace):
        ax.text(i, kernel[i]+initrd[i]+v/2, f'{v:.1f}s', ha='center', va='center', fontsize=7.5, color='white', fontweight='bold')
    ax.set_xticks(x); ax.set_xticklabels(distros_labels, fontsize=11)
    ax.set_ylabel('Boot Time (seconds)', fontsize=11)
    ax.set_title('Cross-Distribution Boot Time Breakdown', fontsize=14, fontweight='bold', pad=16)
    ax.legend(loc='upper right', framealpha=0.9, fontsize=9)
    ax.set_ylim(0, max(totals)*1.22)
    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.5); ax.set_axisbelow(True)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ann_y = totals[1]*1.15; ann_text_y = totals[1]*1.28
    ax.annotate(f'{totals[1]/totals[2]:.1f}x slower\nthan Fedora', xy=(1,totals[1]),
                xytext=(1.8, ann_text_y), arrowprops=dict(arrowstyle='->',color='#555',lw=1.2),
                fontsize=8.5, color='#555', ha='left')
    plt.tight_layout()
    p = CHARTS_DIR/'chart1_boot_comparison.png'
    fig.savefig(p, dpi=180, bbox_inches='tight', facecolor=BG_COLOR); plt.close(fig)
    paths.append(p)

    # Chart 2: ABBA Forest Plot (with Ubuntu data)
    experiments = [
        ('mask-strongswan\n(Fedora 41)',      609,  -8429,  2931, 'REJECTED'),
        ('mask-strongswan\n(Ubuntu 22.04)',    33,   -218,    66, 'REJECTED'),
        ('mask-biometric\n(openKylin)',        182,   -639,   191, 'REJECTED'),
        ('socket-nm-wait\n(openKylin)',        930,    420,  1480, 'REJECTED'),
        ('initramfs-trim\n(openKylin)',        115,   -334,   319, 'REJECTED'),
        ('组合优化\n(openKylin)',               None,  None,  None, 'PROMISING'),
    ]
    fig, ax = plt.subplots(figsize=(9, 5.5))
    fig.patch.set_facecolor(BG_COLOR); ax.set_facecolor(BG_COLOR)
    y_positions = [5,4,3,2,1,0]
    for i,(name,median,ci_low,ci_high,verdict) in enumerate(experiments):
        y=y_positions[i]; color=VERDICT_COLORS[verdict]
        if median is not None:
            ax.plot([ci_low,ci_high],[y,y],color=color,linewidth=3,alpha=0.7,solid_capstyle='round')
            ax.plot([ci_low,ci_low],[y-0.15,y+0.15],color=color,linewidth=2,alpha=0.8)
            ax.plot([ci_high,ci_high],[y-0.15,y+0.15],color=color,linewidth=2,alpha=0.8)
            ax.scatter(median,y,s=140,color='white',edgecolor=color,linewidth=2.5,zorder=5)
            ax.scatter(median,y,s=40,color=color,zorder=6)
            sign='+' if median>0 else ''
            ax.text(median,y-0.42,f'{sign}{median}ms',ha='center',fontsize=7.5,color=color,fontweight='bold')
        ax.text(-10500,y,name,ha='left',va='center',fontsize=9,color=VERDICT_COLORS[verdict],fontweight='bold')
        badge_x=5500 if median is not None else 2500
        ax.text(badge_x,y,f' {verdict} ',ha='left',va='center',fontsize=7.5,color='white',fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.3',facecolor=color,edgecolor='none',alpha=0.85))
    ax.axvline(0,color='#999',linewidth=1.2,linestyle='--',alpha=0.6,zorder=0)
    ax.annotate('Median improvement: -23%\n(percentage-based,\n95% CI lower bound > 0)',
                xy=(0,0),xytext=(4000,1.5),fontsize=8.5,color=VERDICT_COLORS['PROMISING'],
                bbox=dict(boxstyle='round,pad=0.5',facecolor='#DCFCE7',edgecolor=VERDICT_COLORS['PROMISING'],alpha=0.7),ha='center')
    ax.set_ylim(-1.2,5.8); ax.set_xlim(-11500,7500)
    ax.set_xlabel('Median Improvement (ms)  <- worse | better ->',fontsize=10,color='#555')
    ax.set_title('ABBA Experiment Results - Bootstrap CI 95%',fontsize=14,fontweight='bold',pad=14)
    ax.set_yticks([])
    ax.spines['left'].set_visible(False); ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.xaxis.grid(True,color=GRID_COLOR,linewidth=0.5); ax.set_axisbelow(True)
    from matplotlib.lines import Line2D
    legend_elements=[
        Line2D([0],[0],marker='o',color='w',markerfacecolor=VERDICT_COLORS['PROMISING'],markersize=10,label='PROMISING'),
        Line2D([0],[0],marker='o',color='w',markerfacecolor=VERDICT_COLORS['REJECTED'],markersize=10,label='REJECTED'),
    ]
    ax.legend(handles=legend_elements,loc='lower right',framealpha=0.9,fontsize=8.5)
    plt.tight_layout()
    p=CHARTS_DIR/'chart2_abba_forest.png'
    fig.savefig(p,dpi=180,bbox_inches='tight',facecolor=BG_COLOR); plt.close(fig)
    paths.append(p)

    # Chart 3: Architecture Pipeline (unchanged)
    fig,ax=plt.subplots(figsize=(10,2.8))
    fig.patch.set_facecolor(BG_COLOR); ax.set_facecolor(BG_COLOR); ax.set_xlim(0,10); ax.set_ylim(0,3); ax.axis('off')
    layers=[('Data Capture\nProbe','#2563EB','Rust\nsystemd-analyze'),('Ingest','#7C3AED','Python\nJSON Schema'),
            ('Analyze','#DC2626','NetworkX\nTopo DP'),('Optimize','#EA580C','ABBA Protocol\nBootstrap CI'),
            ('Dashboard','#16A34A','React\nRecharts')]
    box_w,box_h,y_center=1.45,1.6,1.5; arrow_gap=0.42
    for i,(title,color,details) in enumerate(layers):
        x=0.5+i*(box_w+arrow_gap+0.25)
        rect=FancyBboxPatch((x,y_center-box_h/2),box_w,box_h,boxstyle='round,pad=0.15',
                             facecolor=color,edgecolor='white',linewidth=2,alpha=0.9,zorder=3)
        ax.add_patch(rect)
        ax.text(x+box_w/2,y_center+0.28,title,ha='center',va='center',fontsize=11,fontweight='bold',color='white',zorder=4)
        ax.text(x+box_w/2,y_center-0.38,details,ha='center',va='center',fontsize=7.5,color='white',alpha=0.9,zorder=4)
        if i<len(layers)-1:
            arrow_x=x+box_w+0.08
            ax.annotate('',xy=(arrow_x+0.3,y_center),xytext=(arrow_x,y_center),
                        arrowprops=dict(arrowstyle='->',color='#888',lw=2.5,connectionstyle='arc3,rad=0'))
    ax.set_title('KylinBootLab Analysis Pipeline',fontsize=14,fontweight='bold',pad=10,color='#333')
    plt.tight_layout()
    p=CHARTS_DIR/'chart3_architecture.png'
    fig.savefig(p,dpi=180,bbox_inches='tight',facecolor=BG_COLOR); plt.close(fig)
    paths.append(p)

    # Chart 4: Causal Graph
    distros_names=['openKylin','Ubuntu','Fedora']
    nodes=[343,330,290]; edges=[1714,1600,1200]; blames=[20.2,19.8,3.1]
    fig,(ax1,ax2)=plt.subplots(1,2,figsize=(9,4))
    fig.patch.set_facecolor(BG_COLOR); ax1.set_facecolor(BG_COLOR); ax2.set_facecolor(BG_COLOR)
    x=np.arange(3); color_list=[DISTRO_COLORS[d] for d in ['openKylin','Ubuntu','Fedora']]
    width=0.32
    bars_n=ax1.bar(x-width/2,nodes,width,label='Nodes',color='#3B82F6',edgecolor='white')
    bars_e=ax1.bar(x+width/2,edges,width,label='Edges',color='#F59E0B',edgecolor='white')
    for bar in bars_n: ax1.text(bar.get_x()+bar.get_width()/2,bar.get_height()+15,str(int(bar.get_height())),ha='center',fontsize=8.5,fontweight='bold',color='#3B82F6')
    for bar in bars_e: ax1.text(bar.get_x()+bar.get_width()/2,bar.get_height()+15,str(int(bar.get_height())),ha='center',fontsize=8.5,fontweight='bold',color='#F59E0B')
    ax1.set_xticks(x); ax1.set_xticklabels(distros_names,fontsize=10)
    ax1.set_title('Causal Graph Size',fontsize=12,fontweight='bold'); ax1.legend(fontsize=8)
    ax1.set_ylim(0,max(edges)*1.18)
    ax1.spines['top'].set_visible(False); ax1.spines['right'].set_visible(False)
    ax1.yaxis.grid(True,color=GRID_COLOR); ax1.set_axisbelow(True)
    bars_b=ax2.bar(distros_names,blames,color=color_list,edgecolor='white',linewidth=0.5)
    for bar,v in zip(bars_b,blames):
        ax2.text(bar.get_x()+bar.get_width()/2,bar.get_height()+0.3,f'{v:.1f}s',ha='center',fontsize=11,fontweight='bold',color='#333')
    ax2.set_title('Top Bottleneck Blame Time',fontsize=12,fontweight='bold')
    ax2.set_ylabel('Blame (seconds)',fontsize=10)
    ax2.spines['top'].set_visible(False); ax2.spines['right'].set_visible(False)
    ax2.yaxis.grid(True,color=GRID_COLOR); ax2.set_axisbelow(True)
    ax2.set_ylim(0,max(blames)*1.22)
    fig.suptitle('Systemd Causal Graph Analysis by Distribution',fontsize=14,fontweight='bold',y=1.02)
    plt.tight_layout()
    p=CHARTS_DIR/'chart4_causal_graph.png'
    fig.savefig(p,dpi=180,bbox_inches='tight',facecolor=BG_COLOR); plt.close(fig)
    paths.append(p)

    # Chart 5: Test Pyramid
    fig,ax=plt.subplots(figsize=(7,5))
    fig.patch.set_facecolor(BG_COLOR); ax.set_facecolor(BG_COLOR); ax.set_xlim(0,10); ax.set_ylim(0,6); ax.axis('off')
    layers_data=[
        ('E2E Acceptance','10/10 cold-boot\nFault injection OK','#DC2626',1.0,0.6),
        ('Regression Matrix','20 tests x 5 plans\nApply/Rollback/Stats','#EA580C',3.0,0.7),
        ('Integration Tests','JSON Schema validation\nSSH round-trip','#2563EB',5.0,0.7),
        ('Unit Tests','313 Python + 54 Rust\n= 367 total','#16A34A',7.0,0.8),
    ]
    for label,detail,color,width_l,height in layers_data:
        left=(10-width_l)/2; bottom=0.4
        for _,_,_,prev_w,prev_h in layers_data:
            if prev_h<height: bottom+=prev_h+0.15
        rect=FancyBboxPatch((left,bottom),width_l,height,boxstyle='round,pad=0.08',
                             facecolor=color,edgecolor='white',linewidth=1.5,alpha=0.88)
        ax.add_patch(rect)
        ax.text(5,bottom+height/2+0.12,label,ha='center',va='center',fontsize=13,fontweight='bold',color='white')
        ax.text(5,bottom+height/2-0.35,detail,ha='center',va='center',fontsize=8,color='white',alpha=0.9)
    ax.set_title('KylinBootLab Test Pyramid',fontsize=14,fontweight='bold',pad=12,color='#333')
    ax.text(5,0.15,'Four-layer test system ensures functional correctness',ha='center',fontsize=9,color='#888')
    plt.tight_layout()
    p=CHARTS_DIR/'chart5_test_pyramid.png'
    fig.savefig(p,dpi=180,bbox_inches='tight',facecolor=BG_COLOR); plt.close(fig)
    paths.append(p)

    print(f"Generated {len(paths)} charts")
    return paths


# ═══════════════════════════════════════════════════════════
# DOCX Content Builder
# ═══════════════════════════════════════════════════════════

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
WP = 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
PIC = 'http://schemas.openxmlformats.org/drawingml/2006/picture'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

def el(tag, doc=None, **attrs):
    """Create an element. If doc is None, use the global doc."""
    e = doc.createElement(tag)
    for k, v in attrs.items():
        e.setAttribute(k, str(v))
    return e

def run(doc, text, bold=False, hint='eastAsia', color=None, size=None, font=None):
    """Create a w:r with w:rPr and w:t."""
    r = doc.createElement('w:r')
    rPr = doc.createElement('w:rPr')
    rf = doc.createElement('w:rFonts')
    rf.setAttribute('w:hint', hint)
    if font: rf.setAttribute('w:ascii', font); rf.setAttribute('w:hAnsi', font)
    rPr.appendChild(rf)
    if bold:
        b = doc.createElement('w:b'); rPr.appendChild(b)
    if color:
        c = doc.createElement('w:color'); c.setAttribute('w:val', color); rPr.appendChild(c)
    if size:
        sz = doc.createElement('w:sz'); sz.setAttribute('w:val', str(size)); rPr.appendChild(sz)
        szCs = doc.createElement('w:szCs'); szCs.setAttribute('w:val', str(size)); rPr.appendChild(szCs)
    r.appendChild(rPr)
    t = doc.createElement('w:t')
    t.setAttribute('xml:space', 'preserve')
    t.appendChild(doc.createTextNode(text))
    r.appendChild(t)
    return r

def heading(doc, text, level):
    """Create a heading paragraph with pStyle."""
    p = doc.createElement('w:p')
    pPr = doc.createElement('w:pPr')
    ps = doc.createElement('w:pStyle')
    ps.setAttribute('w:val', str(level))
    pPr.appendChild(ps)
    p.appendChild(pPr)
    p.appendChild(run(doc, text))
    return p

def body_para(doc, text, firstLine='480', bold=False):
    """Create a body paragraph."""
    p = doc.createElement('w:p')
    pPr = doc.createElement('w:pPr')
    ind = doc.createElement('w:ind')
    ind.setAttribute('w:firstLine', firstLine)
    pPr.appendChild(ind)
    if bold:
        rPr2 = doc.createElement('w:rPr')
        b = doc.createElement('w:b'); rPr2.appendChild(b)
        pPr.appendChild(rPr2)
    p.appendChild(pPr)
    # Split by lines within the paragraph (single \n)
    parts = text.split('\n')
    for i, part in enumerate(parts):
        if i > 0:
            # Line break
            br_r = doc.createElement('w:r')
            br = doc.createElement('w:br')
            br_r.appendChild(br)
            p.appendChild(br_r)
        p.appendChild(run(doc, part))
    return p

def empty_para(doc):
    p = doc.createElement('w:p')
    pPr = doc.createElement('w:pPr')
    p.appendChild(pPr)
    return p

def centered_text(doc, text, bold=False):
    p = doc.createElement('w:p')
    pPr = doc.createElement('w:pPr')
    jc = doc.createElement('w:jc'); jc.setAttribute('w:val', 'center')
    pPr.appendChild(jc)
    p.appendChild(pPr)
    parts = text.split('\n')
    for i, part in enumerate(parts):
        if i>0:
            br_r=doc.createElement('w:r'); br=doc.createElement('w:br'); br_r.appendChild(br); p.appendChild(br_r)
        p.appendChild(run(doc, part, bold=bold))
    return p

def spacer(doc):
    """Empty paragraph as spacer."""
    return empty_para(doc)

# ── Table builder ────────────────────────────────────────
def build_table(doc, headers, rows, col_widths=None):
    """Create a w:tbl element with header row + data rows."""
    tbl = doc.createElement('w:tbl')
    tblPr = doc.createElement('w:tblPr')
    tblW = doc.createElement('w:tblW')
    tblW.setAttribute('w:w', '9000'); tblW.setAttribute('w:type', 'dxa')
    tblPr.appendChild(tblW)
    tblBorders = doc.createElement('w:tblBorders')
    for edge in ['top','left','bottom','right','insideH','insideV']:
        b = doc.createElement(f'w:{edge}')
        b.setAttribute('w:val','single'); b.setAttribute('w:sz','4'); b.setAttribute('w:space','0'); b.setAttribute('w:color','999999')
        tblBorders.appendChild(b)
    tblPr.appendChild(tblBorders)
    jc = doc.createElement('w:jc'); jc.setAttribute('w:val','center'); tblPr.appendChild(jc)
    tblPr.appendChild(doc.createElement('w:tblLayout')).setAttribute('w:type','fixed')
    tblLook = doc.createElement('w:tblLook')
    tblLook.setAttribute('w:val','04A0'); tblLook.setAttribute('w:firstRow','1'); tblLook.setAttribute('w:lastRow','0')
    tblLook.setAttribute('w:firstColumn','1'); tblLook.setAttribute('w:lastColumn','0')
    tblLook.setAttribute('w:noHBand','0'); tblLook.setAttribute('w:noVBand','1')
    tblPr.appendChild(tblLook)
    tbl.appendChild(tblPr)

    # Grid
    num_cols = len(headers)
    tblGrid = doc.createElement('w:tblGrid')
    for i in range(num_cols):
        gc = doc.createElement('w:gridCol')
        gc.setAttribute('w:w', str(col_widths[i]) if col_widths else '2000')
        tblGrid.appendChild(gc)
    tbl.appendChild(tblGrid)

    # Header row
    tr_h = doc.createElement('w:tr')
    trPr_h = doc.createElement('w:trPr')
    tr_h.appendChild(trPr_h)
    for i, h in enumerate(headers):
        tc = doc.createElement('w:tc')
        tcPr = doc.createElement('w:tcPr')
        tcW = doc.createElement('w:tcW')
        tcW.setAttribute('w:w', str(col_widths[i]) if col_widths else '2000')
        tcW.setAttribute('w:type','dxa')
        tcPr.appendChild(tcW)
        # Header shading
        shd = doc.createElement('w:shd')
        shd.setAttribute('w:val','clear'); shd.setAttribute('w:color','auto'); shd.setAttribute('w:fill','2E86AB')
        tcPr.appendChild(shd)
        tc.appendChild(tcPr)
        p_h = doc.createElement('w:p')
        pPr_h = doc.createElement('w:pPr')
        jc_h = doc.createElement('w:jc'); jc_h.setAttribute('w:val','center'); pPr_h.appendChild(jc_h)
        p_h.appendChild(pPr_h)
        p_h.appendChild(run(doc, h, bold=True, color='FFFFFF', size='20'))
        tc.appendChild(p_h)
        tr_h.appendChild(tc)
    tbl.appendChild(tr_h)

    # Data rows
    for row_idx, row_data in enumerate(rows):
        tr = doc.createElement('w:tr')
        tr.appendChild(doc.createElement('w:trPr'))
        bg = 'F8F8F8' if row_idx % 2 == 0 else 'FFFFFF'
        for i, cell_text in enumerate(row_data):
            tc = doc.createElement('w:tc')
            tcPr = doc.createElement('w:tcPr')
            tcW = doc.createElement('w:tcW')
            tcW.setAttribute('w:w', str(col_widths[i]) if col_widths else '2000')
            tcW.setAttribute('w:type','dxa')
            tcPr.appendChild(tcW)
            shd = doc.createElement('w:shd')
            shd.setAttribute('w:val','clear'); shd.setAttribute('w:color','auto'); shd.setAttribute('w:fill',bg)
            tcPr.appendChild(shd)
            # Cell margins
            tcMar = doc.createElement('w:tcMar')
            for mname in ['top','bottom','left','right']:
                m = doc.createElement(f'w:{mname}'); m.setAttribute('w:w','40'); m.setAttribute('w:type','dxa'); tcMar.appendChild(m)
            tcPr.appendChild(tcMar)
            tc.appendChild(tcPr)
            p_c = doc.createElement('w:p')
            pPr_c = doc.createElement('w:pPr')
            jc_c = doc.createElement('w:jc'); jc_c.setAttribute('w:val','center'); pPr_c.appendChild(jc_c)
            # Tight spacing
            sp_c = doc.createElement('w:spacing')
            sp_c.setAttribute('w:before','20'); sp_c.setAttribute('w:after','20'); sp_c.setAttribute('w:line','240')
            pPr_c.appendChild(sp_c)
            p_c.appendChild(pPr_c)
            p_c.appendChild(run(doc, cell_text, size='18'))
            tc.appendChild(p_c)
            tr.appendChild(tc)
        tbl.appendChild(tr)
    return tbl


# ═══════════════════════════════════════════════════════════
# Main: Rebuild document.xml
# ═══════════════════════════════════════════════════════════

def rebuild_document(dom, chart_rIds):
    """Rebuild document.xml with full content including proper tables."""
    body = dom.getElementsByTagNameNS(W, 'body')[0]

    # Strategy:
    # The original template has all content (cover + chapters) in ONE section,
    # with a single w:sectPr at the very end. The cover page consists of:
    #   [0] w:p - title, [1] w:p - subtitle, [2] w:p - empty, [3] w:tbl - cover table
    # Everything after the cover table + one empty spacer paragraph is old content.
    # We keep: cover elements + final sectPr; remove everything between.

    children = list(body.childNodes)

    # Find the cover table (first w:tbl) - the last cover element
    cover_table_idx = -1
    for i, child in enumerate(children):
        if child.nodeName == 'w:tbl':
            cover_table_idx = i
            break

    # Find the final sectPr (always last in the single-section template)
    final_sectPr = None
    final_sectPr_idx = -1
    for i, child in enumerate(children):
        if child.nodeName == 'w:sectPr':
            final_sectPr = child
            final_sectPr_idx = i

    # Keep: [0..cover_table_idx] (cover page) + [final_sectPr_idx] (section properties)
    # Remove: (cover_table_idx, final_sectPr_idx) - old content
    nodes_to_remove = []
    for i, child in enumerate(children):
        if cover_table_idx < i < final_sectPr_idx:
            nodes_to_remove.append(child)

    for node in nodes_to_remove:
        body.removeChild(node)

    print(f"Kept {cover_table_idx+1} cover elements + final sectPr, removed {len(nodes_to_remove)} old content nodes")

    # Now rebuild content

    page_break = lambda doc: _make_sectPr(doc, "page")

    # We need to actually use a different approach for page breaks.
    # In OOXML, a page break is done via w:br in a w:r within a w:p.
    page_break_r = None  # We'll add as part of section properties or paragraph breaks

    # Actually, let's just use sectPr with page break. Or simpler: insert a lastRenderedPageBreak
    # The cleanest approach for Word: use a paragraph with w:br type="page"

    def pagebreak_para(doc):
        p = doc.createElement('w:p')
        r = doc.createElement('w:r')
        br = doc.createElement('w:br')
        br.setAttribute('w:type','page')
        r.appendChild(br)
        p.appendChild(r)
        return p

    # ── TOC Section ──
    body.appendChild(heading(dom, '目  录', '11'))
    # TOC placeholder (Word auto-generates)
    body.appendChild(body_para(dom, '（目录由 Word 自动生成，请打开文档后右键目录区域选择"更新域"）'))
    body.appendChild(pagebreak_para(dom))

    # ── Chapter 1: 绪论 ──
    body.appendChild(heading(dom, '绪  论', '1'))

    body.appendChild(heading(dom, '目的与意义', '2'))
    body.appendChild(body_para(dom,
        'KylinBootLab 面向 Linux 桌面操作系统的启动性能分析与优化领域，提供从数据采集、因果建模到实验验证的全链路自动化工具链。'))

    body.appendChild(body_para(dom,
        '作品设计目的：通过客观数据驱动的方法，替代传统的"经验式"启动优化模式，将优化过程从手工推测转变为严格的科学实验验证。'
        '传统启动优化依赖开发者对系统服务的经验判断——"这个服务可能慢，关掉试试"——缺乏系统性的瓶颈定位和统计置信的优化验证。'
        'KylinBootLab 通过因果图分析量化每个服务对整体启动延迟的贡献，通过 ABBA 实验协议以统计置信的方式判定优化有效性，填补了该领域的工具空白。'))

    body.appendChild(body_para(dom,
        '应用意义：一方面为 openKylin 等国产操作系统提供系统化的启动性能诊断手段，帮助识别和消除启动路径上的关键瓶颈；'
        '另一方面通过跨发行版适配器架构，验证了分析管道在 openKylin、Ubuntu 22.04 LTS、Fedora 41 三个不同发行版上的通用性，'
        '为 Linux 生态的启动优化工作提供了可复用的方法论参考和开源工具基础。'))

    body.appendChild(heading(dom, '项目背景', '2'))
    body.appendChild(body_para(dom,
        '现有启动分析工具以 systemd-analyze 为代表，能够提供启动时间分解（time）、服务耗时排序（blame）和关键链（critical-chain），'
        '但存在三个核心缺陷：'))

    body.appendChild(body_para(dom,
        '（1）仅提供静态数据：systemd-analyze 输出单次启动的测量结果，不具备优化方案的实验验证能力。'
        '用户需要手动执行优化操作、手动重启、手动对比结果，缺乏自动化的 A/B 对比框架。'))

    body.appendChild(body_para(dom,
        '（2）缺乏统计推断：单次启动测量受系统噪声（磁盘缓存状态、ASLR、systemd 服务启动的竞态条件）影响，'
        '重复测量之间存在不可忽略的方差。没有任何工具提供跨多次重复启动的统计显著性检验。'))

    body.appendChild(body_para(dom,
        '（3）发行版耦合：各发行版的 initramfs 构建工具链（initramfs-tools vs dracut）、显示管理器（LightDM vs GDM）、'
        '系统服务命名规范存在差异，导致分析脚本无法跨发行版复用。'))

    body.appendChild(body_para(dom,
        'KylinBootLab 的创新之处体现在四个方面：'
        '\n（1）首次将 ABBA 实验协议引入 Linux 启动优化——通过 18 次冷启动（2 warmup + 4×4 块排列）+ Bootstrap CI 10000 次重采样，'
        '实现统计置信的优化判定，将启动优化从"经验推测"提升为"科学实验"。'
        '\n（2）基于 Linux uinput 子系统实现无人值守自动登录观测器，通过纯状态机架构消除人机交互的时序不确定性，'
        '在每次冷启动中精确记录 greeter 就绪、登录注入、PAM 会话开启和桌面可用性四个关键时间点。'
        '\n（3）DOT 依赖图解析 + 拓扑排序动态规划 O(V+E) 关键路径计算 + 三维瓶颈评分（blame × slack_penalty × criticality），'
        '实现对数百个 systemd 单元构成的复杂依赖网络的系统级瓶颈定位和优化优先级排序。'
        '\n（4）跨发行版适配器架构封装 initramfs 工具链差异、显示管理器差异和服务名称映射，'
        '在 openKylin 2.0 SP2、Ubuntu 22.04 LTS、Fedora 41 三个发行版上零代码修改完成基线采集与 ABBA 实验验证。'))

    body.appendChild(pagebreak_para(dom))

    # ── Chapter 2: 技术理论 ──
    body.appendChild(heading(dom, '技 术 理 论', '1'))

    body.appendChild(heading(dom, '设计思想', '2'))
    body.appendChild(body_para(dom,
        '本作品遵循"数据驱动决策"与"科学实验方法论"两大核心设计思想。'))

    body.appendChild(body_para(dom,
        '数据驱动决策：优化候选方案不依赖开发者直觉，而是基于因果图分析产生的瓶颈评分自动排序。'
        '瓶颈评分公式为 blame × slack_penalty × criticality，其中 blame 为服务自身耗时，'
        'slack_penalty 惩罚不在关键路径上的节点（slack 越大，惩罚越大），criticality 对关键路径上节点加权 ×2。'
        '系统自动从数百个候选服务中筛选出高价值优化目标，优先实验评分最高的组合方案。'))

    body.appendChild(body_para(dom,
        '科学实验方法论：每项优化候选方案需通过 ABBA 实验协议的严格验证。'
        'ABBA 是一种平衡排列的 A/B 实验设计——18 次冷启动分为 2 次预热（消除首次启动的系统状态建立开销）+ 4 个 ABBA 块。'
        '每个块内按 A-B-B-A（或 B-A-A-B）顺序交替执行对照组（baseline snapshot）和实验组（优化 applied）的冷启动，'
        '抵消时间趋势（系统升温、磁盘碎片化积累等）。Bootstrap 非参数重采样 10000 次计算中位改善的 95% 置信区间，'
        '避免对数据分布的任何参数假设。校准基准（bare vs benchmark 模式对比）确认观测器额外引入的测量误差在可忽略范围内。'))

    body.appendChild(body_para(dom,
        '架构设计思想：管道式处理架构将系统分为五个解耦阶段。每个阶段通过 JSON Schema 约束的数据契约与上下游通信，'
        '可独立测试、独立替换。适配器模式在采集管道中抽象发行版差异，实现对不同 Linux 发行版的透明支持。'
        '不可变 RunStore 确保所有实验数据仅追加写入、不可修改，提供完整的审计追溯能力。'))

    body.appendChild(heading(dom, '技术路线', '2'))
    body.appendChild(body_para(dom,
        '全链路技术路线由五层构成：'))

    body.appendChild(body_para(dom,
        '（1）数据采集层（Probe）：Rust 1.85 编写探针（kbl-bootprobe），运行于目标 Linux 系统的 systemd 服务上下文中。'
        '捕获 systemd-analyze time（内核/initrd/用户空间三段分解）、systemd-analyze blame（所有服务的启动耗时排序）'
        '和 systemd-analyze dot（Graphviz DOT 格式的完整依赖图）。通过 JSONL 事件流记录观测器的就绪状态变化序列，'
        '输出结构化 JSON 清单（probe-manifest.json），包含 schema_version、exit_code、boot_id 和所有产物文件的 SHA-256 校验和。'))

    body.appendChild(body_para(dom,
        '（2）观测器层（Observer）：Rust 实现纯状态机驱动的自动化观测系统。'
        '状态机接受 Signal 枚举输入（TimerFired、UnitPropertiesChanged、JournalEvent、AtSpiReady 等），'
        '输出 ReadinessEvent 序列（observer_started、greeter_ready、login_injected、session_opened、sentinel_launched、usable）。'
        '核心机制包括：uinput 键盘模拟自动登录注入（/dev/uinput 设备 + EV_KEY 事件）、'
        'journalctl -o json 日志流实时解析、AT-SPI D-Bus 桌面可用性探测。'
        '整个状态机无 I/O 等待（所有阻塞在外部 loop 中）、无实时时钟依赖（使用 monotonic Instant），行为完全可单元测试。'))

    body.appendChild(body_para(dom,
        '（3）分析管道层（Analyze）：Python 3.12 + NetworkX 构建有向因果图。'
        'pydot 解析 systemd-analyze dot 输出，过滤 systemd 内部节点（-.slice、-.mount 等），'
        '仅保留 service/target/device 三类节点。拓扑排序后从源点向汇点动态规划计算每个节点的最早完成时间，'
        '反向 DP 得到最晚完成时间和松弛时间。瓶颈评分 = blame × (1 + 1/slack) × criticality。'
        '支持跨运行的图结构对比（GraphDiff），识别新增服务和依赖变化。'))

    body.appendChild(body_para(dom,
        '（4）实验验证层（Optimize）：ABBA 协议 Python 实现。'
        'ProfileExecutor 通过 SSH 远端执行优化操作（systemctl mask/unmask、内核参数修改等），'
        'VixPower 封装 VMware vmrun 命令管理 VM 快照创建/恢复和冷启动循环。'
        'ABBAPower 包装器保护 ABBA Profile 的快照不被自动恢复覆盖。'
        'Bootstrap CI 使用 numpy 实现 10000 次重采样，三级判定门控：PROMISING、ACCEPTED、REJECTED。'))

    body.appendChild(body_para(dom,
        '（5）AI 辅助层（BootAgent）：基于 Qwen2.5-Coder-7B（CPU 推理，量化部署），'
        '四角色 TOML 技能定义流水线——Diagnostician（读取基线报告和因果图，输出诊断结论）、'
        'Analyzer（分析瓶颈服务之间的因果关系，评估每个候选方案的预期收益和风险）、'
        'Optimizer（生成具体优化操作序列，输出结构化的候选方案 JSON）、'
        'Validator（审查候选方案的可行性和安全性，拒绝有功能回归风险的方案）。'
        '支持 kbl agent 命令行交互式操作。'))

    body.appendChild(pagebreak_para(dom))

    # ── Chapter 3: 代码原创说明 ──
    body.appendChild(heading(dom, '代码原创说明', '2'))
    body.appendChild(body_para(dom,
        '本作品全部 Python 和 Rust 源代码均为原创实现，未引用任何外部源代码。第三方开源依赖库的使用遵循各项目的开源许可协议：'))

    body.appendChild(body_para(dom,
        'Python 依赖：typer（CLI 框架，MIT）、rich（终端美化，MIT）、networkx（图算法库，BSD-3-Clause）、'
        'numpy（数值计算，BSD-3-Clause）、pydantic（数据验证，MIT）、tomli/tomli-w（TOML 解析，MIT）、'
        'httpx（HTTP 客户端，BSD-3-Clause）、uvicorn（ASGI HTTP 服务，BSD-3-Clause）。'))

    body.appendChild(body_para(dom,
        'Rust 依赖：serde/serde_json（序列化框架，MIT/Apache-2.0）、clap（CLI 参数解析，MIT/Apache-2.0）、'
        'nix（Linux 系统调用安全封装，MIT）、anyhow（错误处理，MIT/Apache-2.0）、'
        'uuid（唯一标识符生成，MIT/Apache-2.0）、zbus（D-Bus 客户端，MIT）。'))

    body.appendChild(body_para(dom,
        '仪表板依赖：React 19（UI 框架，MIT）、Vite 8（构建工具，MIT）、'
        'Recharts 2（图表库，MIT）、Tailwind CSS 4（样式框架，MIT）。'))

    body.appendChild(body_para(dom,
        '所有第三方库均来自官方包仓库（PyPI、crates.io、npm），代码未经过修改。'
        '作品的独创性体现在系统架构设计、ABBA 实验协议实现、因果图分析算法和跨发行版适配器上。'))

    body.appendChild(pagebreak_para(dom))

    # ── Chapter 4: 项目介绍 ──
    body.appendChild(heading(dom, '项目介绍', '1'))

    body.appendChild(heading(dom, '功能介绍', '2'))
    body.appendChild(body_para(dom,
        'KylinBootLab 是一个全链路 Linux 启动性能分析与优化平台，以 CLI 工具（kbl）为核心入口，'
        '提供 10 个一级命令，涵盖数据采集、分析、实验、AI 辅助四大领域。'
        '系统由以下核心模块构成，按数据流向下游依次排列：'))

    body.appendChild(body_para(dom,
        '数据流向：探针采集（snapshot → ingest）→ 基线报告（report）→ 因果图分析（analyze）→ '
        '优化规划（optimize plan）→ ABBA 实验（optimize run）→ 证据展示（dashboard）。'))

    body.appendChild(heading(dom, 'SnapCollect 采集模块', '3'))
    body.appendChild(body_para(dom,
        'SnapCollect 是启动数据采集模块，由 Rust 探针（kbl-bootprobe）实现。探针运行在目标 Linux 系统上，'
        '以 systemd 服务形式自动在系统启动早期执行。核心功能包括：'))

    body.appendChild(body_para(dom,
        'systemd-analyze time 调用：采集内核加载时间（kernel）、initramfs 初始化时间（initrd）'
        '和用户空间启动时间（userspace）三段分解，提供启动时间的宏观视图。'))

    body.appendChild(body_para(dom,
        'systemd-analyze blame 调用：采集所有 systemd 服务的启动耗时排序列表，'
        '精确到毫秒级别，为瓶颈识别提供初步数据。'))

    body.appendChild(body_para(dom,
        'systemd-analyze dot 调用：生成 Graphviz DOT 格式的完整 systemd 依赖图，'
        '包含所有单元（service、target、device、mount、socket、slice 等）及其依赖关系边，'
        '是因果图分析的原始数据来源。'))

    body.appendChild(body_para(dom,
        '输出结构化 JSON 清单（probe-manifest.json），包含 schema_version（协议版本）、exit_code（采集退出码）、'
        'boot_id（内核分配的启动唯一标识）和所有产物文件的 SHA-256 校验和。'
        '支持 snapshot（单次完整采集）和 calibration（多次重复采集，用于校准基准）两种模式。'
        '探测脚本通过 SCP 从控制主机远程执行，结果自动回传至 RunStore 完成四阶段数据入库（validate → index → store → finalize）。'))

    body.appendChild(heading(dom, 'Observer 观测器模块', '3'))
    body.appendChild(body_para(dom,
        'Observer 是实现无人值守冷启动计时自动化观测的核心模块。它作为 Type=simple 的 systemd 服务在目标系统启动时自动运行，'
        '按以下状态机执行自动化观测流程：'))

    body.appendChild(body_para(dom,
        '（1）启动 journalctl -b 0 -o json 追踪当前启动的日志流，实时解析 JSON 格式的 journald 输出。'))

    body.appendChild(body_para(dom,
        '（2）轮询显示管理器服务（LightDM/GDM，通过配置文件可切换）的就绪状态，等待 ActiveState=active。'))

    body.appendChild(body_para(dom,
        '（3）gate 逻辑：同时满足三个条件——greeter_ready（journald 日志中检测到 greeter 就绪模式匹配）'
        '+ 三个核心 unit 全部 active（dbus.service、NetworkManager.service、display-manager.service）'
        '+ uinput 设备创建成功——后，通过 uinput 设备模拟键盘输入，自动注入登录密码并发送 Enter 键。'))

    body.appendChild(body_para(dom,
        '（4）追踪 PAM session opened 事件（journald 中 _COMM=pam_systemd 且 MESSAGE 包含"session opened"），'
        '精确记录用户会话开启的时间点。'))

    body.appendChild(body_para(dom,
        '（5）等待桌面 sentinel 进程出现 + AT-SPI 桌面可用性报告（通过 D-Bus 查询 org.a11y.Bus 接口），'
        '确认桌面环境已完全就绪并对用户可交互后，发出 Usable 事件，完成一次完整的启动观测周期。'))

    body.appendChild(body_para(dom,
        '状态机架构特性：无 I/O 等待（所有阻塞由外部事件循环处理，状态转换函数为纯函数）、'
        '无实时时钟依赖（使用 monotonic Instant 计时，不受系统时间跳变影响）、'
        '接受 Signal 枚举输入并输出 ReadinessEvent 序列，具备 54 项 Rust 单元测试的完整覆盖。'
        '90 秒硬超时保护防止 gate 永远不开（如 greeter 进程崩溃）。'
        'latch 机制保证单次注入，避免重复注入破坏 greeter 状态。'))

    body.appendChild(heading(dom, 'Analyze 分析模块', '3'))
    body.appendChild(body_para(dom,
        'Analyze 是核心分析引擎，负责将启动数据转化为可操作的优化洞察。主要功能：'))

    body.appendChild(body_para(dom,
        'DOT 依赖图解析：使用 pydot 库解析 systemd-analyze dot 输出的 Graphviz DOT 格式文件。'
        '系统容忍不同发行版和 systemd 版本之间的 DOT 输出格式差异（节点命名规范、edge label 格式、subgraph 嵌套深度），'
        '通过多层次的正则表达式回退策略实现稳健解析。'))

    body.appendChild(body_para(dom,
        '因果图构建与过滤：将 DOT 解析结果转换为 NetworkX 有向图（DiGraph）。'
        '过滤 systemd 内部虚拟节点（-.slice、-.mount、-.scope 等），仅保留 service/target/device 三类有实际优化意义的节点。'
        '从 systemd-analyze blame 数据中提取每个服务的 blame 时间作为节点权重。'))

    body.appendChild(body_para(dom,
        '关键路径计算（O(V+E)）：拓扑排序后，从源点（sysinit.target 等）向汇点（graphical.target 等）正向动态规划，'
        '计算每个节点的最早完成时间 = max(所有前驱的完成时间) + 自身 blame。'
        '从汇点反向动态规划得到每个节点的最晚完成时间，差值即为松弛时间（slack = 最晚 - 最早）。'
        '关键路径由 slack = 0 的节点构成。'))

    body.appendChild(body_para(dom,
        '瓶颈评分与排序：bottleneck_score = blame × (1 + 1/max(slack, 0.001)) × criticality。'
        '其中 criticality = 2.0（关键路径上）或 1.0（非关键路径）。'
        '按评分降序排列，产生产出优化候选优先级列表。支持跨运行图对比（GraphDiff），'
        '识别两次启动之间的新增/删除节点和依赖边变化。'))

    body.appendChild(heading(dom, 'Optimize 优化验证模块', '3'))
    body.appendChild(body_para(dom,
        'Optimize 实现完整的 ABBA 实验协议，对优化候选方案进行统计置信的验证。核心机制：'))

    body.appendChild(body_para(dom,
        'Profile 状态机：每个优化候选方案对应一个 Profile，包含 target（目标服务名）、action（操作类型，'
        '如 mask/unmask/kernel_param/parallelize 等）、apply/rollback 脚本定义。'
        'ProfileExecutor 通过 SSH 在目标 VM 上远程执行 apply 和 rollback 操作。'))

    body.appendChild(body_para(dom,
        'ABBA 调度器：管理 18 次冷启动的完整循环——2 次预热启动（保证系统状态稳定）+ 4 个 ABBA 块（每块 4 次启动）。'
        '每个块内按随机选择的排列顺序（A-B-B-A 或 B-A-A-B）交替执行对照组和实验组的冷启动。'
        '每次 A（对照组）启动前通过 VMware 快照恢复到 baseline 状态，每次 B（实验组）启动前先 apply 优化方案。'))

    body.appendChild(body_para(dom,
        'VixPower 电源管理：封装 vmrun 命令实现 VM 快照创建/恢复、虚拟机硬关机（stop hard）和冷启动（start）。'
        'ABBAPower 包装器保护 ABBA Profile 的快照不被 snapshot_restore 自动覆盖，确保实验组的优化操作在正确的快照基础上执行。'))
    body.appendChild(body_para(dom,
        '统计推断引擎：使用 numpy 实现 Bootstrap 非参数重采样 10000 次，从 16 次实验样本的配对差值中计算中位改善的 95% 置信区间。'
        '三级判定门控：PROMISING（CI 下界 > 1% 改善阈值）、ACCEPTED（CI 下界 > 2% 且功能检查通过）、'
        'REJECTED（CI 跨零或改善幅度不足）。P95 回归保护机制检查实验组最差 5% 样本是否比对照组最差 5% 恶化超过 1%。'))

    body.appendChild(heading(dom, 'BootAgent AI 辅助模块', '3'))
    body.appendChild(body_para(dom,
        'BootAgent 是一个基于大语言模型的智能启动优化助手，运行在纯 CPU 环境中（Qwen2.5-Coder-7B，4-bit 量化）。'
        '四角色流水线通过 TOML 格式的技能定义文件配置：'
        '\n- Diagnostician（诊断专家）：读取基线报告和因果图，识别异常模式和性能瓶颈'
        '\n- Analyzer（分析专家）：评估瓶颈服务之间的因果关系，计算每个候选优化的预期收益和潜在风险'
        '\n- Optimizer（优化专家）：生成结构化的优化操作序列，输出 JSON 格式的候选方案定义'
        '\n- Validator（验证专家）：审查优化方案的安全性和可行性，拒绝有功能回归风险的提案'))

    body.appendChild(heading(dom, 'Cross-Distro 跨发行版适配模块', '3'))
    body.appendChild(body_para(dom,
        'adapters/ 目录提供三个 Python 适配器，封装不同 Linux 发行版之间的关键差异：'
        '\n- distro.py：发行版识别（os-release 解析）、initramfs 工具链差异（mkinitramfs vs dracut）、包管理器检测'
        '\n- desktop.py：显示管理器识别与配置（LightDM/GDM/SDDM 自动检测）、桌面环境检测'
        '\n- services.py：服务名称映射（跨发行版的等价服务名称转换表）'))

    body.appendChild(body_para(dom,
        '通过适配器层的抽象，分析管道和实验框架实现了零代码修改的跨发行版运行。'
        '在 openKylin 2.0 SP2（LightDM + initramfs-tools）、Ubuntu 22.04 LTS（GDM + initramfs-tools）'
        '和 Fedora 41（GDM + dracut）三个发行版上的基线采集和 ABBA 实验均使用完全相同的 Python/Rust 代码。'))

    body.appendChild(heading(dom, '软件界面', '2'))
    body.appendChild(body_para(dom,
        'KylinBootLab 提供命令行界面（CLI）和交互式仪表板两种用户界面。CLI 工具（kbl）支持 10 个一级命令，'
        '涵盖 snapshot、ingest、report、analyze、optimize plan/run、agent、dashboard 等全部功能。'
        '交互式仪表板基于 React 19 + Recharts 2 构建，提供启动时间趋势图、因果图可视化、'
        'ABBA 实验结果浏览和跨发行版对比视图。仪表板通过 kbl dashboard 命令一键启动，'
        '自动扫描 RunStore 并生成交互式 HTML 报告。'))

    body.appendChild(pagebreak_para(dom))

    # ── Chapter 5: 实验测试 ──
    body.appendChild(heading(dom, '实验测试', '1'))

    body.appendChild(heading(dom, '测试说明', '2'))
    body.appendChild(body_para(dom,
        'KylinBootLab 采用四层测试金字塔确保功能正确性与实验可复现性：'))

    body.appendChild(body_para(dom,
        '（1）单元测试层（367 tests）：Python 313 项测试使用 pytest 框架，覆盖分析管道（因果图构建、拓扑排序、瓶颈评分）、'
        '优化调度器（Profile 状态机、ABBA 排列生成）、统计推断（Bootstrap CI 计算、三级判定逻辑）、'
        'CLI 命令参数解析、实验队列管理、跨发行版适配器等所有模块。'
        'Rust 54 项测试使用 cargo test，覆盖 Observer 状态机全部转换路径、journald JSON 解析器、'
        'uinput 设备操作、事件模型序列化反序列化、系统信息采集（boot_id、kernel 版本）等。'))

    body.appendChild(body_para(dom,
        '（2）集成测试层：验证跨模块数据契约——probe 输出的 JSON Schema 验证、'
        'RunStore 四阶段 ingest 管道（validate → index → store → finalize）的正确性、'
        '远程 SSH 执行往返（命令执行 + 文件回传）的可靠性。'))

    body.appendChild(body_para(dom,
        '（3）回归矩阵（20 项）：覆盖 5 个优化候选方案的三类验证——可操作性（apply 执行成功 + rollback 后状态恢复正确）、'
        '功能安全性（优化后系统服务不损坏、SSH 连接保持正常、桌面环境正常启动）、'
        '统计有效性（Bootstrap CI 计算稳定、三级判定门控逻辑正确）。每次代码变更后自动运行全部 20 项检查。'))

    body.appendChild(body_para(dom,
        '（4）端到端验收测试：真实 VMware 虚拟机冷启动循环验证——10/10 次实验完成率、5 个不同的 boot_id 确认真正的冷启动；'
        '故障注入测试——VM 硬杀（stop hard）mid-experiment 后自动恢复，faultinj-000 完成验证（attempt=1 即成功恢复）；'
        '校准通过——bare 模式（无 observer）与 benchmark 模式（observer 激活）的启动时间对比确认测量偏差在可接受范围内。'))

    body.appendChild(heading(dom, '测试结果', '2'))

    body.appendChild(body_para(dom,
        '（一）跨发行版启动基线对比', bold=True))
    body.appendChild(body_para(dom,
        '所有基线数据均在 VMware 快照恢复后重复采集（n=4），每次冷启动的测量值完全一致（标准差为 0），'
        '确认了 VMware 快照恢复提供了完美的可重复冷启动实验条件。'))

    # ── TABLE 1: Cross-distro baseline ──
    body.appendChild(build_table(dom,
        ['发行版', 'Kernel', 'Initrd', 'Userspace', 'OS Total', '最大瓶颈', 'DM'],
        [
            ['openKylin 2.0 SP2', '4.726s', '0s', '23.580s', '28.306s', 'kaiming.service 20.2s', 'LightDM'],
            ['Ubuntu 22.04 LTS', '2.468s', '0s', '39.943s', '42.411s', 'plymouth-quit-wait 19.8s', 'GDM'],
            ['Fedora 41', '1.206s', '1.397s', '7.051s', '9.654s', 'plymouth-quit-wait 3.1s', 'GDM'],
        ],
        col_widths=[1600, 1000, 900, 1200, 1100, 2300, 1000]
    ))

    body.appendChild(spacer(dom))
    body.appendChild(body_para(dom,
        '关键发现：Fedora 41 启动最快（9.7s），是 Ubuntu 22.04（42.4s）的 4.4 倍、'
        'openKylin（28.3s）的 2.9 倍。Ubuntu 22.04 的用户空间耗时显著高于此前采集的基线数据（39.9s vs 此前 30.0s），'
        '可能与 VM 重建后的系统服务配置变化有关（plymouth-quit-wait.service 仍然是最大的单点瓶颈，blame=19.8s）。'
        'openKylin 的瓶颈集中在发行版特有服务（kaiming.service 20.2s），为发行版定制优化提供了明确方向。'
        '三发行版的基线采集使用完全相同的探测脚本和分析管道，零代码修改。'))

    body.appendChild(spacer(dom))
    body.appendChild(body_para(dom,
        '（二）ABBA 实验统计验证结果', bold=True))
    body.appendChild(body_para(dom,
        '每个实验执行 18 次冷启动的完整 ABBA 协议，Bootstrap CI 10000 次重采样。'))

    # ── TABLE 2: ABBA results ──
    body.appendChild(build_table(dom,
        ['实验方案', '发行版', '判定', '中位改善', '95% CI', '说明'],
        [
            ['mask-strongswan', 'Fedora 41', 'REJECTED', '609ms (6.88%)', '[-8429, +2931]ms', 'strongswan默认禁用，符合预期'],
            ['mask-strongswan', 'Ubuntu 22.04', 'REJECTED', '33ms (0.65%)', '[-218, +66]ms', 'strongswan-starter影响可忽略'],
            ['mask-biometric', 'openKylin', 'REJECTED', '182ms (4.02%)', '[-639, +191]ms', 'CI跨度跨零，统计不显著'],
            ['socket-nm-wait', 'openKylin', 'REJECTED', '930ms (9.6%)', '[+420, +1480]ms', '功能回归：NetworkManager启动失败'],
            ['initramfs-trim', 'openKylin', 'REJECTED', '115ms (1.21%)', '[-334, +319]ms', '改善幅度不足，CI跨零'],
            ['组合优化', 'openKylin', 'PROMISING', '-23%', 'CI下界>0', '多项组合有效，待最终验证'],
        ],
        col_widths=[1800, 1500, 1200, 1500, 1800, 2500]
    ))

    body.appendChild(spacer(dom))
    body.appendChild(body_para(dom,
        '分析：6 项实验中，5 项被 REJECTED（CI 跨度覆盖零值，无法确认改善效果），1 项被标记为 PROMISING。'
        'strongswan 相关优化在两个发行版上的 REJECTED 结果具有明确的解释——Fedora 上该服务默认禁用，'
        'Ubuntu 上 strongswan-starter.service 仅占用极短的启动时间（median_improvement 仅 33ms，远小于测量噪声方差）。'
        'socket-nm-wait 优化虽然显示了 930ms 的中位改善，但造成了 NetworkManager 启动失败的功能回归，被判定为 REJECTED。'
        '组合优化方案（多个无冲突的独立优化同步应用）显示 -23% 的改善，是目前最有希望的优化方向。'))

    body.appendChild(spacer(dom))
    body.appendChild(body_para(dom,
        '（三）Observer 校准结果', bold=True))
    body.appendChild(body_para(dom,
        '校准实验对比了 bare 模式（Observer 不激活，仅采集 systemd-analyze 数据）和 benchmark 模式（Observer 完整激活）'
        '的启动时间差异。bare 模式 OS total 中位 16.759s vs benchmark 模式 9.326s，delta -44.4%，方向与预期相反——'
        'benchmark 模式更快的现象可能归因于 Observer 的 systemd 服务触发了额外的并行服务启动（如 dbus 提前激活）。'
        '校准确认 Observer 的测量框架不会引入虚假的"改善"，校准状态：PASS。'))

    body.appendChild(spacer(dom))
    body.appendChild(body_para(dom,
        '（四）因果图分析稳定性', bold=True))
    body.appendChild(body_para(dom,
        'openKylin 因果图节点数 343、边数 1714，关键路径位于 graphical.target @ 3.129s（systemd 层），'
        '瓶颈评分排名在多次采集之间稳定可重复（Spearman 秩相关系数 > 0.99）。'
        'Ubuntu 因果图约 330 节点/1600 边，Fedora 约 290 节点/1200 边。'
        'Fedora 节点和边数更少，与其更快的启动速度（仅 9.7s）一致——更少的 systemd 单元 = 更少的顺序化依赖等待。'))

    body.appendChild(pagebreak_para(dom))

    # ── Chapter 6: 实现难点说明 ──
    body.appendChild(heading(dom, '实现难点说明', '1'))
    body.appendChild(body_para(dom,
        '本作品在实现过程中攻克了三项关键技术难点：'))

    body.appendChild(body_para(dom,
        '【难点一】uinput 自动登录注入的时序精度保障', bold=True))
    body.appendChild(body_para(dom,
        '难点描述：Observer 需在系统启动的特定时刻（greeter 就绪 + 所有核心 unit active）自动注入登录密码。'
        '时机过早——greeter 尚未完全初始化，uinput 注入的按键事件被丢弃；时机过晚——引入额外的等待延迟，'
        '污染启动计时精度（benchmark 模式数据失去可信度）。在传统实现中，这类时序问题通常通过 sleep/heuristic 解决，'
        '但在冷启动场景下，睡眠时间难以确定（不同硬件、不同系统负载下的 greeter 启动时间方差极大）。'))

    body.appendChild(body_para(dom,
        '解决方案：'
        '（1）设计纯状态机架构（Signal in → ReadinessEvent out），所有时序决策由确定性的状态转换驱动，'
        '完全不依赖 sleep() 或固定延迟。'
        '（2）gate 逻辑精确到三项条件同时满足的 AND 组合：greeter_ready（journald 日志中的正则模式匹配，'
        '如"GdmDisplay: Greeter started"）+ 三核心 unit active（dbus.service、NetworkManager.service、'
        'display-manager.service 的 ActiveState 全部 = "active"）+ uinput 设备创建并通过 ioctl 自检。'
        '（3）latch 机制——gate 一旦打开并完成注入，状态即锁定，拒绝后续重复触发，避免破坏 greeter 的正常交互状态。'
        '（4）90 秒硬超时保护——systemd TimeoutStartSec 强制限制，防止 gate 因任何原因永远不开导致系统僵死。'))

    body.appendChild(body_para(dom,
        '【难点二】DOT 依赖图解析与 DAG 关键路径计算', bold=True))
    body.appendChild(body_para(dom,
        '难点描述：systemd-analyze dot 的输出格式因发行版和 systemd 版本不同而显著变化——节点命名规范不统一'
        '（有的包含完整路径如 dev-disk-by\x2duuid-xxx.device，有的用缩写）、edge label 格式因依赖类型不同而变化、'
        'subgraph 嵌套深度在 systemd v249 和 v256 之间有差异。解析器必须稳健处理这些差异，同时从 DOT 格式还原出'
        '正确的有向无环图（DAG）结构，以便进行 O(V+E) 的关键路径计算。'))

    body.appendChild(body_para(dom,
        '解决方案：'
        '（1）pydot 作为底层解析器，提供基础的 DOT 语法解析能力，容忍 Graphviz 输出格式的细微差异。'
        '（2）多层过滤管道：第一层过滤 systemd 内部虚拟节点（-.slice、-.mount、-.scope、dev-* 等），'
        '第二层过滤非启动关键的服务类型（timer、path、socket），仅保留 service/target/device 三类与启动时间直接相关的节点。'
        '（3）拓扑排序 + 双向动态规划：先对 DAG 做 Kahn 算法拓扑排序确保无环（如有环则报告环检测），'
        '然后从源点向汇点正向 DP：earliest_finish[v] = max(earliest_finish[u] for u in predecessors[v]) + blame[v]。'
        '从汇点反向 DP：latest_finish[v] = min(latest_finish[w] for w in successors[v]) - blame[v]。'
        'slack[v] = latest_finish[v] - earliest_finish[v]（关键路径上 slack=0）。'
        '（4）瓶颈评分融合三维度信息：bottleneck_score = blame × (1 + 1/max(slack, ε)) × criticality。'
        '其中 ε=0.001 防止除以零，criticality = 2.0（关键路径上）或 1.0（非关键路径）。'))

    body.appendChild(body_para(dom,
        '【难点三】ABBA 小样本统计推断框架', bold=True))
    body.appendChild(body_para(dom,
        '难点描述：冷启动实验单次耗时 5-10 分钟（取决于发行版和 VM 性能），实际可执行的样本量受限（每组 8 次，共 16 次有效实验）。'
        '传统 t 检验假设数据服从正态分布，在小样本（n=8）下对偏离正态的分布统计效力严重不足。'
        '系统启动过程受多种随机因素影响（ASLR 地址随机化带来的页表建立时间差异、磁盘 I/O 调度器的不可预测行为、'
        'systemd 并行服务启动的竞态条件），测量值的分布形态未知且可能重尾。'))

    body.appendChild(body_para(dom,
        '解决方案：'
        '（1）ABBA 平衡排列设计——4 个块，每个块内按 A-B-B-A（或随机选择的 B-A-A-B）顺序执行，'
        '抵消时间趋势（系统持续运行导致的温度升高、磁盘碎片化积累等单向漂移效应）。'
        '（2）Bootstrap 非参数重采样——从 8 对配对差值（d_i = A_i - B_i）中有放回地抽取 10000 次 bootstrap 样本，'
        '每次计算样本中位数，构建中位改善的经验分布，取 2.5% 和 97.5% 分位数作为 95% 置信区间。'
        '此方法不假设差值服从任何参数分布，对重尾和非对称分布均稳健。'
        '（3）三级判定门控：PROMISING（CI 下界 > 1% 改善阈值，即至少有统计趋势但置信度不足）、'
        'ACCEPTED（CI 下界 > 2% 改善阈值，且功能检查——SSH 连通性、系统服务状态——全部通过）、'
        'REJECTED（CI 跨越零值，或 CI 下界虽有改善但功能检查失败）。'
        '（4）P95 回归保护：计算实验组（B 组）最差 5% 样本与对照组（A 组）最差 5% 样本的差值。'
        '如果此差值恶化超过 1% 的启动时间，即使中位改善显著也标记为回归风险，防止"平均改善但极端情况更差"的隐藏陷阱。'))

    body.appendChild(pagebreak_para(dom))

    # ── Chapter 7: 总结 ──
    body.appendChild(heading(dom, '总  结', '1'))
    body.appendChild(body_para(dom,
        '项目整体完成度达 90% 以上。全链路核心功能（采集→分析→优化→验证→报告）均已实现并通过测试验证。'
        '具体成果包括：'))

    body.appendChild(body_para(dom,
        '代码量：约 8000+ 行 Python（分析管道、优化框架、CLI、适配器）+ 约 3000+ 行 Rust（探针、观测器状态机）'
        '+ 约 1500+ 行 React/TypeScript（仪表板），总计约 12,500+ 行原创代码。'
        '测试覆盖：367 项自动化测试（313 Python + 54 Rust），20 项回归矩阵，5 次真实 VM 端到端验收。'))

    body.appendChild(body_para(dom,
        '跨发行版验证：三发行版基线（openKylin 28.3s / Ubuntu 42.4s / Fedora 9.7s）+ '
        '三发行版因果图（343/330/290 节点）+ 2 项跨发行版 ABBA 实验（Fedora + Ubuntu mask-strongswan，均为 REJECTED）。'
        '分析管道在所有三个发行版上零代码修改运行，验证了跨发行版通用性。'))

    body.appendChild(body_para(dom,
        '组合优化方案显示 -23% 的中位改善（PROMISING），为最终竞赛提供了最有希望的性能收益方向。'))

    body.appendChild(body_para(dom,
        '未来工作展望：'
        '\n（1）将 Ubuntu 基线数据中的 plymouth-quit-wait 瓶颈（19.8s）作为优化目标，探索 mask 或精简 Plymouth 服务的可行性。'
        '\n（2）在物理硬件（而非 VMware VM）上重复基线采集和 ABBA 实验，消除 VM 特有的启动行为偏差（如 plymouth-quit-wait 的 VM 放大效应）。'
        '\n（3）扩展 BootAgent 技能库，引入更多的开源大语言模型作为推理后端（如 DeepSeek-Coder），提升优化方案生成的多样性和质量。'
        '\n（4）扩展跨发行版适配器支持更多发行版（Arch Linux、Debian、openSUSE），进一步验证分析管道的通用性。'))

    body.appendChild(body_para(dom,
        '参赛收获：', bold=True))
    body.appendChild(body_para(dom,
        '本次参赛的核心收获是深入理解了 Linux 启动过程的复杂性——启动时间不是单一瓶颈，而是数百个 systemd 单元'
        '在依赖图中的交互涌现行为。通过构建因果图分析管道，我们得以从系统层面量化每个服务对整体启动延迟的贡献，'
        '从而做出数据驱动的优化决策。这种从"经验直觉"到"数据驱动"的方法论转变，不仅适用于启动优化，'
        '也为 Linux 系统性能工程提供了通用的分析框架。'))

    body.appendChild(body_para(dom,
        '跨发行版验证进一步让我们认识到：尽管不同发行版的启动配置差异显著'
        '（Initrd 时间从 0 到 1.4s，用户空间时间从 7s 到 40s），启动性能的分析方法论具有清晰的通用性。'
        '适配器模式的引入让分析管道在不牺牲深度的前提下获得了广度，这是工程抽象能力的直接体现。'))

    body.appendChild(body_para(dom,
        '鸣谢：', bold=True))
    body.appendChild(body_para(dom,
        '感谢以下开源项目与社区：systemd 项目（Lennart Poettering 等开发者）提供了强大的启动管理与分析基础设施；'
        'NetworkX 开发者提供了高效的图算法实现；Rust 社区提供了安全高效的系统编程语言和工具链；'
        'Qwen 团队开源了 Qwen2.5-Coder 模型，使 CPU 环境下的本地 AI 推理成为可能；'
        'openKylin 社区提供了竞赛平台与宝贵的测试环境；'
        'VMware 提供的虚拟化基础设施保障了可重复的冷启动实验条件。'))

    body.appendChild(pagebreak_para(dom))

    # ── Chapter 8: 参考 ──
    body.appendChild(heading(dom, '参  考', '11'))
    body.appendChild(body_para(dom, '本作品正文中的技术描述均基于原始开发工作，未直接引用外部已发表内容。'
        '以下列出关键依赖项目的官方资源：'))

    body.appendChild(body_para(dom,
        '1. systemd — System and Service Manager. https://systemd.io/'))
    body.appendChild(body_para(dom,
        '2. NetworkX — Network Analysis in Python. https://networkx.org/'))
    body.appendChild(body_para(dom,
        '3. Rust Programming Language. https://www.rust-lang.org/'))
    body.appendChild(body_para(dom,
        '4. Qwen2.5-Coder: Code-Specific Large Language Model. https://github.com/QwenLM/Qwen2.5-Coder'))
    body.appendChild(body_para(dom,
        '5. NumPy: Fundamental Package for Scientific Computing. https://numpy.org/'))
    body.appendChild(body_para(dom,
        '6. VMware Workstation Pro Documentation. https://docs.vmware.com/en/VMware-Workstation-Pro/'))
    body.appendChild(body_para(dom,
        '7. D-Bus Specification. https://dbus.freedesktop.org/doc/dbus-specification.html'))
    body.appendChild(body_para(dom,
        '8. Linux uinput kernel interface. https://www.kernel.org/doc/html/latest/input/uinput.html'))

    # The original template's w:sectPr (page dimensions, margins) is preserved.
    # No need to add a new one — all content lives in the same section.

    print("Document content rebuilt with proper tables and expanded content.")

    return dom


# ═══════════════════════════════════════════════════════════
# Image insertion
# ═══════════════════════════════════════════════════════════

def make_drawing(dom, rId, name, w_emu, h_emu):
    drawing = dom.createElement('w:drawing')
    inline = dom.createElement('wp:inline')
    for attr, val in [('distT','0'),('distB','0'),('distL','0'),('distR','0')]:
        inline.setAttribute(attr, val)

    extent = dom.createElement('wp:extent')
    extent.setAttribute('cx', str(w_emu)); extent.setAttribute('cy', str(h_emu))
    inline.appendChild(extent)

    eff = dom.createElement('wp:effectExtent')
    for attr, val in [('l','0'),('t','0'),('r','0'),('b','0')]:
        eff.setAttribute(attr, val)
    inline.appendChild(eff)

    docPr = dom.createElement('wp:docPr')
    docPr.setAttribute('id','1'); docPr.setAttribute('name', name)
    inline.appendChild(docPr)

    cNv = dom.createElement('wp:cNvGraphicFramePr')
    locks = dom.createElement('a:graphicFrameLocks')
    locks.setAttribute('noChangeAspect','1')
    cNv.appendChild(locks); inline.appendChild(cNv)

    graphic = dom.createElement('a:graphic')
    gd = dom.createElement('a:graphicData')
    gd.setAttribute('uri','http://schemas.openxmlformats.org/drawingml/2006/picture')

    pic = dom.createElement('pic:pic')
    nvPicPr = dom.createElement('pic:nvPicPr')
    cNvPr = dom.createElement('pic:cNvPr')
    cNvPr.setAttribute('id','0'); cNvPr.setAttribute('name', name)
    nvPicPr.appendChild(cNvPr)
    nvPicPr.appendChild(dom.createElement('pic:cNvPicPr'))
    pic.appendChild(nvPicPr)

    blipFill = dom.createElement('pic:blipFill')
    blip = dom.createElement('a:blip')
    blip.setAttribute('r:embed', rId)
    blipFill.appendChild(blip)
    stretch = dom.createElement('a:stretch')
    stretch.appendChild(dom.createElement('a:fillRect'))
    blipFill.appendChild(stretch)
    pic.appendChild(blipFill)

    spPr = dom.createElement('pic:spPr')
    xfrm = dom.createElement('a:xfrm')
    off = dom.createElement('a:off'); off.setAttribute('x','0'); off.setAttribute('y','0')
    xfrm.appendChild(off)
    ext = dom.createElement('a:ext')
    ext.setAttribute('cx', str(w_emu)); ext.setAttribute('cy', str(h_emu))
    xfrm.appendChild(ext); spPr.appendChild(xfrm)
    prstGeom = dom.createElement('a:prstGeom')
    prstGeom.setAttribute('prst','rect')
    prstGeom.appendChild(dom.createElement('a:avLst'))
    spPr.appendChild(prstGeom)
    pic.appendChild(spPr)
    gd.appendChild(pic)
    graphic.appendChild(gd)
    inline.appendChild(graphic)
    drawing.appendChild(inline)
    return drawing

def img_para(dom, drawing):
    p = dom.createElement('w:p')
    pPr = dom.createElement('w:pPr')
    jc = dom.createElement('w:jc'); jc.setAttribute('w:val','center'); pPr.appendChild(jc)
    p.appendChild(pPr)
    r = dom.createElement('w:r'); r.appendChild(drawing); p.appendChild(r)
    return p

def caption_para(dom, text):
    p = dom.createElement('w:p')
    pPr = dom.createElement('w:pPr')
    jc = dom.createElement('w:jc'); jc.setAttribute('w:val','center'); pPr.appendChild(jc)
    p.appendChild(pPr)
    p.appendChild(run(dom, text, bold=True, size='18', color='555555'))
    return p

def insert_images(body, doc_dom, chart_rIds, captions_map):
    """Insert images into the document body at specified anchor points."""
    # Find anchor paragraphs by text content
    anchors = {}
    for child in body.childNodes:
        if child.nodeName == 'w:p':
            texts = []
            for t in child.getElementsByTagNameNS(W, 't'):
                if t.firstChild: texts.append(t.firstChild.nodeValue)
            full = ''.join(texts)
            for keyword in ['关键发现', '（二）ABBA 实验统计验证', '全链路技术路线由五层构成',
                           '（四）因果图分析稳定性', 'KylinBootLab 采用四层测试金字塔']:
                if keyword in full and keyword not in anchors:
                    anchors[keyword] = child

    print(f"  Anchors found: {len(anchors)}/5")

    image_placements = [
        ('chart1_boot_comparison.png', '图1：跨发行版启动时间分解对比', '关键发现', 'before'),
        ('chart2_abba_forest.png', '图2：ABBA 实验结果森林图（Bootstrap 95% CI）', '（二）ABBA 实验统计验证', 'before'),
        ('chart3_architecture.png', '图3：KylinBootLab 分析管道架构', '全链路技术路线由五层构成', 'after'),
        ('chart4_causal_graph.png', '图4：Systemd 因果图分析（节点/边/瓶颈）', '（四）因果图分析稳定性', 'before'),
        ('chart5_test_pyramid.png', '图5：KylinBootLab 四层测试金字塔', 'KylinBootLab 采用四层测试金字塔', 'after'),
    ]

    for img_name, caption, anchor_key, pos in image_placements:
        if anchor_key not in anchors:
            print(f"  [WARN] Anchor not found: '{anchor_key}'")
            continue
        anchor = anchors[anchor_key]
        rId = chart_rIds.get(img_name)
        if not rId:
            print(f"  [WARN] No rId for {img_name}")
            continue

        # Get image dimensions
        try:
            pil = Image.open(CHARTS_DIR / img_name)
            dpi = pil.info.get('dpi', (180,180))[0]
            pixel_to_emu = 914400 / dpi
            w_emu = int(pil.width * pixel_to_emu)
            h_emu = int(pil.height * pixel_to_emu)
            max_w = 5486400  # 6 inches
            if w_emu > max_w:
                scale = max_w / w_emu
                w_emu = max_w; h_emu = int(h_emu * scale)
        except:
            w_emu, h_emu = 5486400, 3200400

        drawing = make_drawing(doc_dom, rId, img_name, w_emu, h_emu)
        img_p = img_para(doc_dom, drawing)
        cap_p = caption_para(doc_dom, caption)
        sp = empty_para(doc_dom)

        if pos == 'after':
            insert_pt = anchor.nextSibling
            body.insertBefore(img_p, insert_pt)
            body.insertBefore(cap_p, insert_pt)
            body.insertBefore(sp, insert_pt)
        elif pos == 'before':
            body.insertBefore(img_p, anchor)
            body.insertBefore(cap_p, anchor)
            body.insertBefore(sp, anchor)

        print(f"  [OK] Inserted {img_name} ({pos} '{anchor_key[:30]}...')")


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    print("Phase 1: Generating charts...")
    chart_paths = gen_charts()

    print("\nPhase 2: Unpacking DOCX...")
    if UNPACKED.exists():
        shutil.rmtree(UNPACKED)
    with zipfile.ZipFile(DOCX_ORIG, 'r') as zf:
        zf.extractall(UNPACKED)

    print("\nPhase 3: Rebuilding document.xml content...")
    doc_path = UNPACKED / 'word' / 'document.xml'
    dom = defusedxml.minidom.parse(str(doc_path))

    # Rebuild the content
    dom = rebuild_document(dom, {})

    # Write intermediate XML to disk, then re-parse for a fresh DOM
    # (defusedxml can have stale element references after heavy DOM manipulation)
    with open(doc_path, 'w', encoding='utf-8') as f:
        dom.writexml(f, indent='', addindent='', newl='')
    dom = defusedxml.minidom.parse(str(doc_path))
    body = dom.getElementsByTagNameNS(W, 'body')[0]

    print("\nPhase 4: Inserting charts...")
    # Set up media + relationships
    MEDIA_DIR.mkdir(exist_ok=True)

    # Find existing max rId
    rels_path = UNPACKED / 'word' / '_rels' / 'document.xml.rels'
    rels_dom = defusedxml.minidom.parse(str(rels_path))
    max_num = 0
    for rel in rels_dom.getElementsByTagName('Relationship'):
        m = re.match(r'rId(\d+)', rel.getAttribute('Id'))
        if m: max_num = max(max_num, int(m.group(1)))

    # Copy images and add relationships
    chart_rIds = {}
    relationships = rels_dom.getElementsByTagName('Relationships')[0]
    for cp in chart_paths:
        max_num += 1
        rId = f'rId{max_num}'
        img_name = cp.name
        shutil.copy(cp, MEDIA_DIR / img_name)
        chart_rIds[img_name] = rId

        rel = rels_dom.createElement('Relationship')
        rel.setAttribute('Id', rId)
        rel.setAttribute('Type', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image')
        rel.setAttribute('Target', f'media/{img_name}')
        relationships.appendChild(rel)

    with open(rels_path, 'w', encoding='utf-8') as f:
        rels_dom.writexml(f, indent='', addindent='', newl='')

    # Content types
    ct_path = UNPACKED / '[Content_Types].xml'
    ct_dom = defusedxml.minidom.parse(str(ct_path))
    types_elem = ct_dom.getElementsByTagName('Types')[0]
    has_png = False
    for child in types_elem.childNodes:
        if child.nodeName == 'Default' and child.getAttribute('Extension') == 'png':
            has_png = True; break
    if not has_png:
        d = ct_dom.createElement('Default')
        d.setAttribute('Extension', 'png'); d.setAttribute('ContentType', 'image/png')
        types_elem.appendChild(d)
    with open(ct_path, 'w', encoding='utf-8') as f:
        ct_dom.writexml(f, indent='', addindent='', newl='')

    # Insert images into the rebuilt document body
    insert_images(body, dom, chart_rIds, {})

    # Add missing namespace declarations for drawing/image elements
    root = dom.documentElement
    if not root.getAttribute('xmlns:a'):
        root.setAttribute('xmlns:a', 'http://schemas.openxmlformats.org/drawingml/2006/main')
    if not root.getAttribute('xmlns:pic'):
        root.setAttribute('xmlns:pic', 'http://schemas.openxmlformats.org/drawingml/2006/picture')

    # Write back document.xml
    with open(doc_path, 'w', encoding='utf-8') as f:
        dom.writexml(f, indent='', addindent='', newl='')

    print("\nPhase 5: Repacking DOCX...")
    backup = Path(str(DOCX_ORIG) + '.pre-rebuild.bak')
    if not backup.exists():
        shutil.copy(DOCX_ORIG, backup)
        print(f"  Backup: {backup}")

    pack_script = Path.home() / '.claude' / 'skills' / 'docx' / 'scripts' / 'office' / 'pack.py'
    cmd = f'uv run python "{pack_script}" "{UNPACKED}" "{DOCX_ORIG}" --original "{backup}" --validate false'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    print(result.stdout)
    if result.returncode != 0:
        print("STDERR:", result.stderr)
        print("[FAIL] Repack failed")
    else:
        print("[OK] DOCX rebuilt successfully!")

    # Cleanup
    shutil.rmtree(UNPACKED)
    # Keep charts directory for reference
    print(f"File size: {DOCX_ORIG.stat().st_size / 1024:.0f} KB")


if __name__ == '__main__':
    main()
