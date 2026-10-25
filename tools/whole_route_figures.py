"""Whole-route figures from every results/ganga_km*/ folder: stage-by-km chart and build-time summary."""
import glob, pathlib
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm

ROOT = pathlib.Path(__file__).resolve().parents[1]
STAGES = ["No data", "Not started", "Early clearing", "Earthwork / active", "Paved / near-complete"]
COLORS = ["#d9d9d9", "#4a9e5c", "#e8c547", "#d9713b", "#3b4a6b"]
MILESTONES = {"Physical work began (reported)": "2022Q2", "Inaugurated (reported)": "2026Q2"}

frames = []
for f in sorted(glob.glob(str(ROOT / "results/ganga_km*/segment_quarter_stats.csv"))):
    d = pd.read_csv(f); d["stretch"] = pathlib.Path(f).parent.name.replace("ganga_", ""); frames.append(d)
df = pd.concat(frames)
PER = sorted(df.period.unique())
grid = df.pivot_table(index=["km_start", "label"], columns="period", values="stage", aggfunc="first").reindex(columns=PER)
grid = grid.sort_index(level=0)
# forward-fill cloud gaps so they don't read as regress
grid = grid.replace("No data", np.nan).T.ffill().T.fillna("No data")
codes = grid.apply(lambda c: c.map({s: i for i, s in enumerate(STAGES)})).to_numpy(float)

# insert a blank row between stretches
kms = grid.index.get_level_values(0).to_numpy()
rows, ylab, ypos, breaks = [], [], [], []
prev = None
for i, k in enumerate(kms):
    if prev is not None and k - prev > 2.5:
        rows.append(np.full(len(PER), np.nan)); breaks.append(len(rows) - 1)
    rows.append(codes[i]); prev = k
    if k % 10 == 0 or i == 0 or (i > 0 and kms[i] - kms[i - 1] > 2.5):
        ylab.append(f"km {int(k)}"); ypos.append(len(rows) - 1)
M = np.vstack(rows)

def stage_chart(path, size, title_size, title, legend_y=-0.09):
    fig, ax = plt.subplots(figsize=size)
    cmap = ListedColormap(COLORS); cmap.set_bad("white")
    ax.imshow(np.ma.masked_invalid(M), aspect="auto", cmap=cmap,
              norm=BoundaryNorm(np.arange(-0.5, len(STAGES)), cmap.N), interpolation="nearest")
    ax.set_yticks(ypos); ax.set_yticklabels(ylab, fontsize=8)
    ax.set_xticks(range(len(PER))); ax.set_xticklabels(PER, rotation=90, fontsize=8)
    for name, q in MILESTONES.items():
        x = PER.index(q); ax.axvline(x, color="#222", lw=1, ls="--")
        ax.text(x + 0.2, -0.8, name, rotation=0, fontsize=8, va="bottom", ha="left" if "began" in name else "right")
    for sp in ax.spines.values(): sp.set_visible(False)
    ax.tick_params(length=0)
    ax.set_title(title,
                 fontsize=title_size, pad=22)
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c) for c in COLORS[1:]], labels=STAGES[1:],
              loc="upper center", bbox_to_anchor=(0.5, legend_y), ncol=4, frameon=False, fontsize=9)
    plt.tight_layout(); plt.savefig(path, dpi=150); plt.close()


TITLE = "Ganga Expressway: construction stage by chainage, 7 stretches × 20 km (Meerut at top, Prayagraj at bottom)"
stage_chart(ROOT / "docs/img/whole_route_stages.png", (12, 9.5), 11, TITLE)
stage_chart(ROOT / "docs/img/whole_route_stages_compact.png", (12, 5.9), 10.5, TITLE, legend_y=-0.2)

# ---- build-time summary per stretch ----
ms = []
for f in sorted(glob.glob(str(ROOT / "results/ganga_km*/segment_milestones.csv"))):
    m = pd.read_csv(f); m["stretch"] = pathlib.Path(f).parent.name.replace("ganga_", ""); ms.append(m)
ms = pd.concat(ms)
q2i = lambda q: int(q[:4]) * 4 + int(q[-1]) - 1
ms["months"] = [3 * (q2i(p) - q2i(e)) if isinstance(p, str) and isinstance(e, str) else np.nan
                for e, p in zip(ms.first_earthwork, ms.first_paved)]
summ = (ms.groupby("stretch")
          .agg(km=("stretch", lambda s: int(s.iloc[0].split("-")[0][2:])),
               earthwork_median=("first_earthwork", lambda s: sorted(s.dropna())[len(s.dropna()) // 2]),
               paved_median=("first_paved", lambda s: sorted(s.dropna())[len(s.dropna()) // 2] if s.notna().any() else None),
               months_median=("months", "median"), segments=("seg_id", "size"),
               # opened 29 Apr 2026, inside 2026 Q2: count only paving seen in quarters that ended before it
               paved_by_inauguration=("first_paved", lambda s: int((s.notna() & (s <= "2026Q1")).sum())))
          .sort_values("km"))
summ.to_csv(ROOT / "results/whole_route_summary.csv")
print(summ.to_string())

fig, ax = plt.subplots(figsize=(8, 3.6))
y = np.arange(len(summ))[::-1]
ax.barh(y, summ.months_median, height=0.55, color="#d9713b")
for yi, v, (lbl, r) in zip(y, summ.months_median, summ.iterrows()):
    ax.text(v + 0.6, yi, f"{v:g} mo", va="center", fontsize=9, color="#333")
ax.set_yticks(y); ax.set_yticklabels([f"km {s[2:].replace('-', '–')}" for s in summ.index], fontsize=9)
ax.set_xlabel("median months from earthwork start to paving (per 2 km segment)", fontsize=9)
ax.set_title("How long each stretch took", fontsize=11, loc="left")
for sp in ["top", "right"]: ax.spines[sp].set_visible(False)
ax.grid(axis="x", color="#e5e5e5", lw=0.8); ax.set_axisbelow(True)
plt.tight_layout(); plt.savefig(ROOT / "docs/img/whole_route_build_time.png", dpi=150); plt.close()
