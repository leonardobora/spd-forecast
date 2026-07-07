from pathlib import Path

import pandas as pd


ROOT = Path(".")
OUTPUT_DIR = ROOT / "outputs"
ITEM_FILE = OUTPUT_DIR / "base_item_limpa.csv"
OPP_FILE = OUTPUT_DIR / "base_oportunidade_snapshot.csv"
REPORT_FILE = OUTPUT_DIR / "analise_forecast_avancada_report.md"
DICT_FILE = OUTPUT_DIR / "analise_dicionario_operacional.csv"
PIPELINE_FILE = OUTPUT_DIR / "analise_distribuicoes_pipeline.csv"
CONSISTENCY_FILE = OUTPUT_DIR / "analise_consistencia_comercial.csv"
TODAY = pd.Timestamp("2026-07-07")


def md_table(df, max_rows=20):
    if df is None or df.empty:
        return "_Sem registros._"
    out = df.head(max_rows).copy()
    out = out.fillna("")
    cols = list(out.columns)
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for _, row in out.iterrows():
        vals = []
        for col in cols:
            val = row[col]
            if isinstance(val, float):
                val = f"{val:,.4f}".rstrip("0").rstrip(".")
            vals.append(str(val).replace("\n", " ").replace("|", "\\|"))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def pct(series):
    return series.mul(100).round(2)


def role_for(col):
    c = col.lower()
    if c in {"no_opt", "nome_de_cotacao", "arquivo_origem", "snapshot_ordem"}:
        return "Identificador"
    if "data" in c or "mes" in c or "snapshot" in c or c == "prazo":
        return "Temporal"
    if any(x in c for x in ["total", "pipeline", "r_", "quantidade", "sl"]):
        return "Financeiro"
    if c in {"fase", "status", "probabilidade"} or c.startswith("fase_opt"):
        return "Pipeline"
    if c in {"cliente_final"}:
        return "Cliente"
    if "produto" in c:
        return "Produto"
    if "forecast" in c:
        return "Forecast"
    if c in {"proprietario_da_oportunidade", "departamento", "nome_do_projeto", "sincronizando"}:
        return "Comercial"
    return "Comercial"


def flags_for(col, role):
    c = col.lower()
    can_forecast = c in {
        "probabilidade",
        "fase",
        "status",
        "mes_de_fechamento",
        "mes_de_fechamento_dt",
        "data_forecast",
        "data_forecast_dt",
        "pipeline",
        "r_pipeline",
        "total_liqliq",
    }
    can_error = c in {
        "r_pipeline",
        "pipeline",
        "total_liqliq",
        "mes_de_fechamento_dt",
        "data_forecast_dt",
        "data_atual_dt",
        "data_atual_jun26_dt",
        "data_atual_jul26_dt",
    }
    can_segment = role in {
        "Temporal",
        "Comercial",
        "Pipeline",
        "Cliente",
        "Produto",
        "Forecast",
        "Status",
    } and c not in {"snapshot_ordem"}
    return can_forecast, can_error, can_segment


def freq_table(df, col, value_col=None, top=15):
    if pd.api.types.is_numeric_dtype(df[col]):
        base = df[col].round(6).astype(object).where(df[col].notna(), "(nulo)")
    else:
        base = df[col].fillna("(nulo)")
    out = base.value_counts(dropna=False).head(top).reset_index()
    out.columns = [col, "frequencia_abs"]
    out["frequencia_rel_pct"] = (out["frequencia_abs"] / len(df) * 100).round(2)
    if value_col and value_col in df:
        sums = df.assign(_key=base).groupby("_key", dropna=False)[value_col].sum()
        out[f"{value_col}_soma"] = out[col].map(sums).round(2)
        total = sums.sum()
        out[f"{value_col}_share_pct"] = (
            out[f"{value_col}_soma"] / total * 100 if total else 0
        ).round(2)
    return out


def date_quality(df, col):
    s = pd.to_datetime(df[col], errors="coerce")
    invalid = s.isna() & df[col].notna()
    return {
        "campo": col,
        "nulos_pct": round(df[col].isna().mean() * 100, 2),
        "invalidas_qtd": int(invalid.sum()),
        "futuras_qtd": int((s > TODAY).sum()),
        "min": s.min().date().isoformat() if s.notna().any() else "",
        "max": s.max().date().isoformat() if s.notna().any() else "",
    }


