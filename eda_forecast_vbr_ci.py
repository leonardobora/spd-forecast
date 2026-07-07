"""
EDA e preparacao de dados para Forecast VBR-CI.

O script segue as regras de rigor do projeto:
- nao inventa campos, valores ou nomes;
- separa fato, hipotese e recomendacao;
- calcula metricas de erro apenas quando ha previsto x realizado explicitos;
- preserva a granularidade original por item/produto.
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


MAIN_SHEET = "G-VDC  Forecast de Vendas"
DATE_MIN_REASONABLE = pd.Timestamp("2020-01-01")
DATE_MAX_REASONABLE = pd.Timestamp("2035-12-31")

MONTHS_PT = {
    "jan": 1,
    "fev": 2,
    "mar": 3,
    "abr": 4,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "set": 9,
    "out": 10,
    "nov": 11,
    "dez": 12,
}

FIELD_DESCRIPTIONS = {
    "mes_de_fechamento": "Inferencia: mes/data de fechamento prevista da oportunidade.",
    "data_forecast": "Inferencia: data de referencia do forecast/snapshot.",
    "nome_de_cotacao": "Inferencia: identificador combinado de oportunidade e cotacao.",
    "produto_codigo_do_produto": "Inferencia: codigo do produto/SKU.",
    "produto_nome_do_produto": "Inferencia: descricao do produto/SKU.",
    "quantidade": "Inferencia: volume fisico previsto por linha de produto.",
    "probabilidade": "Inferencia: probabilidade comercial associada ao forecast.",
    "fase": "Inferencia: fase comercial da oportunidade no CRM.",
    "sincronizando": "Inferencia: indicador operacional do CRM.",
    "status": "Inferencia: status da cotacao/oportunidade.",
    "departamento": "Inferencia: unidade/departamento comercial.",
    "proprietario_da_oportunidade": "Inferencia: responsavel/KAM pela oportunidade.",
    "cliente_final": "Inferencia: cliente final associado a oportunidade.",
    "nome_do_projeto": "Inferencia: nome do projeto comercial.",
    "prazo": "Inferencia: prazo associado a linha/oportunidade.",
    "total_liqliq": "Inferencia: valor financeiro liquido por linha.",
    "pipeline": "Inferencia: quantidade ponderada ou pipeline em volume.",
    "r_und": "Inferencia: preco unitario.",
    "r_pipeline": "Inferencia: valor financeiro ponderado do pipeline.",
    "sl": "Inferencia: segmentacao/filtro SL presente no CRM.",
    "no_opt": "Inferencia: identificador da oportunidade.",
}

EXPECTED_FIELDS = {
    "id": ["no_opt", "nome_de_cotacao", "produto_codigo_do_produto", "produto_nome_do_produto"],
    "temporal": ["data_forecast", "mes_de_fechamento"],
    "financial": ["quantidade", "total_liqliq", "pipeline", "r_und", "r_pipeline"],
    "commercial": [
        "probabilidade",
        "fase",
        "status",
        "departamento",
        "proprietario_da_oportunidade",
        "cliente_final",
        "nome_do_projeto",
        "sl",
    ],
}


@dataclass
class DataBundle:
    raw: pd.DataFrame
    clean: pd.DataFrame
    column_dictionary: pd.DataFrame
    files_used: list[str]


def normalize_column(name: object) -> str:
    text = str(name).strip().lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.replace("%", "pct")
    text = text.replace("$", "")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    text = text.replace("probabilidade_pct", "probabilidade")
    text = text.replace("r_und", "r_und")
    text = text.replace("r_pipeline", "r_pipeline")
    if text == "n_opt":
        text = "no_opt"
    return text or "coluna_sem_nome"


def unique_names(names: Iterable[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for name in names:
        count = seen.get(name, 0)
        result.append(name if count == 0 else f"{name}_{count + 1}")
        seen[name] = count + 1
    return result


def infer_snapshot_from_filename(path: Path) -> tuple[str, int]:
    stem = normalize_column(path.stem)
    for month_name, month_num in MONTHS_PT.items():
        match = re.search(rf"(?:^|_){month_name}(\d{{2}})(?:_|$)", stem)
        if match:
            year = 2000 + int(match.group(1))
            return f"{year:04d}-{month_num:02d}", year * 100 + month_num
    return path.stem, 999999


def excel_serial_to_datetime(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return pd.to_datetime("1899-12-30") + pd.to_timedelta(numeric, unit="D")


def coerce_mixed_date(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")

    numeric = pd.to_numeric(series, errors="coerce")
    excel_serial_like = numeric.notna() & numeric.between(1, 60000)
    result = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    result.loc[excel_serial_like] = excel_serial_to_datetime(series.loc[excel_serial_like])
    result.loc[~excel_serial_like] = pd.to_datetime(
        series.loc[~excel_serial_like], errors="coerce", dayfirst=True
    )
    return result


def detect_date_columns(columns: Iterable[str]) -> list[str]:
    return [
        col
        for col in columns
        if col.startswith("data_") or col.startswith("mes_de_fechamento")
    ]


def read_workbooks(input_dir: Path, sheet_name: str = MAIN_SHEET) -> DataBundle:
    files = [path for path in sorted(input_dir.glob("*.xlsx")) if not path.name.startswith("~$")]
    if not files:
        raise FileNotFoundError(f"Nenhum arquivo .xlsx encontrado em {input_dir}")

    frames: list[pd.DataFrame] = []
    dictionaries: list[pd.DataFrame] = []
    files_used: list[str] = []

    for file_path in files:
        try:
            frame = pd.read_excel(file_path, sheet_name=sheet_name, engine="openpyxl")
        except ValueError as exc:
            raise ValueError(f"Aba obrigatoria nao encontrada em {file_path.name}: {sheet_name}") from exc

        original_columns = [str(col) for col in frame.columns]
        normalized_columns = unique_names(normalize_column(col) for col in original_columns)
        snapshot_mes, snapshot_ordem = infer_snapshot_from_filename(file_path)

        dictionaries.append(
            pd.DataFrame(
                {
                    "arquivo_origem": file_path.name,
                    "coluna_original": original_columns,
                    "coluna_interna": normalized_columns,
                }
            )
        )

        frame.columns = normalized_columns
        frame.insert(0, "snapshot_ordem", snapshot_ordem)
        frame.insert(0, "snapshot_mes", snapshot_mes)
        frame.insert(0, "arquivo_origem", file_path.name)
        frames.append(frame)
        files_used.append(file_path.name)

    raw = pd.concat(frames, ignore_index=True, sort=False)
    clean = raw.copy()

    for col in detect_date_columns(clean.columns):
        clean[f"{col}_dt"] = coerce_mixed_date(clean[col])

    return DataBundle(
        raw=raw,
        clean=clean,
        column_dictionary=pd.concat(dictionaries, ignore_index=True),
        files_used=files_used,
    )


def existing_columns(df: pd.DataFrame, candidates: Iterable[str]) -> list[str]:
    return [col for col in candidates if col in df.columns]


def markdown_table(df: pd.DataFrame, max_rows: int = 30) -> str:
    if df.empty:
        return "_Sem registros._"
    view = df.head(max_rows).copy()
    return view.to_markdown(index=False)


def safe_period(df: pd.DataFrame, date_cols: Iterable[str]) -> pd.DataFrame:
    rows = []
    for col in date_cols:
        parsed_col = f"{col}_dt"
        if parsed_col not in df.columns:
            continue
        valid = df[parsed_col].dropna()
        rows.append(
            {
                "campo": col,
                "linhas_com_data_valida": int(valid.shape[0]),
                "data_min": valid.min().date().isoformat() if not valid.empty else None,
                "data_max": valid.max().date().isoformat() if not valid.empty else None,
            }
        )
    return pd.DataFrame(rows)


def infer_usage(col: str) -> str:
    if col in {"arquivo_origem", "snapshot_mes", "snapshot_ordem", "no_opt", "nome_de_cotacao"}:
        return "identificacao"
    if col.startswith("data_") or col.startswith("mes_de_fechamento"):
        return "temporal"
    if col in {"quantidade", "total_liqliq", "pipeline", "r_und", "r_pipeline", "prazo", "probabilidade"}:
        return "financeiro"
    if col.endswith("_dt"):
        return "temporal_derivado"
    return "categorico"


def is_forecast_relevant(col: str) -> bool:
    relevant = set().union(*EXPECTED_FIELDS.values())
    return (
        col in relevant
        or col.startswith("data_atual")
        or col.startswith("fase_opt")
        or col.endswith("_dt")
    )


def step1_initial_inspection(bundle: DataBundle) -> str:
    df = bundle.clean
    date_cols = detect_date_columns(df.columns)

    shapes = (
        df.groupby("arquivo_origem", dropna=False)
        .size()
        .reset_index(name="linhas")
        .assign(colunas=df.shape[1])
    )
    consolidated = pd.DataFrame(
        [{"arquivo_origem": "CONSOLIDADO", "linhas": df.shape[0], "colunas": df.shape[1]}]
    )

    dtypes = pd.DataFrame(
        {"coluna": df.columns, "tipo_pandas": [str(df[col].dtype) for col in df.columns]}
    )
    nulls = (
        df.isna()
        .mean()
        .mul(100)
        .round(2)
        .reset_index()
        .rename(columns={"index": "coluna", 0: "pct_nulos"})
        .sort_values("pct_nulos", ascending=False)
    )

    unique_opportunities = (
        df["no_opt"].nunique(dropna=True) if "no_opt" in df.columns else None
    )

    descriptions = pd.DataFrame(
        {
            "coluna": df.columns,
            "descricao_inferida": [
                FIELD_DESCRIPTIONS.get(
                    col.replace("_dt", ""),
                    f"Inferencia: campo {infer_usage(col)} observado na base.",
                )
                for col in df.columns
            ],
        }
    )

    sample_cols = existing_columns(
        df,
        [
            "arquivo_origem",
            "snapshot_mes",
            "no_opt",
            "cliente_final",
            "proprietario_da_oportunidade",
            "fase",
            "mes_de_fechamento",
            "data_forecast",
            "quantidade",
            "pipeline",
            "r_pipeline",
        ],
    )
    sample = df[sample_cols].head(5) if sample_cols else df.head(5)

    text = [
        "## ETAPA 1 - Inspecao inicial",
        "",
        "### Resumo em texto",
        f"- Arquivos analisados: {', '.join(bundle.files_used)}.",
        f"- Aba usada como fonte principal: `{MAIN_SHEET}`.",
        f"- Amostra consolidada: {df.shape[0]} linhas e {df.shape[1]} colunas, incluindo colunas tecnicas e datas derivadas.",
        f"- Oportunidades unicas por `no_opt`: {unique_opportunities if unique_opportunities is not None else 'campo no_opt ausente'}.",
        "",
        "### Codigo Python usando pandas",
        "```python",
        "bundle = read_workbooks(Path('.'))",
        "df = bundle.clean",
        "linhas_colunas = df.groupby('arquivo_origem').size().reset_index(name='linhas')",
        "tipos = df.dtypes.astype(str)",
        "nulos_pct = df.isna().mean().mul(100).round(2)",
        "oportunidades_unicas = df['no_opt'].nunique() if 'no_opt' in df else None",
        "periodos = safe_period(df, detect_date_columns(df.columns))",
        "amostra = df.head(5)",
        "```",
        "",
        "### Linhas e colunas",
        markdown_table(pd.concat([shapes, consolidated], ignore_index=True)),
        "",
        "### Tipos de dados por coluna",
        markdown_table(dtypes, max_rows=80),
        "",
        "### Percentual de nulos por coluna",
        markdown_table(nulls, max_rows=80),
        "",
        "### Periodo coberto por campos de data",
        markdown_table(safe_period(df, date_cols), max_rows=80),
        "",
        "### Amostra de 5 linhas",
        markdown_table(sample),
        "",
        "### Lista de colunas com descricao inferida",
        markdown_table(descriptions, max_rows=100),
        "",
        "### Interpretacao objetiva",
        "- A base principal possui granularidade por linha de produto/item, nao necessariamente uma linha por oportunidade.",
        "- As estatisticas de oportunidade devem usar `no_opt`; as estatisticas financeiras podem exigir agregacao por oportunidade para evitar dupla contagem.",
        "",
        "### Ressalvas e limitacoes",
        "- As descricoes de colunas sao inferidas pelo nome e conteudo esperado, nao por dicionario oficial do CRM.",
        "- Campos derivados com sufixo `_dt` sao conversoes tecnicas para analise temporal.",
    ]
    return "\n".join(text)


def step2_field_mapping(df: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    rows = []
    for col in df.columns:
        rows.append(
            {
                "nome": col,
                "tipo": str(df[col].dtype),
                "uso_presumido": infer_usage(col),
                "cardinalidade": int(df[col].nunique(dropna=True)),
                "relevante_forecast": is_forecast_relevant(col),
            }
        )
    mapping = pd.DataFrame(rows)

    data_atual_cols = [
        col for col in df.columns if col.startswith("data_atual") and not col.endswith("_dt")
    ]
    answers = pd.DataFrame(
        [
            {"pergunta": "Existe campo de data prometida versus data realizada?", "resposta": "Parcial: ha `mes_de_fechamento` e campos `data_atual*`; nao foi identificado campo explicito de data realizada."},
            {"pergunta": "Existe campo de probabilidade?", "resposta": "Sim" if "probabilidade" in df.columns else "Nao identificado"},
            {"pergunta": "Existe campo de volume ou valor?", "resposta": "Sim" if existing_columns(df, EXPECTED_FIELDS["financial"]) else "Nao identificado"},
            {"pergunta": "Existe campo de cliente e KAM?", "resposta": "Sim" if {"cliente_final", "proprietario_da_oportunidade"}.issubset(df.columns) else "Parcial ou nao identificado"},
            {"pergunta": "Existe campo de fase da oportunidade?", "resposta": "Sim" if "fase" in df.columns or any(col.startswith("fase_opt") for col in df.columns) else "Nao identificado"},
            {"pergunta": "Existe historico de mudancas ou apenas snapshot atual?", "resposta": f"Ha {len(data_atual_cols)} campos `data_atual*` e 3 arquivos snapshot; tratar como historico observacional ate validacao com Daniel/Yasmin."},
        ]
    )

    text = [
        "## ETAPA 2 - Mapeamento de campos",
        "",
        "### Resumo em texto",
        "- Cada coluna foi classificada por uso presumido, cardinalidade e relevancia para forecast.",
        "- A relevancia foi marcada por regras explicitas de nome de campo, nao por julgamento manual de oportunidade.",
        "",
        "### Codigo Python usando pandas",
        "```python",
        "mapeamento = pd.DataFrame([",
        "    {'nome': col, 'tipo': str(df[col].dtype), 'uso_presumido': infer_usage(col),",
        "     'cardinalidade': df[col].nunique(dropna=True),",
        "     'relevante_forecast': is_forecast_relevant(col)}",
        "    for col in df.columns",
        "])",
        "```",
        "",
        "### Mapeamento",
        markdown_table(mapping, max_rows=100),
        "",
        "### Perguntas respondidas pela base",
        markdown_table(answers),
        "",
        "### Interpretacao objetiva",
        "- A base contem os campos centrais para uma EDA de forecast: oportunidade, cliente, responsavel, fase, probabilidade, volume, valores e datas previstas.",
        "- Nao ha evidencia suficiente, apenas pelo nome das colunas, de um campo financeiro realizado compativel com previsto.",
        "",
        "### Ressalvas e limitacoes",
        "- `Data Atual*` pode representar historico de atualizacoes, mas precisa de validacao de negocio para confirmar o significado operacional.",
    ]
    return "\n".join(text), mapping


def build_opportunity_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    if "no_opt" not in df.columns:
        return pd.DataFrame()

    group_cols = ["arquivo_origem", "snapshot_mes", "snapshot_ordem", "no_opt"]
    aggregations = {}

    for col in ["cliente_final", "proprietario_da_oportunidade", "fase", "status", "departamento", "nome_do_projeto"]:
        if col in df.columns:
            aggregations[col] = "first"

    for col in ["quantidade", "pipeline", "total_liqliq", "r_pipeline"]:
        if col in df.columns:
            aggregations[col] = "sum"

    for col in ["probabilidade"]:
        if col in df.columns:
            aggregations[col] = "mean"

    for col in [c for c in df.columns if c.endswith("_dt")]:
        aggregations[col] = "first"

    grouped = df.groupby(group_cols, dropna=False)
    result = grouped.agg(aggregations).reset_index()
    sizes = grouped.size().rename("linhas_item").reset_index()
    result = result.merge(sizes, on=group_cols, how="left")
    return result


def step3_quality(df: pd.DataFrame) -> str:
    exact_duplicates = int(df.duplicated().sum())
    opportunity_rows = (
        df.groupby(["arquivo_origem", "snapshot_mes", "no_opt"], dropna=False)
        .size()
        .reset_index(name="linhas_por_oportunidade")
        .sort_values("linhas_por_oportunidade", ascending=False)
        if "no_opt" in df.columns
        else pd.DataFrame()
    )

    critical = existing_columns(
        df,
        ["no_opt", "cliente_final", "proprietario_da_oportunidade", "fase", "mes_de_fechamento", "data_forecast", "probabilidade", "pipeline", "r_pipeline"],
    )
    missing_critical = (
        df[critical].isna().sum().reset_index().rename(columns={"index": "campo", 0: "nulos"})
        if critical
        else pd.DataFrame()
    )
    if critical:
        missing_critical["pct_nulos"] = (missing_critical["nulos"] / len(df) * 100).round(2)

    invalid_dates = []
    for col in detect_date_columns(df.columns):
        parsed = f"{col}_dt"
        if parsed in df.columns:
            source_not_null = df[col].notna()
            parsed_null = df[parsed].isna()
            out_of_range = df[parsed].notna() & (
                (df[parsed] < DATE_MIN_REASONABLE) | (df[parsed] > DATE_MAX_REASONABLE)
            )
            invalid_dates.append(
                {
                    "campo": col,
                    "valores_nao_nulos_sem_conversao": int((source_not_null & parsed_null).sum()),
                    "datas_fora_faixa_2020_2035": int(out_of_range.sum()),
                }
            )

    negative_rows = []
    for col in existing_columns(df, ["quantidade", "pipeline", "total_liqliq", "r_und", "r_pipeline", "probabilidade"]):
        numeric = pd.to_numeric(df[col], errors="coerce")
        negative_rows.append({"campo": col, "valores_negativos": int((numeric < 0).sum())})

    phase_consistency = pd.DataFrame()
    if "fase" in df.columns:
        closed_mask = df["fase"].astype(str).str.contains("fechad|ganh|perdid|cancel", case=False, na=False)
        date_col = "data_atual_dt" if "data_atual_dt" in df.columns else "mes_de_fechamento_dt"
        if date_col in df.columns:
            phase_consistency = pd.DataFrame(
                [
                    {
                        "criterio": f"fase indica encerramento e `{date_col}` ausente",
                        "linhas": int((closed_mask & df[date_col].isna()).sum()),
                    }
                ]
            )

    text = [
        "## ETAPA 3 - Qualidade da base",
        "",
        "### Resumo em texto",
        f"- Duplicatas exatas de linha: {exact_duplicates}.",
        "- A contagem por `no_opt` deve ser interpretada com cuidado porque a base esta em nivel de item/produto.",
        "",
        "### Codigo Python usando pandas",
        "```python",
        "duplicatas_exatas = df.duplicated().sum()",
        "linhas_por_opt = df.groupby(['arquivo_origem', 'snapshot_mes', 'no_opt']).size()",
        "nulos_criticos = df[campos_criticos].isna().sum()",
        "datas_invalidas = ...  # comparar campo original nao nulo contra campo convertido *_dt nulo",
        "valores_negativos = ... # aplicar em campos numericos esperados",
        "```",
        "",
        "### Registros por oportunidade dentro de cada snapshot",
        markdown_table(opportunity_rows.head(30) if not opportunity_rows.empty else opportunity_rows),
        "",
        "### Campos criticos ausentes",
        markdown_table(missing_critical, max_rows=50),
        "",
        "### Datas invalidas ou fora do periodo esperado",
        markdown_table(pd.DataFrame(invalid_dates), max_rows=50),
        "",
        "### Valores negativos onde nao deveria haver",
        markdown_table(pd.DataFrame(negative_rows), max_rows=50),
        "",
        "### Consistencia entre fase e data",
        markdown_table(phase_consistency),
        "",
        "### Interpretacao objetiva",
        "- Multiplas linhas por oportunidade sao esperadas quando uma oportunidade possui varios produtos.",
        "- Datas fora de 2020-2035 foram marcadas como suspeitas operacionais, nao como erro definitivo.",
        "",
        "### Ressalvas e limitacoes",
        "- A consistencia entre fase e data depende do significado oficial de `Data Atual*`, que ainda precisa ser confirmado.",
    ]
    return "\n".join(text)


def step4_temporal(df: pd.DataFrame) -> str:
    forecast_month = pd.DataFrame()
    closing_month = pd.DataFrame()
    phase_dist = pd.DataFrame()
    changes = pd.DataFrame()

    if "data_forecast_dt" in df.columns:
        forecast_month = (
            df.assign(mes_forecast=df["data_forecast_dt"].dt.to_period("M").astype(str))
            .groupby(["snapshot_mes", "mes_forecast"], dropna=False)
            .agg(linhas=("arquivo_origem", "size"), oportunidades=("no_opt", "nunique") if "no_opt" in df.columns else ("arquivo_origem", "size"))
            .reset_index()
        )

    if "mes_de_fechamento_dt" in df.columns:
        closing_month = (
            df.assign(mes_fechamento_previsto=df["mes_de_fechamento_dt"].dt.to_period("M").astype(str))
            .groupby(["snapshot_mes", "mes_fechamento_previsto"], dropna=False)
            .agg(linhas=("arquivo_origem", "size"), oportunidades=("no_opt", "nunique") if "no_opt" in df.columns else ("arquivo_origem", "size"))
            .reset_index()
        )

    if "fase" in df.columns:
        phase_dist = (
            df.groupby(["snapshot_mes", "fase"], dropna=False)
            .agg(linhas=("arquivo_origem", "size"), oportunidades=("no_opt", "nunique") if "no_opt" in df.columns else ("arquivo_origem", "size"))
            .reset_index()
            .sort_values(["snapshot_mes", "oportunidades"], ascending=[True, False])
        )

    opp = build_opportunity_snapshot(df)
    date_update_cols = [c for c in opp.columns if c.startswith("data_atual") and c.endswith("_dt")]
    if not opp.empty and date_update_cols:
        base_cols = existing_columns(opp, ["no_opt", "snapshot_mes", "mes_de_fechamento_dt"])
        temp = opp[base_cols + date_update_cols].copy()
        temp["primeira_data_atual"] = temp[date_update_cols].min(axis=1)
        temp["ultima_data_atual"] = temp[date_update_cols].max(axis=1)
        temp["dias_entre_primeira_e_ultima_atualizacao"] = (
            temp["ultima_data_atual"] - temp["primeira_data_atual"]
        ).dt.days
        if "mes_de_fechamento_dt" in temp.columns:
            temp["dias_entre_fechamento_previsto_e_ultima_atualizacao"] = (
                temp["mes_de_fechamento_dt"] - temp["ultima_data_atual"]
            ).dt.days
        numeric_change_cols = [
            col for col in temp.columns if col.startswith("dias_entre_")
        ]
        changes = (
            temp[numeric_change_cols]
            .describe()
            .reset_index()
            if numeric_change_cols
            else pd.DataFrame()
        )

    text = [
        "## ETAPA 4 - Analise temporal",
        "",
        "### Resumo em texto",
        "- A analise temporal usa campos convertidos com sufixo `_dt` e preserva o snapshot de origem.",
        "- Quando ha varias linhas por oportunidade, a contagem de oportunidades usa `nunique(no_opt)`.",
        "",
        "### Codigo Python usando pandas",
        "```python",
        "df['mes_forecast'] = df['data_forecast_dt'].dt.to_period('M')",
        "df['mes_fechamento_previsto'] = df['mes_de_fechamento_dt'].dt.to_period('M')",
        "oportunidades_por_mes = df.groupby(['snapshot_mes', 'mes_forecast'])['no_opt'].nunique()",
        "fechamento_por_mes = df.groupby(['snapshot_mes', 'mes_fechamento_previsto'])['no_opt'].nunique()",
        "fase = df.groupby(['snapshot_mes', 'fase'])['no_opt'].nunique()",
        "```",
        "",
        "### Oportunidades por mes de forecast",
        markdown_table(forecast_month, max_rows=80),
        "",
        "### Oportunidades por mes de fechamento previsto",
        markdown_table(closing_month, max_rows=80),
        "",
        "### Distribuicao por fase",
        markdown_table(phase_dist, max_rows=80),
        "",
        "### Historico de mudancas, se aplicavel",
        markdown_table(changes, max_rows=30),
        "",
        "### Interpretacao objetiva",
        "- As distribuicoes mostram concentracao temporal e status/fase por snapshot, sem inferir causalidade.",
        "- Campos `Data Atual*` permitem medir diferencas temporais somente se o significado operacional for confirmado.",
        "",
        "### Ressalvas e limitacoes",
        "- Se os snapshots ja incluem colunas futuras/preenchidas por formulas, mudancas historicas devem ser validadas antes de conclusoes.",
    ]
    return "\n".join(text)


def find_realized_fields(df: pd.DataFrame) -> list[str]:
    patterns = ["real", "realizado", "realizada", "faturado", "fechado", "executado"]
    candidates = []
    for col in df.columns:
        if any(pattern in col for pattern in patterns):
            numeric = pd.to_numeric(df[col], errors="coerce")
            if numeric.notna().any():
                candidates.append(col)
    return candidates


def step5_error(df: pd.DataFrame) -> str:
    predicted_candidates = existing_columns(df, ["pipeline", "r_pipeline", "quantidade", "total_liqliq"])
    realized_candidates = find_realized_fields(df)

    metrics = pd.DataFrame()
    message = "Nao calculado: nao foi identificado campo numerico explicito de realizado compativel com previsto."

    if predicted_candidates and realized_candidates:
        pred_col = "r_pipeline" if "r_pipeline" in predicted_candidates else predicted_candidates[0]
        real_col = realized_candidates[0]
        calc = df[[pred_col, real_col]].copy()
        calc[pred_col] = pd.to_numeric(calc[pred_col], errors="coerce")
        calc[real_col] = pd.to_numeric(calc[real_col], errors="coerce")
        calc = calc.dropna()
        if not calc.empty:
            error = calc[pred_col] - calc[real_col]
            real_non_zero = calc[real_col] != 0
            metrics = pd.DataFrame(
                [
                    {"metrica": "MAE", "valor": error.abs().mean(), "amostra": len(calc), "criterio": f"{pred_col} - {real_col}"},
                    {"metrica": "Bias", "valor": error.mean(), "amostra": len(calc), "criterio": f"{pred_col} - {real_col}"},
                    {"metrica": "MAPE", "valor": (error[real_non_zero].abs() / calc.loc[real_non_zero, real_col]).mean() * 100, "amostra": int(real_non_zero.sum()), "criterio": "exclui Real = 0"},
                ]
            )
            message = f"Calculado usando previsto `{pred_col}` e realizado `{real_col}`."

    text = [
        "## ETAPA 5 - Calculo inicial de erro",
        "",
        "### Resumo em texto",
        f"- {message}",
        "",
        "### Codigo Python usando pandas",
        "```python",
        "erro = forecast - real",
        "mae = erro.abs().mean()",
        "bias = erro.mean()",
        "mape = (erro.abs() / real).replace([float('inf')], pd.NA).dropna().mean() * 100",
        "```",
        "",
        "### Metricas",
        markdown_table(metrics),
        "",
        "### Interpretacao objetiva",
        "- MAE, Bias e MAPE exigem uma coluna de realizado; fase/status nao substituem valor realizado.",
        "- Sem realizado explicito, esta etapa documenta a lacuna em vez de produzir metricas artificiais.",
        "",
        "### Ressalvas e limitacoes",
        "- `Fechada`, `Ganha` ou `Perdida` podem indicar desfecho comercial, mas nao permitem calcular erro financeiro/volume sem valor real correspondente.",
    ]
    return "\n".join(text)


def step6_preparation(df: pd.DataFrame, output_dir: Path) -> tuple[str, pd.DataFrame]:
    opp = build_opportunity_snapshot(df)
    derived_cols = pd.DataFrame(
        [
            {"coluna_derivada": "arquivo_origem", "descricao": "Arquivo Excel de origem."},
            {"coluna_derivada": "snapshot_mes", "descricao": "Mes inferido do nome do arquivo."},
            {"coluna_derivada": "snapshot_ordem", "descricao": "Chave numerica para ordenacao de snapshots."},
            {"coluna_derivada": "*_dt", "descricao": "Conversao tecnica de campos de data para datetime."},
            {"coluna_derivada": "linhas_item", "descricao": "Quantidade de linhas de item por oportunidade no snapshot agregado."},
        ]
    )

    text = [
        "## ETAPA 6 - Preparacao para etapas seguintes",
        "",
        "### Resumo em texto",
        "- Dataset limpo sugerido: manter a base por item/produto e criar uma segunda tabela agregada por oportunidade e snapshot.",
        "- Nenhuma coluna original deve ser descartada nesta etapa; campos derivados ficam documentados.",
        "- Formato recomendado: parquet para uso analitico; CSV foi usado como alternativa simples e portavel neste script.",
        "",
        "### Codigo Python usando pandas",
        "```python",
        "base_item_limpa = df.copy()",
        "base_oportunidade_snapshot = build_opportunity_snapshot(df)",
        "base_item_limpa.to_csv(output_dir / 'base_item_limpa.csv', index=False)",
        "base_oportunidade_snapshot.to_csv(output_dir / 'base_oportunidade_snapshot.csv', index=False)",
        "```",
        "",
        "### Colunas derivadas uteis",
        markdown_table(derived_cols),
        "",
        "### Interpretacao objetiva",
        "- A tabela por item preserva rastreabilidade e evita perda de detalhe de produto.",
        "- A tabela por oportunidade reduz dupla contagem quando a analise estiver no nivel comercial.",
        "",
        "### Ressalvas e limitacoes",
        "- Parquet exige dependencia adicional opcional (`pyarrow` ou `fastparquet`). Por isso, CSV e o padrao minimo deste script.",
        f"- Saidas serao gravadas em `{output_dir}` somente quando o script for executado.",
    ]
    return "\n".join(text), opp


def final_sections(bundle: DataBundle, df: pd.DataFrame) -> str:
    facts = [
        f"Foram localizados e carregados {len(bundle.files_used)} arquivos .xlsx.",
        f"A aba principal usada foi `{MAIN_SHEET}`.",
        "A base principal esta em granularidade de item/produto.",
        "`no_opt` e tratado como identificador de oportunidade quando presente.",
        "Metricas de erro dependem de campo explicito de realizado.",
    ]
    hypotheses = [
        "Os arquivos Mar26, Abr26 e Mai26 representam snapshots mensais comparaveis.",
        "`Data Atual*` pode representar historico ou estado de atualizacao da oportunidade.",
        "`R$ Pipeline` pode representar forecast financeiro ponderado, sujeito a validacao.",
    ]
    questions = [
        "Qual e o significado operacional exato de `Data Atual`, `Data Atual Jun26` e `Data Atual Jul26`?",
        "Existe campo de valor/volume realizado fora desta aba ou em outro sistema?",
        "A coluna `Pipeline` representa volume ponderado por probabilidade ou outra regra?",
        "Qual fase deve ser considerada fechamento ganho, perdido ou cancelado?",
        "Os tres arquivos sao snapshots exportados na mesma data de corte mensal?",
    ]
    recommendations = [
        "Validar dicionario de dados com Daniel e Yasmin antes de calcular indicadores finais.",
        "Confirmar campos de realizado para habilitar MAE, Bias e MAPE.",
        "Manter duas granularidades: item/produto e oportunidade-snapshot.",
        "Registrar criterios de exclusao antes de descartar qualquer linha ou coluna.",
    ]

    def bullet(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items)

    return "\n".join(
        [
            "## Fechamento",
            "",
            "### Lista de fatos observados",
            bullet(facts),
            "",
            "### Lista de hipoteses levantadas",
            bullet(hypotheses),
            "",
            "### Perguntas em aberto para Daniel e Yasmin",
            bullet(questions),
            "",
            "### Recomendacao de proximos passos",
            bullet(recommendations),
        ]
    )


def build_report(bundle: DataBundle, output_dir: Path) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    df = bundle.clean
    step2_text, mapping = step2_field_mapping(df)
    step6_text, opp = step6_preparation(df, output_dir)

    parts = [
        "# Relatorio EDA e Preparacao - Forecast VBR-CI",
        "",
        "Este relatorio foi gerado por `eda_forecast_vbr_ci.py` a partir dos arquivos Excel disponiveis.",
        "Todas as estatisticas usam apenas campos presentes na base carregada.",
        "",
        step1_initial_inspection(bundle),
        "",
        step2_text,
        "",
        step3_quality(df),
        "",
        step4_temporal(df),
        "",
        step5_error(df),
        "",
        step6_text,
        "",
        final_sections(bundle, df),
        "",
    ]
    return "\n".join(parts), mapping, opp


def write_outputs(bundle: DataBundle, report: str, mapping: pd.DataFrame, opp: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "eda_forecast_vbr_ci_report.md").write_text(report, encoding="utf-8-sig")
    bundle.clean.to_csv(output_dir / "base_item_limpa.csv", index=False, encoding="utf-8-sig")
    bundle.column_dictionary.to_csv(output_dir / "dicionario_colunas.csv", index=False, encoding="utf-8-sig")
    mapping.to_csv(output_dir / "mapeamento_campos.csv", index=False, encoding="utf-8-sig")
    if not opp.empty:
        opp.to_csv(output_dir / "base_oportunidade_snapshot.csv", index=False, encoding="utf-8-sig")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EDA Forecast VBR-CI com pandas.")
    parser.add_argument("--input-dir", type=Path, default=Path("."), help="Pasta com arquivos .xlsx.")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"), help="Pasta de saida.")
    parser.add_argument("--sheet-name", default=MAIN_SHEET, help="Nome da aba principal.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bundle = read_workbooks(args.input_dir, args.sheet_name)
    report, mapping, opp = build_report(bundle, args.output_dir)
    write_outputs(bundle, report, mapping, opp, args.output_dir)
    print(f"Relatorio gerado em: {args.output_dir / 'eda_forecast_vbr_ci_report.md'}")


if __name__ == "__main__":
    main()
