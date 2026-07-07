"""
Metricas indiretas de instabilidade da carteira VBR-CI.

Entrada esperada:
- outputs/base_item_limpa.csv
- outputs/base_oportunidade_snapshot.csv

O script nao usa realizado e nao calcula assertividade final. Ele mede sinais
indiretos de instabilidade: mudanca de mes previsto, probabilidade, valor,
concentracao, rotatividade e impacto de duplicatas.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


SNAPSHOT_ORDER = ["2026-03", "2026-04", "2026-05"]
VALUE_COL = "r_pipeline"
PROJECT_VALUE_COL = "total_liqliq"


def markdown_table(df: pd.DataFrame, max_rows: int = 30) -> str:
    if df.empty:
        return "_Sem registros._"
    return df.head(max_rows).to_markdown(index=False)


def money(value: float | int | None) -> str:
    if pd.isna(value):
        return "NA"
    return f"R$ {float(value):,.2f}"


def pct(value: float | int | None) -> str:
    if pd.isna(value):
        return "NA"
    return f"{float(value):.2f}%"


def month_number(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce")
    return parsed.dt.year * 12 + parsed.dt.month


def closing_delta_bucket(value: float | int | None) -> str:
    if pd.isna(value):
        return "sem_dado"
    value = int(value)
    if value <= -7:
        return "<=-7"
    if value <= -4:
        return "-6 a -4"
    if value in {-3, -2, -1, 0, 1, 2, 3}:
        return f"{value:+d}" if value > 0 else str(value)
    if value <= 6:
        return "+4 a +6"
    return ">=+7"


def load_data(output_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    item_path = output_dir / "base_item_limpa.csv"
    opp_path = output_dir / "base_oportunidade_snapshot.csv"

    if not item_path.exists() or not opp_path.exists():
        raise FileNotFoundError(
            "Arquivos base_item_limpa.csv e base_oportunidade_snapshot.csv nao encontrados. "
            "Execute eda_forecast_vbr_ci.py primeiro."
        )

    item = pd.read_csv(item_path, encoding="utf-8-sig")
    opp = pd.read_csv(opp_path, encoding="utf-8-sig")

    for df in [item, opp]:
        for col in [VALUE_COL, PROJECT_VALUE_COL, "probabilidade", "pipeline"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        for col in ["mes_de_fechamento_dt", "data_forecast_dt", "data_atual_dt"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")

    return item, opp


def opportunities_in_all_snapshots(opp: pd.DataFrame) -> pd.DataFrame:
    counts = opp.groupby("no_opt")["snapshot_mes"].nunique()
    common_ids = counts[counts == len(SNAPSHOT_ORDER)].index
    return opp[opp["no_opt"].isin(common_ids)].copy()


def closing_month_stability(common: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    data = common[["no_opt", "snapshot_mes", "mes_de_fechamento_dt"]].copy()
    data["mes_num"] = month_number(data["mes_de_fechamento_dt"])
    wide = data.pivot_table(index="no_opt", columns="snapshot_mes", values="mes_num", aggfunc="first")
    wide = wide.reindex(columns=SNAPSHOT_ORDER)

    result = wide.reset_index()
    result["delta_abr_menos_mar_meses"] = result["2026-04"] - result["2026-03"]
    result["delta_mai_menos_abr_meses"] = result["2026-05"] - result["2026-04"]
    result["delta_total_mai_menos_mar_meses"] = result["2026-05"] - result["2026-03"]
    result["deslocamento_abs_total_meses"] = result["delta_total_mai_menos_mar_meses"].abs()
    result["manteve_mes_todos_snapshots"] = (
        (result["2026-03"] == result["2026-04"]) & (result["2026-04"] == result["2026-05"])
    )

    order = ["<=-7", "-6 a -4", "-3", "-2", "-1", "0", "+1", "+2", "+3", "+4 a +6", ">=+7", "sem_dado"]
    histogram = (
        result["delta_total_mai_menos_mar_meses"]
        .map(closing_delta_bucket)
        .pipe(lambda s: pd.Categorical(s, categories=order, ordered=True))
        .value_counts(dropna=False)
        .sort_index()
        .rename_axis("deslocamento_total_meses")
        .reset_index(name="oportunidades")
    )

    summary = pd.DataFrame(
        [
            {
                "amostra_oportunidades": len(result),
                "criterio": "oportunidades presentes nos 3 snapshots; delta = mes_de_fechamento Mai26 - Mar26",
                "media_delta_total_meses": result["delta_total_mai_menos_mar_meses"].mean(),
                "media_abs_delta_total_meses": result["deslocamento_abs_total_meses"].mean(),
                "mediana_abs_delta_total_meses": result["deslocamento_abs_total_meses"].median(),
                "pct_manteve_mes_todos_snapshots": result["manteve_mes_todos_snapshots"].mean() * 100,
            }
        ]
    )
    return result, histogram, summary


def probability_stability(common: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = common[["no_opt", "snapshot_mes", "probabilidade", "cliente_final", "fase", VALUE_COL]].copy()
    wide = data.pivot_table(index="no_opt", columns="snapshot_mes", values="probabilidade", aggfunc="first")
    wide = wide.reindex(columns=SNAPSHOT_ORDER)
    result = wide.reset_index()
    result["delta_mai_menos_mar_prob"] = result["2026-05"] - result["2026-03"]
    result["variacao_max_min_prob"] = wide.max(axis=1).values - wide.min(axis=1).values

    attrs = (
        common.sort_values(["no_opt", "snapshot_mes"])
        .groupby("no_opt", as_index=False)
        .agg(cliente_final=("cliente_final", "last"), fase_mais_recente=("fase", "last"), r_pipeline_mais_recente=(VALUE_COL, "last"))
    )
    result = result.merge(attrs, on="no_opt", how="left")

    top = result.sort_values("variacao_max_min_prob", ascending=False).head(20)
    summary = pd.DataFrame(
        [
            {
                "amostra_oportunidades": len(result),
                "criterio": "oportunidades presentes nos 3 snapshots; variacao = max(probabilidade) - min(probabilidade)",
                "media_variacao_prob": result["variacao_max_min_prob"].mean(),
                "mediana_variacao_prob": result["variacao_max_min_prob"].median(),
                "max_variacao_prob": result["variacao_max_min_prob"].max(),
                "pct_sem_variacao_prob": (result["variacao_max_min_prob"] == 0).mean() * 100,
            }
        ]
    )
    return top, summary


def value_stability(common: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    data = common[["no_opt", "snapshot_mes", VALUE_COL, PROJECT_VALUE_COL, "cliente_final", "fase"]].copy()
    wide = data.pivot_table(index="no_opt", columns="snapshot_mes", values=VALUE_COL, aggfunc="first")
    wide = wide.reindex(columns=SNAPSHOT_ORDER)
    result = wide.reset_index()
    result["delta_mai_menos_mar_r_pipeline"] = result["2026-05"] - result["2026-03"]
    result["variacao_abs_mai_menos_mar_r_pipeline"] = result["delta_mai_menos_mar_r_pipeline"].abs()
    result["variacao_max_min_r_pipeline"] = wide.max(axis=1).values - wide.min(axis=1).values
    result["pct_delta_mai_menos_mar_r_pipeline"] = (
        result["delta_mai_menos_mar_r_pipeline"] / result["2026-03"].replace(0, pd.NA) * 100
    )

    attrs = (
        common.sort_values(["no_opt", "snapshot_mes"])
        .groupby("no_opt", as_index=False)
        .agg(cliente_final=("cliente_final", "last"), fase_mais_recente=("fase", "last"), total_liqliq_mais_recente=(PROJECT_VALUE_COL, "last"))
    )
    result = result.merge(attrs, on="no_opt", how="left")

    bins = [-float("inf"), -1_000_000, -500_000, -100_000, -1, 0, 100_000, 500_000, 1_000_000, float("inf")]
    labels = ["<=-1M", "-1M a -500k", "-500k a -100k", "-100k a -1", "0", "1 a 100k", "100k a 500k", "500k a 1M", ">=1M"]
    distribution = (
        pd.cut(result["delta_mai_menos_mar_r_pipeline"], bins=bins, labels=labels, include_lowest=True)
        .value_counts(dropna=False)
        .sort_index()
        .rename_axis("faixa_delta_r_pipeline")
        .reset_index(name="oportunidades")
    )

    top = result.sort_values("variacao_abs_mai_menos_mar_r_pipeline", ascending=False).head(20)
    summary = pd.DataFrame(
        [
            {
                "amostra_oportunidades": len(result),
                "criterio": "oportunidades presentes nos 3 snapshots; delta = R$ Pipeline Mai26 - Mar26",
                "media_delta_r_pipeline": result["delta_mai_menos_mar_r_pipeline"].mean(),
                "media_abs_delta_r_pipeline": result["variacao_abs_mai_menos_mar_r_pipeline"].mean(),
                "mediana_abs_delta_r_pipeline": result["variacao_abs_mai_menos_mar_r_pipeline"].median(),
                "pct_sem_variacao_r_pipeline": (result["variacao_abs_mai_menos_mar_r_pipeline"] == 0).mean() * 100,
            }
        ]
    )
    return top, distribution, summary


def concentration(opp: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    percentiles = (
        opp.groupby("snapshot_mes")[VALUE_COL]
        .quantile([0.50, 0.75, 0.90, 0.99])
        .unstack()
        .rename(columns={0.50: "p50", 0.75: "p75", 0.90: "p90", 0.99: "p99"})
        .reset_index()
    )

    top10_share_rows = []
    for snapshot, group in opp.groupby("snapshot_mes"):
        total = group[VALUE_COL].sum()
        top10 = group.nlargest(10, VALUE_COL)[VALUE_COL].sum()
        top10_share_rows.append(
            {
                "snapshot_mes": snapshot,
                "oportunidades": group["no_opt"].nunique(),
                "total_r_pipeline": total,
                "top10_r_pipeline": top10,
                "pct_total_top10": (top10 / total * 100) if total else pd.NA,
            }
        )
    top10_share = pd.DataFrame(top10_share_rows)

    top_clients = (
        opp.groupby("cliente_final", dropna=False)
        .agg(
            r_pipeline_total=(VALUE_COL, "sum"),
            total_liqliq_total=(PROJECT_VALUE_COL, "sum"),
            oportunidades=("no_opt", "nunique"),
            snapshots=("snapshot_mes", "nunique"),
        )
        .reset_index()
        .sort_values("r_pipeline_total", ascending=False)
        .head(10)
    )
    return percentiles, top10_share, top_clients


def rotation(opp: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sets = {
        snapshot: set(opp.loc[opp["snapshot_mes"] == snapshot, "no_opt"].dropna())
        for snapshot in SNAPSHOT_ORDER
    }
    transition_rows = []
    exits_detail = []

    for prev, curr in zip(SNAPSHOT_ORDER[:-1], SNAPSHOT_ORDER[1:]):
        previous_ids = sets[prev]
        current_ids = sets[curr]
        entries = current_ids - previous_ids
        exits = previous_ids - current_ids
        kept = previous_ids & current_ids

        transition_rows.append(
            {
                "transicao": f"{prev} -> {curr}",
                "base_mes_anterior": len(previous_ids),
                "base_mes_atual": len(current_ids),
                "mantidas": len(kept),
                "entradas": len(entries),
                "saidas": len(exits),
                "pct_entradas_sobre_mes_atual": len(entries) / len(current_ids) * 100 if current_ids else pd.NA,
                "pct_saidas_sobre_mes_anterior": len(exits) / len(previous_ids) * 100 if previous_ids else pd.NA,
            }
        )

        exited = opp[(opp["snapshot_mes"] == prev) & (opp["no_opt"].isin(exits))].copy()
        exited["transicao"] = f"{prev} -> {curr}"
        exits_detail.append(exited)

    transitions = pd.DataFrame(transition_rows)
    exits = pd.concat(exits_detail, ignore_index=True) if exits_detail else pd.DataFrame()

    exits_profile = (
        exits.groupby(["transicao", "fase"], dropna=False)
        .agg(oportunidades=("no_opt", "nunique"), r_pipeline_total=(VALUE_COL, "sum"), total_liqliq_total=(PROJECT_VALUE_COL, "sum"))
        .reset_index()
        .sort_values(["transicao", "r_pipeline_total"], ascending=[True, False])
        if not exits.empty
        else pd.DataFrame()
    )

    exits_top = (
        exits[["transicao", "no_opt", "cliente_final", "fase", VALUE_COL, PROJECT_VALUE_COL]]
        .sort_values(["transicao", VALUE_COL], ascending=[True, False])
        .groupby("transicao")
        .head(10)
        if not exits.empty
        else pd.DataFrame()
    )
    return transitions, exits_profile, exits_top


def duplicate_impact(item: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    duplicate_mask = item.duplicated(keep="first")
    duplicated_rows = item[duplicate_mask].copy()

    by_snapshot = (
        duplicated_rows.groupby("snapshot_mes", dropna=False)
        .agg(
            duplicatas_exatas=("no_opt", "size"),
            oportunidades_afetadas=("no_opt", "nunique"),
            impacto_r_pipeline=(VALUE_COL, "sum"),
            impacto_total_liqliq=(PROJECT_VALUE_COL, "sum"),
        )
        .reset_index()
        if not duplicated_rows.empty
        else pd.DataFrame()
    )

    total_before = item[VALUE_COL].sum()
    total_after = item.drop_duplicates()[VALUE_COL].sum()
    summary = pd.DataFrame(
        [
            {
                "linhas_item": len(item),
                "duplicatas_exatas": int(duplicate_mask.sum()),
                "criterio": "duplicata exata de linha; impacto = soma das linhas duplicadas que inflariam uma soma direta",
                "r_pipeline_com_duplicatas": total_before,
                "r_pipeline_sem_duplicatas": total_after,
                "impacto_r_pipeline": total_before - total_after,
                "pct_impacto_r_pipeline": (total_before - total_after) / total_before * 100 if total_before else pd.NA,
            }
        ]
    )
    return by_snapshot, summary


def write_csvs(
    output_dir: Path,
    closing_detail: pd.DataFrame,
    closing_histogram: pd.DataFrame,
    probability_top: pd.DataFrame,
    value_top: pd.DataFrame,
    value_distribution: pd.DataFrame,
    concentration_percentiles: pd.DataFrame,
    top10_share: pd.DataFrame,
    top_clients: pd.DataFrame,
    transitions: pd.DataFrame,
    exits_profile: pd.DataFrame,
    exits_top: pd.DataFrame,
    duplicate_by_snapshot: pd.DataFrame,
    duplicate_summary: pd.DataFrame,
) -> None:
    outputs = {
        "instabilidade_fechamento_98_oportunidades.csv": closing_detail,
        "histograma_deslocamento_fechamento.csv": closing_histogram,
        "top_variacao_probabilidade.csv": probability_top,
        "top_variacao_r_pipeline.csv": value_top,
        "distribuicao_variacao_r_pipeline.csv": value_distribution,
        "concentracao_percentis_r_pipeline.csv": concentration_percentiles,
        "concentracao_top10_share.csv": top10_share,
        "ranking_top10_clientes_valor.csv": top_clients,
        "rotatividade_transicoes.csv": transitions,
        "rotatividade_perfil_saidas_fase.csv": exits_profile,
        "rotatividade_top_saidas.csv": exits_top,
        "duplicatas_por_snapshot.csv": duplicate_by_snapshot,
        "duplicatas_impacto_financeiro.csv": duplicate_summary,
    }
    for filename, df in outputs.items():
        df.to_csv(output_dir / filename, index=False, encoding="utf-8-sig")


def build_report(output_dir: Path) -> str:
    item, opp = load_data(output_dir)
    common = opportunities_in_all_snapshots(opp)

    closing_detail, closing_histogram, closing_summary = closing_month_stability(common)
    probability_top, probability_summary = probability_stability(common)
    value_top, value_distribution, value_summary = value_stability(common)
    concentration_percentiles, top10_share, top_clients = concentration(opp)
    transitions, exits_profile, exits_top = rotation(opp)
    duplicate_by_snapshot, duplicate_summary = duplicate_impact(item)

    write_csvs(
        output_dir,
        closing_detail,
        closing_histogram,
        probability_top,
        value_top,
        value_distribution,
        concentration_percentiles,
        top10_share,
        top_clients,
        transitions,
        exits_profile,
        exits_top,
        duplicate_by_snapshot,
        duplicate_summary,
    )

    facts = [
        f"Amostra de oportunidades presentes nos 3 snapshots: {common['no_opt'].nunique()} oportunidades.",
        f"Amostra oportunidade-snapshot total: {len(opp)} registros.",
        f"Amostra item/produto total: {len(item)} linhas.",
        "Realizado nao esta disponivel; as metricas abaixo sao indiretas.",
        "Movimentacao de carteira foi medida por presenca/ausencia de `no_opt`, nao por classificacao manual.",
    ]

    hypotheses = [
        "Mudancas de mes de fechamento podem indicar instabilidade da previsao comercial do KAM.",
        "Alta concentracao de valor pode amplificar erro agregado mesmo com poucas oportunidades variando.",
        "Saidas entre snapshots podem representar ganho, perda, cancelamento, limpeza de pipeline ou ausencia temporaria; a base atual nao diferencia sozinha.",
    ]

    questions = [
        "Quando uma oportunidade some de um snapshot, qual evento operacional isso representa no CRM?",
        "`R$ Pipeline` deve ser tratado como valor ponderado oficial do forecast ou apenas apoio da planilha?",
        "`Total liqliq` e o melhor campo para valor total de projeto nao ponderado?",
        "Duplicatas exatas devem ser removidas antes de qualquer soma oficial?",
        "Qual regra oficial separa ganho, perda, cancelamento e oportunidade ainda em aberto?",
    ]

    lines = [
        "# Metricas Indiretas de Instabilidade - Forecast VBR-CI",
        "",
        "Relatorio gerado a partir de `base_item_limpa.csv` e `base_oportunidade_snapshot.csv`.",
        "Nao usa realizado e nao calcula assertividade final.",
        "",
        "## 1. Deslocamento de mes de fechamento",
        "",
        "### Resumo",
        "- Criterio: oportunidades presentes nos 3 snapshots; delta total = `mes_de_fechamento` Mai26 menos Mar26, em meses.",
        "- `Manteve data` significa mesmo mes de fechamento em Mar26, Abr26 e Mai26.",
        "",
        "### Codigo Python usando pandas",
        "```python",
        "common = opportunities_in_all_snapshots(opp)",
        "closing_detail, closing_histogram, closing_summary = closing_month_stability(common)",
        "```",
        "",
        "### Estatisticas",
        markdown_table(closing_summary),
        "",
        "### Distribuicao dos deslocamentos",
        markdown_table(closing_histogram),
        "",
        "### Interpretacao objetiva",
        "- A metrica indica estabilidade ou mudanca do mes previsto pelo KAM entre snapshots.",
        "- O sinal positivo/negativo mede deslocamento calendario, sem rotular como postergado/antecipado como regra de negocio.",
        "",
        "### Limitacoes",
        "- Usa apenas as 98 oportunidades presentes nos 3 snapshots; oportunidades que entraram/sairam ficam fora desta etapa.",
        "",
        "## 2. Estabilidade de probabilidade",
        "",
        "### Resumo",
        "- Criterio: variacao = max(probabilidade) - min(probabilidade) por oportunidade nas 98 comuns.",
        "",
        "### Codigo Python usando pandas",
        "```python",
        "probability_top, probability_summary = probability_stability(common)",
        "```",
        "",
        "### Estatisticas",
        markdown_table(probability_summary),
        "",
        "### Oportunidades com maior variacao",
        markdown_table(probability_top, max_rows=20),
        "",
        "### Interpretacao objetiva",
        "- Probabilidade estavel sugere pouca revisao de chance comercial entre snapshots.",
        "- Maiores variacoes devem ser tratadas como casos para investigacao, nao como erro confirmado.",
        "",
        "### Limitacoes",
        "- Probabilidade pode ser regra padrao da fase, julgamento do KAM ou formula da planilha; precisa validacao.",
        "",
        "## 3. Estabilidade de valor",
        "",
        "### Resumo",
        "- Criterio: delta = `R$ Pipeline` Mai26 menos Mar26 por oportunidade nas 98 comuns.",
        "",
        "### Codigo Python usando pandas",
        "```python",
        "value_top, value_distribution, value_summary = value_stability(common)",
        "```",
        "",
        "### Estatisticas",
        markdown_table(value_summary),
        "",
        "### Distribuicao das variacoes",
        markdown_table(value_distribution),
        "",
        "### Maiores variacoes absolutas",
        markdown_table(value_top, max_rows=20),
        "",
        "### Interpretacao objetiva",
        "- Variacao de valor mede instabilidade de escopo, quantidade, preco ou probabilidade ponderada no pipeline.",
        "- Como `R$ Pipeline` pode ser ponderado, variacao de valor pode refletir probabilidade e valor base simultaneamente.",
        "",
        "### Limitacoes",
        "- Sem campo de realizado, a variacao de valor nao mede erro; mede instabilidade da carteira prevista.",
        "",
        "## 4. Concentracao",
        "",
        "### Resumo",
        "- Criterio: percentis e concentracao calculados em nivel oportunidade-snapshot usando `R$ Pipeline`.",
        "",
        "### Codigo Python usando pandas",
        "```python",
        "concentration_percentiles, top10_share, top_clients = concentration(opp)",
        "```",
        "",
        "### Percentis de R$ Pipeline por snapshot",
        markdown_table(concentration_percentiles),
        "",
        "### Percentual do total nas 10 maiores oportunidades",
        markdown_table(top10_share),
        "",
        "### Ranking dos 10 clientes com maior valor",
        markdown_table(top_clients, max_rows=10),
        "",
        "### Interpretacao objetiva",
        "- Alta concentracao indica que poucas oportunidades podem dominar a variacao agregada do forecast.",
        "",
        "### Limitacoes",
        "- Ranking por cliente soma snapshots; nao deve ser interpretado como receita unica sem remover repeticao temporal.",
        "",
        "## 5. Rotatividade",
        "",
        "### Resumo",
        "- Criterio: entrada = `no_opt` aparece no snapshot atual e nao no anterior; saida = aparece no anterior e nao no atual.",
        "",
        "### Codigo Python usando pandas",
        "```python",
        "transitions, exits_profile, exits_top = rotation(opp)",
        "```",
        "",
        "### Percentual de entradas e saidas",
        markdown_table(transitions),
        "",
        "### Perfil das saidas por fase",
        markdown_table(exits_profile),
        "",
        "### Top oportunidades que sairam por valor",
        markdown_table(exits_top, max_rows=20),
        "",
        "### Interpretacao objetiva",
        "- Rotatividade mostra troca de composicao da carteira entre snapshots.",
        "- Saida nao significa perda, ganho ou cancelamento sem regra validada.",
        "",
        "### Limitacoes",
        "- A base atual nao informa a causa da saida do snapshot.",
        "",
        "## 6. Duplicatas",
        "",
        "### Resumo",
        "- Criterio: duplicata exata de linha na base item/produto; impacto financeiro = soma das linhas duplicadas em `R$ Pipeline`.",
        "",
        "### Codigo Python usando pandas",
        "```python",
        "duplicate_by_snapshot, duplicate_summary = duplicate_impact(item)",
        "```",
        "",
        "### Distribuicao por snapshot",
        markdown_table(duplicate_by_snapshot),
        "",
        "### Impacto financeiro estimado",
        markdown_table(duplicate_summary),
        "",
        "### Interpretacao objetiva",
        "- O impacto mostra quanto uma soma direta por item pode ser inflada se duplicatas exatas nao forem removidas.",
        "",
        "### Limitacoes",
        "- Duplicata exata nao cobre duplicidade semantica; linhas parecidas, mas nao identicas, exigem regra adicional.",
        "",
        "## Fechamento",
        "",
        "### Fatos observados",
        "\n".join(f"- {fact}" for fact in facts),
        "",
        "### Hipoteses",
        "\n".join(f"- {hypothesis}" for hypothesis in hypotheses),
        "",
        "### Perguntas em aberto",
        "\n".join(f"- {question}" for question in questions),
        "",
    ]

    report = "\n".join(lines)
    (output_dir / "instability_metrics_report.md").write_text(report, encoding="utf-8-sig")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Metricas indiretas de instabilidade do forecast VBR-CI.")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"), help="Pasta com os outputs da EDA.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_report(args.output_dir)
    print(f"Relatorio gerado em: {args.output_dir / 'instability_metrics_report.md'}")
    print(f"Tamanho do relatorio: {len(report)} caracteres")


if __name__ == "__main__":
    main()