def examples(df, mask, cols, n=5):
    return df.loc[mask, cols].head(n).copy()


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    items = pd.read_csv(ITEM_FILE)
    opp = pd.read_csv(OPP_FILE)

    for df in [items, opp]:
        for col in df.columns:
            if col.endswith("_dt") or col in {"data_forecast", "mes_de_fechamento"}:
                df[col] = pd.to_datetime(df[col], errors="coerce")

    # A - dictionary
    dict_rows = []
    for col in items.columns:
        role = role_for(col)
        can_forecast, can_error, can_segment = flags_for(col, role)
        dict_rows.append(
            {
                "coluna": col,
                "tipo_dado": str(items[col].dtype),
                "cardinalidade": int(items[col].nunique(dropna=True)),
                "nulos_pct": round(items[col].isna().mean() * 100, 2),
                "papel_analitico": role,
                "pode_usar_forecast": "Sim" if can_forecast else "Nao",
                "pode_usar_calculo_erro": "Sim" if can_error else "Nao",
                "pode_usar_segmentacao": "Sim" if can_segment else "Nao",
            }
        )
    dict_df = pd.DataFrame(dict_rows)
    dict_df.to_csv(DICT_FILE, index=False, encoding="utf-8-sig")

    # B - granularity
    by_opp_snap = items.groupby(["snapshot_mes", "no_opt"], dropna=False)
    gran_summary = pd.DataFrame(
        {
            "metrica": [
                "linhas_item",
                "oportunidades_unicas",
                "oportunidade_snapshots",
                "snapshots",
                "produtos_unicos",
                "clientes_unicos",
                "proprietarios_unicos",
            ],
            "valor": [
                len(items),
                items["no_opt"].nunique(),
                by_opp_snap.ngroups,
                items["snapshot_mes"].nunique(),
                items["produto_codigo_do_produto"].nunique(),
                items["cliente_final"].nunique(),
                items["proprietario_da_oportunidade"].nunique(),
            ],
        }
    )
    gran_stats = by_opp_snap.agg(
        linhas=("no_opt", "size"),
        produtos=("produto_codigo_do_produto", "nunique"),
        clientes=("cliente_final", "nunique"),
        proprietarios=("proprietario_da_oportunidade", "nunique"),
        cotacoes=("nome_de_cotacao", "nunique"),
    ).reset_index()
    gran_desc = gran_stats[["linhas", "produtos", "clientes", "proprietarios", "cotacoes"]].describe(
        percentiles=[0.25, 0.5, 0.75, 0.9, 0.95]
    ).round(2)

    # C - pipeline
    pipeline_tables = []
    for col in ["fase", "status", "probabilidade", "cliente_final", "proprietario_da_oportunidade"]:
        tbl = freq_table(opp, col, "r_pipeline", top=20)
        tbl.insert(0, "dimensao", col)
        pipeline_tables.append(tbl)
    pipeline_df = pd.concat(pipeline_tables, ignore_index=True)
    pipeline_df.to_csv(PIPELINE_FILE, index=False, encoding="utf-8-sig")
    client_conc = freq_table(opp, "cliente_final", "r_pipeline", top=10)
    owner_conc = freq_table(opp, "proprietario_da_oportunidade", "r_pipeline", top=10)

    # D - forecast fields
    prob = opp["probabilidade"]
    prob_stats = prob.describe(percentiles=[0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]).round(4)
    prob_dist = freq_table(opp, "probabilidade", "r_pipeline", top=20)
    prob_outside = opp[prob.notna() & ((prob < 0) | (prob > 1))]
    date_df = pd.DataFrame(
        [
            date_quality(opp, "data_forecast_dt"),
            date_quality(opp, "mes_de_fechamento_dt"),
            date_quality(opp, "data_atual_dt"),
            date_quality(opp, "data_atual_jun26_dt"),
            date_quality(opp, "data_atual_jul26_dt"),
        ]
    )
    opp["diff_forecast_fechamento_dias"] = (
        opp["data_forecast_dt"] - opp["mes_de_fechamento_dt"]
    ).dt.days
    diff_desc = opp["diff_forecast_fechamento_dias"].describe(
        percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]
    ).round(2)
    diff_bins = pd.cut(
        opp["diff_forecast_fechamento_dias"],
        bins=[-9999, -61, -31, -1, 0, 30, 60, 9999],
        labels=["<= -62", "-61 a -32", "-31 a -1", "0", "1 a 30", "31 a 60", ">= 61"],
    ).value_counts(dropna=False).sort_index().reset_index()
    diff_bins.columns = ["faixa_diff_dias", "frequencia_abs"]
    diff_bins["frequencia_rel_pct"] = (diff_bins["frequencia_abs"] / len(opp) * 100).round(2)

    # E - commercial consistency. These are flags for review, not errors.
    high = opp["probabilidade"] >= 0.7
    low = opp["probabilidade"] <= 0.4
    initial_phase = opp["fase"].astype(str).str.contains("prospec", case=False, na=False)
    final_phase = opp["fase"].astype(str).str.contains("negocia", case=False, na=False)
    rejected = opp["status"].astype(str).str.contains("Rejeitado", case=False, na=False)
    approved = opp["status"].astype(str).str.contains("Aprovado", case=False, na=False)
    consistency_rules = [
        ("status_aprovado_sem_mes_fechamento", approved & opp["mes_de_fechamento_dt"].isna()),
        ("status_rejeitado_em_fase_negociacao", rejected & final_phase),
        ("probabilidade_alta_em_prospeccao", high & initial_phase),
        ("probabilidade_baixa_em_negociacao", low & final_phase),
        ("data_forecast_anterior_mes_fechamento", opp["data_forecast_dt"] < opp["mes_de_fechamento_dt"]),
    ]
    cons_rows = []
    for name, mask in consistency_rules:
        cons_rows.append(
            {
                "regra_revisao": name,
                "quantidade": int(mask.sum()),
                "percentual_opp_snapshot": round(mask.mean() * 100, 2),
            }
        )
    cons_df = pd.DataFrame(cons_rows)
    cons_df.to_csv(CONSISTENCY_FILE, index=False, encoding="utf-8-sig")
    ex_cols = [
        "snapshot_mes",
        "no_opt",
        "cliente_final",
        "proprietario_da_oportunidade",
        "fase",
        "status",
        "probabilidade",
        "mes_de_fechamento_dt",
        "data_forecast_dt",
        "r_pipeline",
    ]
    cons_examples = {
        name: examples(opp, mask, ex_cols)
        for name, mask in consistency_rules
        if mask.any()
    }

    # F - future accuracy readiness
    readiness = pd.DataFrame(
        [
            {
                "item": "Forecast previsto",
                "avaliacao": "SIM",
                "justificativa": "Ha campos de probabilidade, data_forecast_dt, mes_de_fechamento_dt, pipeline e r_pipeline.",
            },
            {
                "item": "Resultado realizado",
                "avaliacao": "INCERTO",
                "justificativa": "Nao ha campo explicito de ganho/perda ou valor realizado; status contem Aprovado/Rejeitado, mas isso nao prova realizacao comercial.",
            },
            {
                "item": "Data prevista",
                "avaliacao": "SIM",
                "justificativa": "Campos data_forecast_dt e mes_de_fechamento_dt estao preenchidos na base de oportunidade-snapshot.",
            },
            {
                "item": "Data realizada",
                "avaliacao": "INCERTO",
                "justificativa": "Campos data_atual* existem, mas nao ha evidencia direta de que sejam data realizada de fechamento.",
            },
        ]
    )

    # G - history
    hist = opp.sort_values(["no_opt", "snapshot_ordem"])
    changes = hist.groupby("no_opt").agg(
        snapshots=("snapshot_mes", "nunique"),
        prob_distintas=("probabilidade", "nunique"),
        fases_distintas=("fase", "nunique"),
        status_distintos=("status", "nunique"),
        meses_fechamento_distintos=("mes_de_fechamento_dt", "nunique"),
        data_forecast_distintas=("data_forecast_dt", "nunique"),
        r_pipeline_distintos=("r_pipeline", "nunique"),
    ).reset_index()
    hist_summary = pd.DataFrame(
        {
            "evidencia": [
                "oportunidades_unicas",
                "oportunidades_com_mais_de_um_snapshot",
                "oportunidades_com_mudanca_probabilidade",
                "oportunidades_com_mudanca_fase",
                "oportunidades_com_mudanca_status",
                "oportunidades_com_mudanca_mes_fechamento",
                "oportunidades_com_mudanca_data_forecast",
                "oportunidades_com_mudanca_r_pipeline",
            ],
            "quantidade": [
                changes["no_opt"].nunique(),
                int((changes["snapshots"] > 1).sum()),
                int((changes["prob_distintas"] > 1).sum()),
                int((changes["fases_distintas"] > 1).sum()),
                int((changes["status_distintos"] > 1).sum()),
                int((changes["meses_fechamento_distintos"] > 1).sum()),
                int((changes["data_forecast_distintas"] > 1).sum()),
                int((changes["r_pipeline_distintos"] > 1).sum()),
            ],
        }
    )
    hist_examples = changes[
        (changes["snapshots"] > 1)
        & (
            (changes["prob_distintas"] > 1)
            | (changes["fases_distintas"] > 1)
            | (changes["meses_fechamento_distintos"] > 1)
            | (changes["r_pipeline_distintos"] > 1)
        )
    ].head(10)

    code_blocks = {
        "A": "dict_df = pd.DataFrame([{...} for col in items.columns])\ndict_df.to_csv('analise_dicionario_operacional.csv', index=False)",
        "B": "by_opp_snap = items.groupby(['snapshot_mes', 'no_opt'])\ngran_stats = by_opp_snap.agg(linhas=('no_opt','size'), produtos=('produto_codigo_do_produto','nunique'))",
        "C": "freq = opp[col].value_counts(dropna=False)\nshare_valor = opp.groupby(col)['r_pipeline'].sum() / opp['r_pipeline'].sum()",
        "D": "prob_stats = opp['probabilidade'].describe(percentiles=[.01,.05,.1,.25,.5,.75,.9,.95,.99])\nopp['diff_forecast_fechamento_dias'] = (opp['data_forecast_dt'] - opp['mes_de_fechamento_dt']).dt.days",
        "E": "flags = {\n  'probabilidade_alta_em_prospeccao': (opp['probabilidade'] >= .7) & fase_inicial,\n  'probabilidade_baixa_em_negociacao': (opp['probabilidade'] <= .4) & fase_final,\n}",
        "F": "readiness = pd.DataFrame([...])  # SIM/NAO/INCERTO por campo necessario",
        "G": "changes = opp.groupby('no_opt').agg(snapshots=('snapshot_mes','nunique'), prob_distintas=('probabilidade','nunique'), fases_distintas=('fase','nunique'))",
    }

    lines = []
    lines.append("# Analise exploratoria avancada - Forecast VBR-CI")
    lines.append("")
    lines.append("Base usada: `base_item_limpa.csv` para granularidade de itens e `base_oportunidade_snapshot.csv` para metricas em nivel de oportunidade-snapshot.")
    lines.append(f"Data de referencia para datas futuras: {TODAY.date().isoformat()}.")
    lines.append("")
    lines.append("## ETAPA A - Dicionario de dados operacional")
    lines.append("### Resumo executivo")
    lines.append(f"Foram avaliadas {len(dict_df)} colunas. O dicionario completo foi salvo em `{DICT_FILE.name}`.")
    lines.append("### Estatisticas calculadas")
    lines.append(md_table(dict_df, max_rows=35))
    lines.append("### Codigo Python (pandas)")
    lines.append(f"```python\n{code_blocks['A']}\n```")
    lines.append("### Interpretacao objetiva")
    lines.append("Campos de forecast observaveis: probabilidade, fase, status, datas de forecast/fechamento e valores de pipeline. Campos de erro existem apenas parcialmente, pois nao ha realizado explicito.")
    lines.append("### Limitacoes")
    lines.append("A classificacao do papel analitico e operacional; ela nao substitui validacao de negocio sobre o significado de cada coluna.")
    lines.append("")

    lines.append("## ETAPA B - Entendimento da granularidade")
    lines.append("### Resumo executivo")
    lines.append("A menor unidade observada e uma linha de item/produto de oportunidade dentro de um snapshot mensal. A base agregada representa oportunidade-snapshot.")
    lines.append("### Estatisticas calculadas")
    lines.append(md_table(gran_summary))
    lines.append("")
    lines.append(md_table(gran_desc.reset_index().rename(columns={'index': 'estatistica'})))
    lines.append("### Codigo Python (pandas)")
    lines.append(f"```python\n{code_blocks['B']}\n```")
    lines.append("### Interpretacao objetiva")
    lines.append("Uma linha nao deve ser tratada como oportunidade inteira, porque uma mesma oportunidade aparece em multiplas linhas de produto e em multiplos snapshots.")
    lines.append("Unidade correta para medir forecast: oportunidade-snapshot, agregando itens de produto antes de medir valor/probabilidade por oportunidade e por mes de snapshot.")
    lines.append("### Limitacoes")
    lines.append("Sem um identificador de linha de item, a unicidade exata do item depende da combinacao de oportunidade, snapshot, cotacao, produto e atributos financeiros.")
    lines.append("")

    lines.append("## ETAPA C - Analise de pipeline")
    lines.append("### Resumo executivo")
    lines.append("As distribuicoes foram calculadas em oportunidade-snapshot para evitar inflar clientes/proprietarios com numero de itens.")
    lines.append("### Estatisticas calculadas - fase/status/probabilidade")
    lines.append(md_table(pipeline_df[pipeline_df["dimensao"].isin(["fase", "status", "probabilidade"])], max_rows=60))
    lines.append("### Concentracao por cliente")
    lines.append(md_table(client_conc, max_rows=10))
    lines.append("### Concentracao por proprietario")
    lines.append(md_table(owner_conc, max_rows=10))
    lines.append("### Codigo Python (pandas)")
    lines.append(f"```python\n{code_blocks['C']}\n```")
    lines.append("### Interpretacao objetiva")
    lines.append(f"Top 10 clientes concentram {client_conc['r_pipeline_share_pct'].sum():.2f}% do R$ Pipeline observado nos registros exibidos; top 10 proprietarios concentram {owner_conc['r_pipeline_share_pct'].sum():.2f}%.")
    lines.append("### Limitacoes")
    lines.append("Concentracao financeira usa `r_pipeline`; se este campo ja estiver ponderado por probabilidade, ele nao equivale a valor bruto realizado.")
    lines.append("")

    lines.append("## ETAPA D - Qualidade dos campos de forecast")
    lines.append("### Resumo executivo")
    lines.append("Probabilidade foi avaliada no intervalo esperado de 0 a 1; datas foram avaliadas quanto a nulos, invalidas, futuras e diferenca entre forecast e fechamento.")
    lines.append("### Estatisticas calculadas - probabilidade")
    lines.append(md_table(prob_stats.reset_index().rename(columns={"index": "estatistica", "probabilidade": "valor"}), max_rows=20))
    lines.append("### Distribuicao de probabilidade")
    lines.append(md_table(prob_dist, max_rows=20))
    lines.append(f"Valores fora de 0-1: {len(prob_outside)}.")
    lines.append("### Qualidade de datas")
    lines.append(md_table(date_df, max_rows=10))
    lines.append("### Diferenca entre Data Forecast e Mes de Fechamento")
    lines.append(md_table(diff_desc.reset_index().rename(columns={'index': 'estatistica', 'diff_forecast_fechamento_dias': 'dias'})))
    lines.append(md_table(diff_bins))
    lines.append("### Codigo Python (pandas)")
    lines.append(f"```python\n{code_blocks['D']}\n```")
    lines.append("### Interpretacao objetiva")
    lines.append("Diferencas positivas indicam data_forecast posterior ao mes_de_fechamento; diferencas negativas indicam data_forecast anterior. Isso e uma diferenca operacional, nao um erro confirmado.")
    lines.append("### Limitacoes")
    lines.append("Datas `data_atual*` nao foram interpretadas como realizado por falta de evidencia direta.")
    lines.append("")

    lines.append("## ETAPA E - Analise de consistencia comercial")
    lines.append("### Resumo executivo")
    lines.append("As regras abaixo sao flags para revisao. Nenhuma foi classificada como erro sem validacao de negocio.")
    lines.append("### Estatisticas calculadas")
    lines.append(md_table(cons_df))
    for name, ex in cons_examples.items():
        lines.append(f"### Exemplos - {name}")
        lines.append(md_table(ex, max_rows=5))
    lines.append("### Codigo Python (pandas)")
    lines.append(f"```python\n{code_blocks['E']}\n```")
    lines.append("### Interpretacao objetiva")
    lines.append("A maior parte das flags depende da definicao de fase inicial/final e do significado comercial de status Aprovado/Rejeitado.")
    lines.append("### Limitacoes")
    lines.append("Nao existem status explicitos de ganho/perda nos valores observados, portanto regras de ganho/perda nao foram assumidas.")
    lines.append("")

    lines.append("## ETAPA F - Preparacao para futuro calculo de assertividade")
    lines.append("### Resumo executivo")
    lines.append("A base permite estruturar forecast previsto, mas nao comprova resultado realizado nem data realizada.")
    lines.append("### Estatisticas calculadas")
    lines.append(md_table(readiness))
    lines.append("### Codigo Python (pandas)")
    lines.append(f"```python\n{code_blocks['F']}\n```")
    lines.append("### Interpretacao objetiva")
    lines.append("Para MAE, Bias, MAPE, Hit Rate e Forecast Accuracy % faltam valor realizado, status final ganho/perda validado, data real de fechamento e regra de comparacao entre snapshot e realizado.")
    lines.append("### Limitacoes")
    lines.append("Usar `Aprovado` ou `Rejeitado` como realizado sem validacao pode contaminar todas as metricas de assertividade.")
    lines.append("")

    lines.append("## ETAPA G - Avaliacao de historico")
    lines.append("### Resumo executivo")
    lines.append("Ha evidencia de historico parcial: existem tres snapshots mensais e oportunidades repetidas com mudancas em campos de pipeline. Nao ha evidencia de historico completo do ciclo de vida.")
    lines.append("### Estatisticas calculadas")
    lines.append(md_table(hist_summary))
    lines.append("### Exemplos de oportunidades com mudancas")
    lines.append(md_table(hist_examples, max_rows=10))
    lines.append("### Codigo Python (pandas)")
    lines.append(f"```python\n{code_blocks['G']}\n```")
    lines.append("### Interpretacao objetiva")
    lines.append("Classificacao: historico parcial. A base nao e snapshot unico, mas tambem nao cobre necessariamente todos os ciclos, alteracoes e resultados finais.")
    lines.append("### Limitacoes")
    lines.append("Apenas snapshots Mar/2026, Abr/2026 e Mai/2026 foram observados nos CSVs disponiveis.")
    lines.append("")

    lines.append("# FATOS OBSERVADOS")
    lines.append(f"- `base_item_limpa.csv` contem {len(items)} linhas e {items['no_opt'].nunique()} oportunidades unicas.")
    lines.append(f"- `base_oportunidade_snapshot.csv` contem {len(opp)} registros de oportunidade-snapshot e {opp['no_opt'].nunique()} oportunidades unicas.")
    lines.append(f"- Snapshots observados: {', '.join(map(str, sorted(opp['snapshot_mes'].dropna().unique())))}.")
    lines.append(f"- Fases observadas: {', '.join(map(str, opp['fase'].dropna().unique()))}.")
    lines.append(f"- Status observados: {', '.join(map(str, opp['status'].dropna().unique()))}.")
    lines.append(f"- Valores fora do intervalo 0-1 em probabilidade: {len(prob_outside)}.")
    lines.append("")
    lines.append("# HIPOTESES")
    lines.append("- A base pode representar snapshots mensais exportados do CRM/Tableau, pois ha arquivo_origem, snapshot_mes e repeticao de oportunidades ao longo dos meses.")
    lines.append("- `r_pipeline` pode representar valor ponderado por probabilidade, mas isso precisa ser validado contra a regra de calculo comercial.")
    lines.append("- `data_atual*` pode estar relacionada a datas de acompanhamento, mas nao ha evidencia suficiente para tratar como data realizada.")
    lines.append("")
    lines.append("# DADOS NECESSARIOS")
    lines.append("- Campo de resultado final validado: ganho, perdido, cancelado ou em aberto.")
    lines.append("- Valor realizado final por oportunidade.")
    lines.append("- Data real de fechamento.")
    lines.append("- Regra oficial de calculo de pipeline e R$ Pipeline.")
    lines.append("- Historico completo de snapshots em periodicidade definida.")
    lines.append("- Chave unica de oportunidade e, se aplicavel, chave unica de item/produto.")
    lines.append("- Definicao de quais status/fases entram no forecast oficial.")
    lines.append("")
    lines.append("# RISCOS ANALITICOS")
    lines.append("- Medir forecast em nivel de linha de produto pode duplicar oportunidades e distorcer concentracao.")
    lines.append("- Tratar status operacional como resultado realizado pode gerar erro artificial.")
    lines.append("- Comparar snapshots parciais contra resultados futuros ausentes pode produzir falsa assertividade.")
    lines.append("- Misturar valor bruto, valor ponderado e quantidade sem regra oficial compromete MAE, Bias e MAPE.")
    lines.append("")
    lines.append("# PROXIMA ETAPA RECOMENDADA")
    lines.append("Validar com Revenue Operations o significado de `r_pipeline`, `pipeline`, `status`, `data_atual*` e a regra oficial de oportunidade-snapshot. Em seguida, obter historico completo com resultado realizado para calcular assertividade.")
    lines.append("")

    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
