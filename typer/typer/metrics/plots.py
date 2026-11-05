"""Wykresy niezawodnosci zapisywane do plikow (modul 6). Obok kazdego PNG ten sam wykres w CSV,
zeby liczby dalo sie sprawdzic bez patrzenia na obrazek."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from typer.metrics.scores import ece, reliability_table  # noqa: E402

COLORS = ["#2a6fbb", "#d9822b", "#3a9a5b", "#8f4fb3"]


def reliability_plot(series: dict[str, tuple], path, title: str = "", bins: int = 10) -> Path:
    """series: etykieta -> (p, y) dla rynku binarnego albo jednej klasy 1X2. Zapisuje PNG i CSV."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(5, 5), dpi=110)
    ax.plot([0, 1], [0, 1], color="#999999", lw=1, ls="--", label="idealna kalibracja")
    tabs = []
    lo_all, hi_all = 1.0, 0.0
    for k, (label, (p, y)) in enumerate(series.items()):
        t = reliability_table(p, y, bins)
        t.insert(0, "seria", label)
        tabs.append(t)
        c = COLORS[k % len(COLORS)]
        ax.errorbar(t["p_srednie"], t["czestosc"], yerr=[t["czestosc"] - t["ci_lo"], t["ci_hi"] - t["czestosc"]],
                    fmt="o-", color=c, ms=4, lw=1.2, capsize=2,
                    label=f"{label} (ECE {ece(np.asarray(p), np.asarray(y), bins):.4f}, n={len(p)})")
        lo_all, hi_all = min(lo_all, t["ci_lo"].min(), t["p_srednie"].min()), max(hi_all, t["ci_hi"].max(),
                                                                                   t["p_srednie"].max())
    pad = 0.03
    lim = (max(0.0, lo_all - pad), min(1.0, hi_all + pad))
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xlabel("przewidziane prawdopodobienstwo")
    ax.set_ylabel("obserwowana czestosc (95% Wilson)")
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=7, loc="upper left")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    pd.concat(tabs).to_csv(path.with_suffix(".csv"), index=False)
    return path
