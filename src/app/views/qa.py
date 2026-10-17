"""Data QA & sources tab: pipeline health, warehouse counts, knowledge-base validation."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

import polars as pl
import streamlit as st

from src.app.i18n import lang, t
from src.app.ui import kpi
from src.region.knowledge import KnowledgeBase


def render(data: dict, kb: KnowledgeBase | None, kb_error: str | None) -> None:
    runs: pl.DataFrame = data["runs"]
    counts: dict = data["counts"]
    lr = runs.row(0, named=True) if runs.height else {}
    fresh_h = ((datetime.now(timezone.utc).replace(tzinfo=None) - lr["finished_at"]).total_seconds()
               / 3600) if lr else float("nan")
    q = st.columns(5)
    kpi(q[0], t("qa_last"), lr.get("status", "—").replace("_", " ").title(), f"run {lr.get('run_id', '—')}")
    kpi(q[1], t("qa_fresh"), t("qa_fresh_v", h=fresh_h),
        t("qa_fresh_ok") if fresh_h < 24 else t("qa_fresh_bad"))
    pass_rate = 100 * lr["rows_passed"] / lr["rows_received"] if lr.get("rows_received") else 0
    kpi(q[2], t("qa_pass"), f"{pass_rate:.1f}%", t("qa_rows", ok=lr.get("rows_passed", 0), n=lr.get("rows_received", 0)))
    kpi(q[3], t("qa_quarantine"), f"{lr.get('rows_rejected', 0)}", t("qa_anomalies", n=lr.get("anomaly_warnings", 0)))
    if kb is not None:
        n_items = sum(len(x) for x in (kb.key_figures, kb.problems, kb.root_causes, kb.solutions,
                                        kb.stories, kb.towns, kb.provinces))
        label = "Base de connaissances" if lang() == "fr" else "Knowledge base"
        sub = (f"{n_items} entrées · {len(kb.sources)} sources · 100 % citées" if lang() == "fr"
               else f"{n_items} entries · {len(kb.sources)} sources · 100% cited")
        kpi(q[4], label, "✔ " + ("valide" if lang() == "fr" else "valid"), sub)
    else:
        kpi(q[4], "Knowledge base", "✖ invalid", kb_error or "")

    st.write("")
    c1, c2 = st.columns([3, 2], gap="large")
    with c1:
        st.markdown(f"##### {t('qa_completeness')}")
        st.dataframe(data["completeness"], hide_index=True, width="stretch")
        st.markdown(f"##### {t('qa_history')}")
        st.dataframe(runs.head(10), hide_index=True, width="stretch")
        if data.get("history_log") is not None and data["history_log"].height:
            st.markdown("##### " + ("Archive climatique (ERA5 / GloFAS)" if lang() == "fr"
                                    else "Climate archive runs (ERA5 / GloFAS)"))
            st.dataframe(data["history_log"].head(5), hide_index=True, width="stretch")
    with c2:
        st.markdown(f"##### {t('qa_counts')}")
        st.dataframe(pl.DataFrame({"table": list(counts), "rows": list(counts.values())}),
                     hide_index=True, width="stretch")
        st.markdown(f"##### {t('qa_gates')}")
        st.markdown(t("qa_gates_md"))
        rej = data["rejections"]
        st.markdown(f"##### {t('qa_quarantined', n=rej.height)}")
        if rej.height:
            st.dataframe(rej, hide_index=True, width="stretch")
        else:
            st.success(t("qa_none"))
        if kb is not None:
            st.markdown("##### " + ("Sources par éditeur" if lang() == "fr" else "Sources by publisher"))
            pubs = Counter(s.publisher for s in kb.sources).most_common()
            st.dataframe(pl.DataFrame({"publisher": [p for p, _ in pubs], "n": [n for _, n in pubs]}),
                         hide_index=True, width="stretch", height=240)
