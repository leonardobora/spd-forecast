# EDA Forecast VBR-CI

Este projeto contem um roteiro reproduzivel em Python/pandas para inspecionar os
arquivos Excel do CRM VBR-CI sem inventar campos ou valores.

## Como executar

Em um ambiente com Python instalado:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python eda_forecast_vbr_ci.py --input-dir . --output-dir outputs
python instability_metrics_vbr_ci.py --output-dir outputs
python analise_forecast_avancada.py
streamlit run dashboard_forecast_vbr_ci.py
```

## Entradas esperadas

- Arquivos `.xlsx` na pasta informada por `--input-dir`.
- Aba principal: `G-VDC  Forecast de Vendas`.
- Cada arquivo e tratado como um snapshot mensal.
- Os arquivos em `outputs/` nao sao versionados porque podem conter dados comerciais.

## Saidas geradas

- `outputs/eda_forecast_vbr_ci_report.md`: relatorio com as Etapas 1 a 6.
- `outputs/base_item_limpa.csv`: base consolidada na granularidade original por item/produto.
- `outputs/base_oportunidade_snapshot.csv`: base agregada por snapshot e oportunidade.
- `outputs/dicionario_colunas.csv`: mapeamento de colunas originais para nomes internos.
- `outputs/mapeamento_campos.csv`: classificacao de uso, cardinalidade e relevancia de cada coluna.
- `outputs/instability_metrics_report.md`: metricas indiretas de instabilidade sem usar realizado.
- `outputs/*.csv` adicionais de instabilidade: deslocamento de fechamento, variacao de probabilidade, variacao de valor, concentracao, rotatividade e duplicatas.
- `outputs/analise_forecast_avancada_report.md`: diagnostico avancado por etapas A-G, separando fatos, hipoteses e dados necessarios.
- `outputs/analise_dicionario_operacional.csv`: dicionario operacional das colunas existentes.
- `outputs/analise_distribuicoes_pipeline.csv`: distribuicoes de pipeline por fase, status, probabilidade, cliente e proprietario.
- `outputs/analise_consistencia_comercial.csv`: flags comerciais para revisao, sem assumir erro.

## Dashboard Streamlit

O dashboard `dashboard_forecast_vbr_ci.py` usa `outputs/base_oportunidade_snapshot.csv`
como unidade principal de analise e `outputs/base_item_limpa.csv` para contagens de
itens/produtos.

Antes de executar, coloque estes arquivos localmente em `outputs/`:

- `outputs/base_oportunidade_snapshot.csv`
- `outputs/base_item_limpa.csv`

```powershell
streamlit run dashboard_forecast_vbr_ci.py
```

Abas disponiveis:

- Visao geral do pipeline por snapshot, fase, status e probabilidade.
- Concentracao por cliente e proprietario.
- Qualidade de campos de forecast e flags comerciais para revisao.
- Historico parcial por oportunidade ao longo dos snapshots.
- Tabela filtrada com download CSV.

## Ressalva importante

MAE, Bias e MAPE so sao calculados se houver campos explicitos e compativeis de
previsto versus realizado. Caso contrario, o relatorio declara a impossibilidade
do calculo nesta etapa.
