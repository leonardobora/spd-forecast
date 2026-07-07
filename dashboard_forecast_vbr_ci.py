from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st


ROOT = Path(__file__).parent
DATA_DIR = ROOT / "outputs"
OPP_FILE = DATA_DIR / "base_oportunidade_snapshot.csv"
ITEM_FILE = DATA_DIR / "base_item_limpa.csv"
TODAY = pd.Timestamp("2026-07-07")

COLORWAY = ["#2563eb", "#059669", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2"]


st.set_page_config(
    page_title="Forecast VBR-CI",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(show_spinner=False)
def load_data():
    opp = pd.read_csv(OPP_FILE)
    items = pd.read_csv(ITEM_FILE, usecols=["snapshot_mes", "no_opt", "produto_codigo_do_produto"])

    date_cols = [
        "mes_de_fechamento_dt",
        "data_forecast_dt",
        "data_atual_dt",
        "data_atual_jun26_dt",
        "data_atual_jul26_dt",
    ]
    for col in date_cols:
        if col in opp.columns:
            opp[col] = pd.to_datetime(opp[col], errors="coerce")

    opp["probabilidade"] = pd.to_numeric(opp["probabilidade"], errors="coerce")
    for col in ["quantidade", "pipeline", "total_liqliq", "r_pipeline", "linhas_item"]:
        opp[col] = pd.to_numeric(opp[col], errors="coerce")

    product_counts = (
        items.groupby(["snapshot_mes", "no_opt"], dropna=False)["produto_codigo_do_produto"]
        .nunique()
        .reset_index(name="produtos_unicos")
    )
    opp = opp.merge(product_counts, on=["snapshot_mes", "no_opt"], how="left")
    opp["diff_forecast_fechamento_dias"] = (
        opp["data_forecast_dt"] - opp["mes_de_fechamento_dt"]
    ).dt.days
    return opp


def money(value):
    if pd.isna(value):
        return "R$ 0"
    return f"R$ {value:,.0f}".replace(",", ".")


def pct(value):
    if pd.isna(value):
        return "0,0%"
    return f"{value:.1f}%".replace(".", ",")


def top_table(df, dim, n=10):
    out = (
        df.groupby(dim, dropna=False)
        .agg(
            oportunidades=("no_opt", "nunique"),
            snapshots=("no_opt", "size"),
            r_pipeline=("r_pipeline", "sum"),
            pipeline=("pipeline", "sum"),
        )
        .reset_index()
        .sort_values("r_pipeline", ascending=False)
        .head(n)
    )
    total = df["r_pipeline"].sum()
    out["share_r_pipeline_pct"] = (out["r_pipeline"] / total * 100).round(2) if total else 0
    return out


def bar_chart(df, x, y, title, color=None, orientation="v"):
    fig = px.bar(
        df,
        x=x,
        y=y,
        color=color,
        orientation=orientation,
        title=title,
        color_discrete_sequence=COLORWAY,
    )
    fig.update_layout(
        height=380,
        margin=dict(l=10, r=10, t=50, b=10),
        legend_title_text="",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=13),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(148,163,184,0.25)")
    return fig


def line_chart(df):
    monthly = (
        df.groupby("snapshot_mes", dropna=False)
        .agg(
            oportunidades=("no_opt", "nunique"),
            r_pipeline=("r_pipeline", "sum"),
            probabilidade_media=("probabilidade", "mean"),
        )
        .reset_index()
        .sort_values("snapshot_mes")
    )
    fig = px.line(
        monthly,
        x="snapshot_mes",
        y="r_pipeline",
        markers=True,
        title="R$ Pipeline por snapshot",
        color_discrete_sequence=["#2563eb"],
    )
    fig.update_layout(
        height=340,
        margin=dict(l=10, r=10, t=50, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(tickprefix="R$ ", separatethousands=True, gridcolor="rgba(148,163,184,0.25)")
    fig.update_xaxes(showgrid=False)
    return fig


def apply_multiselect(df, col, selected):
    if not selected:
        return df
    return df[df[col].isin(selected)]


st.markdown(
    """
    <style>
    .block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
    div[data-testid="stMetric"] {
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 14px 16px;
      background: #ffffff;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
    }
    h1, h2, h3 {letter-spacing: 0;}
    .small-note {
      color: #64748b;
      font-size: 0.92rem;
      line-height: 1.4;
      margin-top: -0.4rem;
      margin-bottom: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


opp = load_data()

st.title("Forecast VBR-CI")
st.markdown(
    "<div class='small-note'>Dashboard exploratorio baseado apenas nos campos existentes. Unidade principal: oportunidade-snapshot.</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Filtros")
    snapshot_filter = st.multiselect(
        "Snapshot",
        options=sorted(opp["snapshot_mes"].dropna().unique()),
        default=sorted(opp["snapshot_mes"].dropna().unique()),
    )
    fase_filter = st.multiselect("Fase", options=sorted(opp["fase"].dropna().unique()))
    status_filter = st.multiselect("Status", options=sorted(opp["status"].dropna().unique()))
    owner_filter = st.multiselect(
        "Proprietario", options=sorted(opp["proprietario_da_oportunidade"].dropna().unique())
    )
    client_options = sorted(opp["cliente_final"].dropna().unique())
    client_filter = st.multiselect("Cliente", options=client_options)
    min_prob, max_prob = st.slider(
        "Probabilidade",
        min_value=0.0,
        max_value=1.0,
        value=(0.0, 1.0),
        step=0.1,
    )

filtered = opp.copy()
filtered = apply_multiselect(filtered, "snapshot_mes", snapshot_filter)
filtered = apply_multiselect(filtered, "fase", fase_filter)
filtered = apply_multiselect(filtered, "status", status_filter)
filtered = apply_multiselect(filtered, "proprietario_da_oportunidade", owner_filter)
filtered = apply_multiselect(filtered, "cliente_final", client_filter)
filtered = filtered[
    filtered["probabilidade"].between(min_prob, max_prob, inclusive="both")
    | filtered["probabilidade"].isna()
]

if filtered.empty:
    st.warning("Nenhum registro encontrado com os filtros atuais.")
    st.stop()

total_pipeline = filtered["r_pipeline"].sum()
gross_pipeline = filtered["pipeline"].sum()
opps = filtered["no_opt"].nunique()
snapshots = filtered["snapshot_mes"].nunique()
avg_prob = filtered["probabilidade"].mean() * 100

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
kpi1.metric("R$ Pipeline", money(total_pipeline))
kpi2.metric("Pipeline", f"{gross_pipeline:,.0f}".replace(",", "."))
kpi3.metric("Oportunidades", f"{opps:,}".replace(",", "."))
kpi4.metric("Snapshots", snapshots)
kpi5.metric("Prob. media", pct(avg_prob))

tab_overview, tab_concentration, tab_quality, tab_history, tab_data = st.tabs(
    ["Visao geral", "Concentracao", "Qualidade", "Historico", "Dados"]
)

with tab_overview:
    left, right = st.columns([1.2, 1])
    with left:
        st.plotly_chart(line_chart(filtered), width="stretch")
    with right:
        phase = (
            filtered.groupby("fase", dropna=False)
            .agg(r_pipeline=("r_pipeline", "sum"), registros=("no_opt", "size"))
            .reset_index()
            .sort_values("r_pipeline", ascending=False)
        )
        st.plotly_chart(
            bar_chart(phase, "fase", "r_pipeline", "R$ Pipeline por fase"),
            width="stretch",
        )

    col_a, col_b = st.columns(2)
    with col_a:
        status = (
            filtered.groupby("status", dropna=False)
            .agg(registros=("no_opt", "size"))
            .reset_index()
            .sort_values("registros", ascending=False)
        )
        st.plotly_chart(
            bar_chart(status, "status", "registros", "Registros por status"),
            width="stretch",
        )
    with col_b:
        prob = (
            filtered.assign(probabilidade_round=filtered["probabilidade"].round(2))
            .groupby("probabilidade_round", dropna=False)
            .agg(registros=("no_opt", "size"), r_pipeline=("r_pipeline", "sum"))
            .reset_index()
            .sort_values("probabilidade_round")
        )
        st.plotly_chart(
            bar_chart(prob, "probabilidade_round", "registros", "Distribuicao de probabilidade"),
            width="stretch",
        )

with tab_concentration:
    client_top = top_table(filtered, "cliente_final", 15)
    owner_top = top_table(filtered, "proprietario_da_oportunidade", 15)
    top10_client_share = top_table(filtered, "cliente_final", 10)["share_r_pipeline_pct"].sum()
    top10_owner_share = top_table(filtered, "proprietario_da_oportunidade", 10)["share_r_pipeline_pct"].sum()

    c1, c2 = st.columns(2)
    c1.metric("Share top 10 clientes", pct(top10_client_share))
    c2.metric("Share top 10 proprietarios", pct(top10_owner_share))

    left, right = st.columns(2)
    with left:
        chart_df = client_top.sort_values("r_pipeline", ascending=True)
        st.plotly_chart(
            bar_chart(
                chart_df,
                "r_pipeline",
                "cliente_final",
                "Top clientes por R$ Pipeline",
                orientation="h",
            ),
            width="stretch",
        )
        st.dataframe(client_top, width="stretch", hide_index=True)
    with right:
        chart_df = owner_top.sort_values("r_pipeline", ascending=True)
        st.plotly_chart(
            bar_chart(
                chart_df,
                "r_pipeline",
                "proprietario_da_oportunidade",
                "Top proprietarios por R$ Pipeline",
                orientation="h",
            ),
            width="stretch",
        )
        st.dataframe(owner_top, width="stretch", hide_index=True)

with tab_quality:
    invalid_prob = filtered[
        filtered["probabilidade"].notna()
        & ((filtered["probabilidade"] < 0) | (filtered["probabilidade"] > 1))
    ]
    date_quality = pd.DataFrame(
        [
            {
                "campo": col,
                "nulos_pct": round(filtered[col].isna().mean() * 100, 2),
                "futuras_qtd": int((filtered[col] > TODAY).sum()),
                "min": filtered[col].min(),
                "max": filtered[col].max(),
            }
            for col in [
                "data_forecast_dt",
                "mes_de_fechamento_dt",
                "data_atual_dt",
                "data_atual_jun26_dt",
                "data_atual_jul26_dt",
            ]
            if col in filtered.columns
        ]
    )
    q1, q2, q3 = st.columns(3)
    q1.metric("Prob. fora de 0-1", len(invalid_prob))
    q2.metric("Media diff forecast x fechamento", f"{filtered['diff_forecast_fechamento_dias'].mean():.1f} dias")
    q3.metric("Mediana diff", f"{filtered['diff_forecast_fechamento_dias'].median():.0f} dias")

    left, right = st.columns([1, 1])
    with left:
        diff = filtered["diff_forecast_fechamento_dias"].dropna()
        diff_df = pd.DataFrame({"diff_dias": diff})
        fig = px.histogram(
            diff_df,
            x="diff_dias",
            nbins=12,
            title="Diferenca entre Data Forecast e Mes de Fechamento",
            color_discrete_sequence=["#059669"],
        )
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(fig, width="stretch")
    with right:
        st.dataframe(date_quality, width="stretch", hide_index=True)

    st.subheader("Flags comerciais para revisao")
    high = filtered["probabilidade"] >= 0.7
    low = filtered["probabilidade"] <= 0.4
    initial_phase = filtered["fase"].astype(str).str.contains("prospec", case=False, na=False)
    final_phase = filtered["fase"].astype(str).str.contains("negocia", case=False, na=False)
    rejected = filtered["status"].astype(str).str.contains("Rejeitado", case=False, na=False)
    approved = filtered["status"].astype(str).str.contains("Aprovado", case=False, na=False)
    flags = pd.DataFrame(
        [
            ("status_aprovado_sem_mes_fechamento", approved & filtered["mes_de_fechamento_dt"].isna()),
            ("status_rejeitado_em_fase_negociacao", rejected & final_phase),
            ("probabilidade_alta_em_prospeccao", high & initial_phase),
            ("probabilidade_baixa_em_negociacao", low & final_phase),
            ("data_forecast_anterior_mes_fechamento", filtered["data_forecast_dt"] < filtered["mes_de_fechamento_dt"]),
        ],
        columns=["regra", "mask"],
    )
    flags["quantidade"] = flags["mask"].apply(lambda s: int(s.sum()))
    flags["percentual"] = flags["quantidade"] / len(filtered) * 100
    st.dataframe(flags[["regra", "quantidade", "percentual"]], width="stretch", hide_index=True)

with tab_history:
    changes = (
        filtered.sort_values(["no_opt", "snapshot_mes"])
        .groupby("no_opt", dropna=False)
        .agg(
            snapshots=("snapshot_mes", "nunique"),
            prob_distintas=("probabilidade", "nunique"),
            fases_distintas=("fase", "nunique"),
            status_distintos=("status", "nunique"),
            meses_fechamento_distintos=("mes_de_fechamento_dt", "nunique"),
            r_pipeline_distintos=("r_pipeline", "nunique"),
        )
        .reset_index()
    )
    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Oportunidades", changes["no_opt"].nunique())
    h2.metric("Com >1 snapshot", int((changes["snapshots"] > 1).sum()))
    h3.metric("Mudanca de mes fechamento", int((changes["meses_fechamento_distintos"] > 1).sum()))
    h4.metric("Mudanca de R$ Pipeline", int((changes["r_pipeline_distintos"] > 1).sum()))

    timeline = (
        filtered.groupby(["snapshot_mes", "fase"], dropna=False)
        .agg(oportunidades=("no_opt", "nunique"))
        .reset_index()
        .sort_values("snapshot_mes")
    )
    fig = px.bar(
        timeline,
        x="snapshot_mes",
        y="oportunidades",
        color="fase",
        title="Oportunidades por fase ao longo dos snapshots",
        color_discrete_sequence=COLORWAY,
    )
    fig.update_layout(height=390, margin=dict(l=10, r=10, t=50, b=10), legend_title_text="")
    st.plotly_chart(fig, width="stretch")
    st.dataframe(
        changes.sort_values(["snapshots", "r_pipeline_distintos"], ascending=False).head(50),
        width="stretch",
        hide_index=True,
    )

with tab_data:
    st.subheader("Base filtrada")
    cols = [
        "snapshot_mes",
        "no_opt",
        "cliente_final",
        "proprietario_da_oportunidade",
        "fase",
        "status",
        "probabilidade",
        "pipeline",
        "r_pipeline",
        "mes_de_fechamento_dt",
        "data_forecast_dt",
        "linhas_item",
        "produtos_unicos",
    ]
    st.dataframe(filtered[cols].sort_values(["snapshot_mes", "r_pipeline"], ascending=[True, False]), width="stretch", hide_index=True)
    st.download_button(
        "Baixar CSV filtrado",
        data=filtered[cols].to_csv(index=False).encode("utf-8-sig"),
        file_name="forecast_vbr_ci_filtrado.csv",
        mime="text/csv",
    )
