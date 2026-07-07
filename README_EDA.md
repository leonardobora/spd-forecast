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
```

## Entradas esperadas

- Arquivos `.xlsx` na pasta informada por `--input-dir`.
- Aba principal: `G-VDC  Forecast de Vendas`.
- Cada arquivo e tratado como um snapshot mensal.

## Saidas geradas

- `outputs/eda_forecast_vbr_ci_report.md`: relatorio com as Etapas 1 a 6.
- `outputs/base_item_limpa.csv`: base consolidada na granularidade original por item/produto.
- `outputs/base_oportunidade_snapshot.csv`: base agregada por snapshot e oportunidade.
- `outputs/dicionario_colunas.csv`: mapeamento de colunas originais para nomes internos.
- `outputs/mapeamento_campos.csv`: classificacao de uso, cardinalidade e relevancia de cada coluna.
- `outputs/instability_metrics_report.md`: metricas indiretas de instabilidade sem usar realizado.
- `outputs/*.csv` adicionais de instabilidade: deslocamento de fechamento, variacao de probabilidade, variacao de valor, concentracao, rotatividade e duplicatas.

## Ressalva importante

MAE, Bias e MAPE so sao calculados se houver campos explicitos e compativeis de
previsto versus realizado. Caso contrario, o relatorio declara a impossibilidade
do calculo nesta etapa.
