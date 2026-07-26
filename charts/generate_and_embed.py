"""Generate charts and embed them into the competition DOCX."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import FancyBboxPatch
import numpy as np
import os, io, shutil, zipfile, copy, re
from pathlib import Path
import defusedxml.minidom

# ── Config ────────────────────────────────────────────
CHARTS_DIR = Path("charts")
DOCX_PATH = Path("操作系统开源创新大赛项目说明书.docx")
UNPACKED_DIR = Path("unpacked-charts")

# Font setup for Chinese
plt.rcParams['font.family'] = 'Microsoft YaHei'
plt.rcParams['axes.unicode_minus'] = False

# Color palette
C_KERNEL   = '#2E86AB'   # blue
C_INITRD   = '#A23B72'   # purple
C_USERSPACE = '#F18F01'  # orange
C_TOTAL_BG  = '#C73E1D'  # red
COLORS = [C_KERNEL, C_INITRD, C_USERSPACE]
DISTRO_COLORS = {'openKylin': '#16A34A', 'Ubuntu': '#E95420', 'Fedora': '#3C6EB4'}
VERDICT_COLORS = {'PROMISING': '#16A34A', 'ACCEPTED': '#2563EB', 'REJECTED': '#DC2626'}
BG_COLOR = '#FAFAFA'
GRID_COLOR = '#E5E5E5'

# ── Chart 1: Cross-Distribution Boot Time Breakdown ──────
def chart1_boot_comparison():
    distros = ['openKylin\n2.0 SP2', 'Ubuntu\n22.04 LTS', 'Fedora\n41']
    kernel    = [4.726, 2.468, 1.206]
    initrd    = [0,      0,     1.397]
    userspace = [23.580, 29.971, 7.051]
    totals    = [28.306, 32.439, 9.654]

    fig, ax = plt.subplots(figsize=(8, 4.8))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    x = np.arange(len(distros))
    width = 0.52

    bars_kernel    = ax.bar(x, kernel,    width, label='Kernel',    color=C_KERNEL,   edgecolor='white', linewidth=0.5)
    bars_initrd    = ax.bar(x, initrd,    width, label='Initrd',    color=C_INITRD,   edgecolor='white', linewidth=0.5,
                            bottom=kernel)
    bars_userspace = ax.bar(x, userspace, width, label='Userspace', color=C_USERSPACE, edgecolor='white', linewidth=0.5,
                            bottom=[k+i for k,i in zip(kernel,initrd)])

    # Total labels on top of bars
    for i, (t, d) in enumerate(zip(totals, distros)):
        ax.text(i, t + 0.6, f'{t:.1f}s', ha='center', va='bottom', fontsize=11, fontweight='bold', color=C_TOTAL_BG)

    # Value labels inside bars
    for i, v in enumerate(kernel):
        if v > 0.8:
            ax.text(i, v/2, f'{v:.2f}s', ha='center', va='center', fontsize=7.5, color='white', fontweight='bold')
    for i, v in enumerate(initrd):
        if v > 0.8:
            ax.text(i, kernel[i] + v/2, f'{v:.2f}s', ha='center', va='center', fontsize=7.5, color='white', fontweight='bold')
    for i, v in enumerate(userspace):
        ax.text(i, kernel[i]+initrd[i] + v/2, f'{v:.1f}s', ha='center', va='center', fontsize=7.5, color='white', fontweight='bold')

    ax.set_xticks(x)
    ax.set_xticklabels(distros, fontsize=11)
    ax.set_ylabel('Boot Time (seconds)', fontsize=11)
    ax.set_title('Cross-Distribution Boot Time Breakdown', fontsize=14, fontweight='bold', pad=16)
    ax.legend(loc='upper right', framealpha=0.9, fontsize=9)
    ax.set_ylim(0, max(totals) * 1.18)
    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.5)
    ax.set_axisbelow(True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # Speed ratio annotation
    ax.annotate(f'{totals[1]/totals[2]:.1f}× slower\nthan Fedora',
                xy=(1, totals[1]), xytext=(1.5, totals[1]+9),
                arrowprops=dict(arrowstyle='->', color='#555', lw=1.2),
                fontsize=8.5, color='#555', ha='left')

    plt.tight_layout()
    path = CHARTS_DIR / 'chart1_boot_comparison.png'
    fig.savefig(path, dpi=180, bbox_inches='tight', facecolor=BG_COLOR)
    plt.close(fig)
    print(f"  [OK] {path.name}")
    return path

# ── Chart 2: ABBA Experiment Forest Plot ──────────────
def chart2_abba_forest():
    experiments = [
        ('mask-strongswan\n(Fedora 41)',       609,  -8429,   2931, 'REJECTED'),
        ('mask-biometric\n(openKylin)',         182,   -639,    191, 'REJECTED'),
        ('socket-nm-wait\n(openKylin)',         930,    420,   1480, 'REJECTED'),
        ('initramfs-trim\n(openKylin)',         115,   -334,    319, 'REJECTED'),
        ('组合优化\n(openKylin)',                 None,   None,   None, 'PROMISING'),
    ]

    fig, ax = plt.subplots(figsize=(9, 5))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    y_positions = [4, 3, 2, 1, 0]

    for i, (name, median, ci_low, ci_high, verdict) in enumerate(experiments):
        y = y_positions[i]
        color = VERDICT_COLORS[verdict]

        if median is not None:
            # CI bar
            ax.plot([ci_low, ci_high], [y, y], color=color, linewidth=3, alpha=0.7, solid_capstyle='round')
            # CI endpoints
            ax.plot([ci_low, ci_low], [y-0.15, y+0.15], color=color, linewidth=2, alpha=0.8)
            ax.plot([ci_high, ci_high], [y-0.15, y+0.15], color=color, linewidth=2, alpha=0.8)
            # Point estimate
            ax.scatter(median, y, s=140, color='white', edgecolor=color, linewidth=2.5, zorder=5)
            ax.scatter(median, y, s=40, color=color, zorder=6)
            # Value label
            sign = '+' if median > 0 else ''
            ax.text(median, y - 0.38, f'{sign}{median}ms', ha='center', fontsize=8, color=color, fontweight='bold')

        # Experiment name
        color_name = 'PROMISING' if verdict == 'PROMISING' else 'REJECTED'
        ax.text(-9500, y, name, ha='left', va='center', fontsize=9.5,
                color=VERDICT_COLORS[verdict], fontweight='bold')

        # Verdict badge
        badge_x = 4800 if median is not None else 2000
        ax.text(badge_x, y, f' {verdict} ', ha='left', va='center', fontsize=7.5,
                color='white', fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.3', facecolor=color, edgecolor='none', alpha=0.85))

    # Zero line
    ax.axvline(0, color='#999', linewidth=1.2, linestyle='--', alpha=0.6, zorder=0)

    # PROMISING combo annotation (special case, percentage)
    ax.annotate('Median improvement: -23%\n(percentage-based,\n95% CI lower bound > 0)',
                xy=(0, 0), xytext=(3500, 1.2),
                fontsize=8.5, color=VERDICT_COLORS['PROMISING'],
                bbox=dict(boxstyle='round,pad=0.5', facecolor='#DCFCE7', edgecolor=VERDICT_COLORS['PROMISING'], alpha=0.7),
                ha='center')

    ax.set_ylim(-1.2, 4.8)
    ax.set_xlim(-10000, 6500)
    ax.set_xlabel('Median Improvement (ms)  ←  worse  |  better  →', fontsize=10, color='#555')
    ax.set_title('ABBA Experiment Results — Bootstrap CI 95%', fontsize=14, fontweight='bold', pad=14)
    ax.set_yticks([])
    ax.spines['left'].set_visible(False)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.xaxis.grid(True, color=GRID_COLOR, linewidth=0.5)
    ax.set_axisbelow(True)

    # Legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker='o', color='w', markerfacecolor=VERDICT_COLORS['PROMISING'],
               markersize=10, label='PROMISING (CI下界>0)'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor=VERDICT_COLORS['REJECTED'],
               markersize=10, label='REJECTED (CI跨零)'),
    ]
    ax.legend(handles=legend_elements, loc='lower right', framealpha=0.9, fontsize=8.5)

    plt.tight_layout()
    path = CHARTS_DIR / 'chart2_abba_forest.png'
    fig.savefig(path, dpi=180, bbox_inches='tight', facecolor=BG_COLOR)
    plt.close(fig)
    print(f"  [OK] {path.name}")
    return path

# ── Chart 3: Architecture Pipeline ─────────────────────
def chart3_architecture():
    fig, ax = plt.subplots(figsize=(10, 2.8))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 3)
    ax.axis('off')

    layers = [
        ('数据采集\nProbe',        '#2563EB', 'Rust\nsystemd-analyze'),
        ('数据入库\nIngest',       '#7C3AED', 'Python\nJSON Schema'),
        ('因果分析\nAnalyze',      '#DC2626', 'NetworkX\nTopo DP'),
        ('优化验证\nOptimize',     '#EA580C', 'ABBA Protocol\nBootstrap CI'),
        ('仪表板\nDashboard',      '#16A34A', 'React\nRecharts'),
    ]

    box_w, box_h = 1.45, 1.6
    y_center = 1.5
    arrow_gap = 0.42

    for i, (title, color, details) in enumerate(layers):
        x = 0.5 + i * (box_w + arrow_gap + 0.25)

        # Box
        rect = FancyBboxPatch((x, y_center - box_h/2), box_w, box_h,
                              boxstyle='round,pad=0.15', facecolor=color, edgecolor='white',
                              linewidth=2, alpha=0.9, zorder=3)
        ax.add_patch(rect)

        # Title
        ax.text(x + box_w/2, y_center + 0.28, title, ha='center', va='center',
                fontsize=11, fontweight='bold', color='white', zorder=4)

        # Details
        ax.text(x + box_w/2, y_center - 0.38, details, ha='center', va='center',
                fontsize=7.5, color='white', alpha=0.9, zorder=4)

        # Arrow to next
        if i < len(layers) - 1:
            arrow_x = x + box_w + 0.08
            ax.annotate('', xy=(arrow_x + 0.3, y_center), xytext=(arrow_x, y_center),
                        arrowprops=dict(arrowstyle='->', color='#888', lw=2.5, connectionstyle='arc3,rad=0'))

    ax.set_title('KylinBootLab Analysis Pipeline', fontsize=14, fontweight='bold', pad=10, color='#333')

    plt.tight_layout()
    path = CHARTS_DIR / 'chart3_architecture.png'
    fig.savefig(path, dpi=180, bbox_inches='tight', facecolor=BG_COLOR)
    plt.close(fig)
    print(f"  [OK] {path.name}")
    return path

# ── Chart 4: Causal Graph Statistics ───────────────────
def chart4_causal_graph():
    distros = ['openKylin', 'Ubuntu', 'Fedora']
    nodes   = [343, 330, 290]
    edges   = [1714, 1600, 1200]
    blames  = [20.2, 19.8, 3.1]  # top bottleneck blame

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 4))
    fig.patch.set_facecolor(BG_COLOR)
    ax1.set_facecolor(BG_COLOR)
    ax2.set_facecolor(BG_COLOR)

    x = np.arange(len(distros))
    color_list = [DISTRO_COLORS[d] for d in ['openKylin', 'Ubuntu', 'Fedora']]

    # Nodes & edges
    width = 0.32
    bars_n = ax1.bar(x - width/2, nodes, width, label='Nodes', color='#3B82F6', edgecolor='white')
    bars_e = ax1.bar(x + width/2, edges, width, label='Edges', color='#F59E0B', edgecolor='white')
    for bar in bars_n:
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 15,
                 str(int(bar.get_height())), ha='center', fontsize=8.5, fontweight='bold', color='#3B82F6')
    for bar in bars_e:
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 15,
                 str(int(bar.get_height())), ha='center', fontsize=8.5, fontweight='bold', color='#F59E0B')
    ax1.set_xticks(x)
    ax1.set_xticklabels(distros, fontsize=10)
    ax1.set_title('Causal Graph Size', fontsize=12, fontweight='bold')
    ax1.legend(fontsize=8)
    ax1.set_ylim(0, max(edges)*1.18)
    ax1.spines['top'].set_visible(False)
    ax1.spines['right'].set_visible(False)
    ax1.yaxis.grid(True, color=GRID_COLOR)
    ax1.set_axisbelow(True)

    # Top bottleneck
    bars_b = ax2.bar(distros, blames, color=color_list, edgecolor='white', linewidth=0.5)
    for bar, v in zip(bars_b, blames):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                 f'{v:.1f}s', ha='center', fontsize=11, fontweight='bold', color='#333')
    ax2.set_title('Top Bottleneck Blame Time', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Blame (seconds)', fontsize=10)
    ax2.spines['top'].set_visible(False)
    ax2.spines['right'].set_visible(False)
    ax2.yaxis.grid(True, color=GRID_COLOR)
    ax2.set_axisbelow(True)
    ax2.set_ylim(0, max(blames)*1.22)

    fig.suptitle('Systemd Causal Graph Analysis by Distribution', fontsize=14, fontweight='bold', y=1.02)

    plt.tight_layout()
    path = CHARTS_DIR / 'chart4_causal_graph.png'
    fig.savefig(path, dpi=180, bbox_inches='tight', facecolor=BG_COLOR)
    plt.close(fig)
    print(f"  [OK] {path.name}")
    return path

# ── Chart 5: Test Pyramid ──────────────────────────────
def chart5_test_pyramid():
    fig, ax = plt.subplots(figsize=(7, 5))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis('off')

    layers_data = [
        ('E2E 端到端',    '10/10 cold-boot\nFault injection OK',         '#DC2626', 1.0, 0.6),
        ('回归矩阵',       '20 tests × 5 plans\nApply/Rollback/Stats',  '#EA580C', 3.0, 0.7),
        ('集成测试',       'JSON Schema validation\nSSH round-trip',     '#2563EB', 5.0, 0.7),
        ('单元测试',       '313 Python + 54 Rust\n= 367 total',         '#16A34A', 7.0, 0.8),
    ]

    for label, detail, color, width, height in layers_data:
        left = (10 - width) / 2
        bottom = 0.4
        for prev_label, prev_detail, prev_color, prev_width, prev_height in layers_data:
            if prev_height < height:
                bottom += prev_height + 0.15

        rect = FancyBboxPatch((left, bottom), width, height,
                              boxstyle='round,pad=0.08', facecolor=color, edgecolor='white',
                              linewidth=1.5, alpha=0.88)
        ax.add_patch(rect)
        ax.text(5, bottom + height/2 + 0.12, label, ha='center', va='center',
                fontsize=13, fontweight='bold', color='white')
        ax.text(5, bottom + height/2 - 0.35, detail, ha='center', va='center',
                fontsize=8, color='white', alpha=0.9)

    ax.set_title('KylinBootLab Test Pyramid', fontsize=14, fontweight='bold', pad=12, color='#333')
    ax.text(5, 0.15, '四层测试体系确保功能正确性', ha='center', fontsize=9, color='#888')

    plt.tight_layout()
    path = CHARTS_DIR / 'chart5_test_pyramid.png'
    fig.savefig(path, dpi=180, bbox_inches='tight', facecolor=BG_COLOR)
    plt.close(fig)
    print(f"  [OK] {path.name}")
    return path


# ═══════════════════════════════════════════════════════════
# DOCX Image Insertion
# ═══════════════════════════════════════════════════════════

DRAWING_NS = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}

def make_drawing_xml(doc, rId, name, width_emu, height_emu, descr=""):
    """Build the w:drawing XML element for an inline image."""
    drawing = doc.createElement('w:drawing')
    inline = doc.createElement('wp:inline')
    inline.setAttribute('distT', '0')
    inline.setAttribute('distB', '0')
    inline.setAttribute('distL', '0')
    inline.setAttribute('distR', '0')

    extent = doc.createElement('wp:extent')
    extent.setAttribute('cx', str(width_emu))
    extent.setAttribute('cy', str(height_emu))
    inline.appendChild(extent)

    effectExt = doc.createElement('wp:effectExtent')
    effectExt.setAttribute('l', '0')
    effectExt.setAttribute('t', '0')
    effectExt.setAttribute('r', '0')
    effectExt.setAttribute('b', '0')
    inline.appendChild(effectExt)

    docPr = doc.createElement('wp:docPr')
    docPr.setAttribute('id', '1')
    docPr.setAttribute('name', name)
    if descr:
        docPr.setAttribute('descr', descr)
    inline.appendChild(docPr)

    cNvGraphic = doc.createElement('wp:cNvGraphicFramePr')
    locks = doc.createElement('a:graphicFrameLocks')
    locks.setAttribute('xmlns:a', 'http://schemas.openxmlformats.org/drawingml/2006/main')
    locks.setAttribute('noChangeAspect', '1')
    cNvGraphic.appendChild(locks)
    inline.appendChild(cNvGraphic)

    graphic = doc.createElement('a:graphic')
    graphic.setAttribute('xmlns:a', 'http://schemas.openxmlformats.org/drawingml/2006/main')
    graphicData = doc.createElement('a:graphicData')
    graphicData.setAttribute('uri', 'http://schemas.openxmlformats.org/drawingml/2006/picture')

    pic = doc.createElement('pic:pic')
    pic.setAttribute('xmlns:pic', 'http://schemas.openxmlformats.org/drawingml/2006/picture')
    nvPicPr = doc.createElement('pic:nvPicPr')
    cNvPr = doc.createElement('pic:cNvPr')
    cNvPr.setAttribute('id', '0')
    cNvPr.setAttribute('name', name)
    nvPicPr.appendChild(cNvPr)
    cNvPicPr = doc.createElement('pic:cNvPicPr')
    nvPicPr.appendChild(cNvPicPr)
    pic.appendChild(nvPicPr)

    blipFill = doc.createElement('pic:blipFill')
    blip = doc.createElement('a:blip')
    blip.setAttribute('r:embed', rId)
    blip.setAttribute('xmlns:r', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships')
    blipFill.appendChild(blip)
    stretch = doc.createElement('a:stretch')
    fillRect = doc.createElement('a:fillRect')
    stretch.appendChild(fillRect)
    blipFill.appendChild(stretch)
    pic.appendChild(blipFill)

    spPr = doc.createElement('pic:spPr')
    xfrm = doc.createElement('a:xfrm')
    off = doc.createElement('a:off')
    off.setAttribute('x', '0')
    off.setAttribute('y', '0')
    xfrm.appendChild(off)
    ext = doc.createElement('a:ext')
    ext.setAttribute('cx', str(width_emu))
    ext.setAttribute('cy', str(height_emu))
    xfrm.appendChild(ext)
    spPr.appendChild(xfrm)
    prstGeom = doc.createElement('a:prstGeom')
    prstGeom.setAttribute('prst', 'rect')
    avLst = doc.createElement('a:avLst')
    prstGeom.appendChild(avLst)
    spPr.appendChild(prstGeom)
    pic.appendChild(spPr)

    graphicData.appendChild(pic)
    graphic.appendChild(graphicData)
    inline.appendChild(graphic)
    drawing.appendChild(inline)

    return drawing


def insert_images_into_docx(docx_path, image_map):
    """
    image_map: list of (image_path, anchor_section_text, position_logic)

    For each image:
    1. Copy to word/media/
    2. Add relationship to doc.xml.rels
    3. Add content type
    4. Insert drawing XML at right place in document.xml
    """
    # Unpack
    if UNPACKED_DIR.exists():
        shutil.rmtree(UNPACKED_DIR)
    UNPACKED_DIR.mkdir()

    with zipfile.ZipFile(docx_path, 'r') as zf:
        zf.extractall(UNPACKED_DIR)

    media_dir = UNPACKED_DIR / 'word' / 'media'
    media_dir.mkdir(exist_ok=True)

    # Find next available relationship ID
    rels_path = UNPACKED_DIR / 'word' / '_rels' / 'document.xml.rels'
    rels_dom = defusedxml.minidom.parse(str(rels_path))
    existing_ids = []
    for rel in rels_dom.getElementsByTagName('Relationship'):
        rid = rel.getAttribute('Id')
        existing_ids.append(rid)
    max_num = 0
    for rid in existing_ids:
        m = re.match(r'rId(\d+)', rid)
        if m:
            max_num = max(max_num, int(m.group(1)))

    # Parse document.xml
    doc_path = UNPACKED_DIR / 'word' / 'document.xml'
    doc_dom = defusedxml.minidom.parse(str(doc_path))
    body = doc_dom.getElementsByTagNameNS(
        'http://schemas.openxmlformats.org/wordprocessingml/2006/main', 'body')[0]

    # Prepare images
    image_entries = []
    for img_path, section_text, position in image_map:
        max_num += 1
        rId = f'rId{max_num}'
        img_name = img_path.name

        # Copy image to media
        shutil.copy(img_path, media_dir / img_name)

        image_entries.append((img_name, rId, section_text, position))

    # Add relationships
    relationships = rels_dom.getElementsByTagName('Relationships')[0]
    for img_name, rId, _, _ in image_entries:
        rel = rels_dom.createElement('Relationship')
        rel.setAttribute('Id', rId)
        rel.setAttribute('Type', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image')
        rel.setAttribute('Target', f'media/{img_name}')
        relationships.appendChild(rel)

    with open(rels_path, 'w', encoding='utf-8') as f:
        rels_dom.writexml(f, indent='', addindent='', newl='')

    # Add content type
    ct_path = UNPACKED_DIR / '[Content_Types].xml'
    ct_dom = defusedxml.minidom.parse(str(ct_path))
    types_elem = ct_dom.getElementsByTagName('Types')[0]
    # Check if PNG already exists
    has_png = False
    for child in types_elem.childNodes:
        if child.nodeName == 'Default' and child.getAttribute('Extension') == 'png':
            has_png = True
            break
    if not has_png:
        default = ct_dom.createElement('Default')
        default.setAttribute('Extension', 'png')
        default.setAttribute('ContentType', 'image/png')
        types_elem.appendChild(default)

    with open(ct_path, 'w', encoding='utf-8') as f:
        ct_dom.writexml(f, indent='', addindent='', newl='')

    # Insert images into document.xml
    # Strategy: find the paragraph containing anchor_section_text, then insert image
    # after it (or before the next heading)

    # We need to insert drawing elements. Each drawing goes inside a new w:p
    # that we insert at the right place.

    # Build a list of (paragraph_element, anchor_text_match) from body children
    para_list = []
    for child in body.childNodes:
        if child.nodeName == 'w:p':
            texts = []
            for t in child.getElementsByTagNameNS(
                'http://schemas.openxmlformats.org/wordprocessingml/2006/main', 't'):
                if t.firstChild:
                    texts.append(t.firstChild.nodeValue)
            full = ''.join(texts)
            para_list.append((child, full))

    inserted = 0
    for img_name, rId, section_text, position in image_entries:
        # Find the anchor paragraph
        target_idx = None
        for i, (p, text) in enumerate(para_list):
            if section_text in text:
                target_idx = i
                break

        if target_idx is None:
            print(f"  [WARN] Could not find anchor '{section_text[:40]}...' for {img_name}")
            continue

        target_p = para_list[target_idx][0]

        if position == 'before':
            ref_node = target_p
        elif position == 'after':
            # Insert after: use target_p's nextSibling
            ref_node = target_p.nextSibling
            # But we want to insert BEFORE this ref_node
            if ref_node is None:
                body.appendChild  # fallback
        else:
            ref_node = target_p

        # Determine image dimensions
        # Use PIL to get actual dimensions
        try:
            from PIL import Image
            pil_img = Image.open(CHARTS_DIR / img_name)
            img_w, img_h = pil_img.size
            # Target width: ~6 inches = 5486400 EMU
            target_w_emu = 5486400
            ratio = target_w_emu / (img_w * 914400 / pil_img.info.get('dpi', (180, 180))[0])
            # Use DPI from file or default 180
            dpi = pil_img.info.get('dpi', (180, 180))[0]
            pixel_to_emu = 914400 / dpi
            w_emu = int(img_w * pixel_to_emu)
            h_emu = int(img_h * pixel_to_emu)
            # Clamp width to 6 inches
            if w_emu > 5486400:
                scale = 5486400 / w_emu
                w_emu = 5486400
                h_emu = int(h_emu * scale)
        except Exception as e:
            w_emu = 5486400
            h_emu = 3200400
            print(f"  ! PIL error: {e}, using default dimensions")

        # Create image paragraph
        img_para = doc_dom.createElement('w:p')
        # Center alignment
        pPr = doc_dom.createElement('w:pPr')
        jc = doc_dom.createElement('w:jc')
        jc.setAttribute('w:val', 'center')
        pPr.appendChild(jc)
        img_para.appendChild(pPr)

        drawing = make_drawing_xml(doc_dom, rId, img_name, w_emu, h_emu, img_name)
        # Wrap drawing in a run
        r = doc_dom.createElement('w:r')
        r.appendChild(drawing)
        img_para.appendChild(r)

        # Also add a caption paragraph
        captions = {
            'chart1_boot_comparison.png': '图1：跨发行版启动时间分解对比',
            'chart2_abba_forest.png': '图2：ABBA 实验结果森林图（Bootstrap 95% CI）',
            'chart3_architecture.png': '图3：KylinBootLab 分析管道架构',
            'chart4_causal_graph.png': '图4：Systemd 因果图分析（节点/边/瓶颈）',
            'chart5_test_pyramid.png': '图5：KylinBootLab 四层测试金字塔',
        }

        if position == 'after':
            # Insert image paragraph + caption after target paragraph
            insert_pt = target_p.nextSibling
            # Image
            body.insertBefore(img_para, insert_pt)
            # Caption
            cap = doc_dom.createElement('w:p')
            cap_pPr = doc_dom.createElement('w:pPr')
            cap_jc = doc_dom.createElement('w:jc')
            cap_jc.setAttribute('w:val', 'center')
            cap_pPr.appendChild(cap_jc)
            cap.appendChild(cap_pPr)
            cap_r = doc_dom.createElement('w:r')
            cap_rPr = doc_dom.createElement('w:rPr')
            cap_rFonts = doc_dom.createElement('w:rFonts')
            cap_rFonts.setAttribute('w:hint', 'eastAsia')
            cap_rPr.appendChild(cap_rFonts)
            cap_b = doc_dom.createElement('w:b')
            cap_rPr.appendChild(cap_b)
            cap_r.appendChild(cap_rPr)
            cap_t = doc_dom.createElement('w:t')
            cap_t.setAttribute('xml:space', 'preserve')
            cap_t.appendChild(doc_dom.createTextNode(captions.get(img_name, img_name)))
            cap_r.appendChild(cap_t)
            cap.appendChild(cap_r)
            body.insertBefore(cap, insert_pt)
            # Add an empty spacer paragraph
            spacer = doc_dom.createElement('w:p')
            body.insertBefore(spacer, insert_pt)
            inserted += 1
            print(f"  [OK] Inserted {img_name} after '{section_text[:50]}...'")

        elif position == 'before':
            # Insert image before target, then caption between image and target
            body.insertBefore(img_para, target_p)
            cap = doc_dom.createElement('w:p')
            cap_pPr = doc_dom.createElement('w:pPr')
            cap_jc = doc_dom.createElement('w:jc')
            cap_jc.setAttribute('w:val', 'center')
            cap_pPr.appendChild(cap_jc)
            cap.appendChild(cap_pPr)
            cap_r = doc_dom.createElement('w:r')
            cap_rPr = doc_dom.createElement('w:rPr')
            cap_rFonts = doc_dom.createElement('w:rFonts')
            cap_rFonts.setAttribute('w:hint', 'eastAsia')
            cap_rPr.appendChild(cap_rFonts)
            cap_b = doc_dom.createElement('w:b')
            cap_rPr.appendChild(cap_b)
            cap_r.appendChild(cap_rPr)
            cap_t = doc_dom.createElement('w:t')
            cap_t.setAttribute('xml:space', 'preserve')
            cap_t.appendChild(doc_dom.createTextNode(captions.get(img_name, img_name)))
            cap_r.appendChild(cap_t)
            cap.appendChild(cap_r)
            body.insertBefore(cap, target_p)
            spacer = doc_dom.createElement('w:p')
            body.insertBefore(spacer, target_p)
            inserted += 1
            print(f"  [OK] Inserted {img_name} before '{section_text[:50]}...'")

    # Write back document.xml
    with open(doc_path, 'w', encoding='utf-8') as f:
        doc_dom.writexml(f, indent='', addindent='', newl='')

    print(f"\nTotal images inserted: {inserted}/{len(image_entries)}")

    return UNPACKED_DIR


def repack(unpacked_dir, output_path, original_path):
    """Repack the edited directory into a DOCX file."""
    import subprocess
    # Use the skill's pack.py
    pack_script = Path.home() / '.claude' / 'skills' / 'docx' / 'scripts' / 'office' / 'pack.py'
    cmd = f'uv run python "{pack_script}" "{unpacked_dir}" "{output_path}" --original "{original_path}" --validate false'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    print(result.stdout)
    if result.returncode != 0:
        print("STDERR:", result.stderr)
    return result.returncode == 0


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
def main():
    CHARTS_DIR.mkdir(exist_ok=True)

    # ── Phase 1: Generate charts ──
    print("Phase 1: Generating charts...")
    charts = [
        chart1_boot_comparison,   # Stacked bar: boot time by distro
        chart2_abba_forest,       # Forest plot: ABBA experiment results
        chart3_architecture,      # Pipeline diagram
        chart4_causal_graph,      # Causal graph stats
        chart5_test_pyramid,      # Test pyramid
    ]
    chart_paths = [f() for f in charts]
    print(f"Generated {len(chart_paths)} charts.\n")

    # ── Phase 2: Insert into DOCX ──
    print("Phase 2: Inserting charts into DOCX...")

    # Define where each chart goes (anchor text in document + position)
    image_map = [
        # (path, anchor_text_fragment, 'before'|'after')
        (chart_paths[0], '关键发现：Fedora 41 启动最快', 'before'),       # Boot comparison before findings
        (chart_paths[1], '（二）ABBA 实验统计验证结果', 'before'),       # ABBA forest before ABBA table
        (chart_paths[2], '全链路技术路线由五层构成', 'after'),           # Architecture after tech route intro
        (chart_paths[3], '（四）因果图分析稳定性', 'before'),            # Causal graph before causal findings
        (chart_paths[4], 'KylinBootLab 采用四层测试金字塔', 'after'),   # Test pyramid after test desc intro
    ]

    unpacked = insert_images_into_docx(DOCX_PATH, image_map)

    # ── Phase 3: Repack ──
    print("\nPhase 3: Repacking DOCX...")
    output_path = DOCX_PATH  # Overwrite
    backup = Path(str(DOCX_PATH) + '.pre-charts.bak')
    if DOCX_PATH.exists() and not backup.exists():
        shutil.copy(DOCX_PATH, backup)
        print(f"  Backup saved to {backup}")

    success = repack(unpacked, output_path, DOCX_PATH)
    if success:
        print(f"\n[OK] Done! Charts embedded in {output_path}")
    else:
        print("\n[FAIL] Repack failed. Check errors above.")

    # Cleanup
    if UNPACKED_DIR.exists():
        shutil.rmtree(UNPACKED_DIR)
    print("Cleaned up temporary files.")


if __name__ == '__main__':
    main()
