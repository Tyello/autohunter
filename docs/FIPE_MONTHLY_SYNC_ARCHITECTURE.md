# FIPE Monthly Sync Architecture

## Decisão operacional

AutoHunter usa **base FIPE local mensal**. O runtime principal continua consumindo somente tabelas locais do banco; não há chamada de API FIPE externa no caminho de wishlist, matching, score ou notificação.

O pipeline externo (ex.: modelo `caiopizzol/cnpj-data-pipeline` aplicado ao domínio FIPE, ou export compatível com `caiopizzol/fipe-data-pipeline`) é tratado como **produtor de arquivo**. O AutoHunter não incorpora Bun/TypeScript nem cliente online FIPE no runtime.

## Estado atual confirmado no código

Tabelas já existentes:

- `fipe_catalog_entries`: staging/catalog mensal normalizado e idempotente por (`reference_month`, `vehicle_type`, `source`, `identity_key`).
- `fipe_sync_runs`: trilha de runs aplicados do import mensal de catálogo.
- `fipe_prices`: tabela local final consumida por score/inteligência de preço.
- `system_logs`: auditoria operacional dos applies e do comando mensal.

Componentes já existentes antes do comando mensal único:

- `scripts/import_fipe_catalog_entries.py`: import isolado de catálogo, com `--format external-pipeline` e `--apply`.
- `scripts/import_fipe_prices.py`: import direto de `fipe_prices` por CSV/JSON operacional.
- `app/services/fipe_external_pipeline_adapter.py`: adapter de aliases do output externo para o contrato local.
- `app/services/fipe_catalog_resolver_service.py`: resolver diagnóstico AutoHunter → FIPE, sem escrita em `fipe_prices`.
- `app/services/fipe_prices_planning_service.py`: plano e apply controlado para inserir `fipe_prices` apenas em matches high, não ambíguos, deduplicados.
- Comandos Telegram admin `/admin fipe catalog`, `coverage`, `resolve`, `resolver_status`, `plan`, `apply_plan`, `apply_history`/`audit` e `apply_status`.

## O que ainda era manual

Antes de `scripts/run_monthly_fipe_sync.py`, a operação mensal exigia encadear manualmente:

1. validar o arquivo exportado pelo pipeline externo;
2. rodar import de catálogo;
3. consultar relatório/cobertura;
4. rodar plano de `fipe_prices`;
5. aplicar o plano live explicitamente;
6. correlacionar logs em `fipe_sync_runs` e `system_logs`.

O comando único implementado reduz essa sequência para uma execução auditável, mantendo o scheduler mensal **fora do escopo**.

## Fluxo alvo mensal

```text
pipeline externo FIPE
  -> arquivo JSON/CSV local
  -> scripts/run_monthly_fipe_sync.py
  -> adapter external-pipeline
  -> upsert fipe_catalog_entries
  -> relatório de catálogo/staging
  -> resolver coverage AutoHunter→FIPE
  -> plano fipe_prices
  -> apply controlado apenas com --apply
  -> system_logs + fipe_sync_runs
  -> fipe_prices local para runtime
```

Separação explícita:

1. **Catálogo bruto/staging:** `fipe_catalog_entries`.
2. **Mapeamento AutoHunter → FIPE:** resolver local baseado em `CarListing` + catálogo mensal.
3. **Tabela final de consumo:** `fipe_prices`.
4. **Runtime:** somente lê dados locais; não chama API FIPE externa.

## Comando operacional único

Dry-run obrigatório antes do live:

```bash
python scripts/run_monthly_fipe_sync.py \
  --reference-month 2026-05 \
  --input /path/to/fipe_pipeline_output.json \
  --format external-pipeline \
  --dry-run
```

Apply explícito:

```bash
python scripts/run_monthly_fipe_sync.py \
  --reference-month 2026-05 \
  --input /path/to/fipe_pipeline_output.json \
  --format external-pipeline \
  --apply
```

Parâmetros opcionais:

- `--source external_pipeline`: fonte gravada em `fipe_catalog_entries.source`.
- `--limit 100`: amostra operacional para coverage/plan.
- `--min-confidence 80`: confiança mínima para inserir em `fipe_prices`.

## Semântica de dry-run e apply

### `--dry-run`

- valida mês e arquivo;
- normaliza input pelo adapter externo;
- executa upsert de catálogo em modo preview (`dry_run=True`), sem persistir `fipe_catalog_entries`;
- gera relatório do catálogo atualmente persistido para o mês/source;
- calcula coverage/plan contra o catálogo já persistido no banco;
- não cria `fipe_sync_runs`;
- grava auditoria em `system_logs` com `component="fipe_monthly_sync"`.

Observação: se o mês ainda não foi aplicado, o dry-run mostra quantas linhas seriam inseridas/atualizadas, mas coverage/plan não usa linhas não persistidas. Isso preserva segurança operacional e evita staging temporário invisível/ambíguo.

### `--apply`

- valida e normaliza input;
- faz upsert idempotente em `fipe_catalog_entries`;
- cria e conclui uma linha em `fipe_sync_runs`;
- gera relatório de catálogo já aplicado;
- calcula resolver coverage;
- aplica o plano de `fipe_prices` com `dry_run=False` e `allow_updates=False`;
- grava auditoria em `system_logs` com `component="fipe_monthly_sync"`;
- não atualiza preços existentes automaticamente.

## Idempotência

- `fipe_catalog_entries` usa chave única por (`reference_month`, `vehicle_type`, `source`, `identity_key`). Reprocessar o mesmo arquivo/mês atualiza a linha existente em vez de duplicar.
- `fipe_prices` usa chave única por (`vehicle_key`, `reference_month`). O plano pula itens já existentes com reason `already_exists`.
- `fipe_sync_runs` e `system_logs` podem ter múltiplas linhas por reexecução: isso é trilha de auditoria, não duplicação de dados de negócio.

## Saída esperada para operação

O comando imprime resumo compacto:

- modo (`dry-run` ou `apply`);
- referência mensal;
- contadores do adapter;
- contadores do import de catálogo;
- tamanho atual do catálogo no mês/source;
- coverage do resolver;
- plano/apply de `fipe_prices`;
- total atual de `fipe_prices` na competência;
- próximo passo recomendado.

## Ordem operacional recomendada

1. Gerar arquivo mensal fora do AutoHunter.
2. Copiar o arquivo para o host do AutoHunter.
3. Rodar `--dry-run` e revisar contadores:
   - `normalized > 0`;
   - `skipped_missing_price` e `skipped_missing_model` aceitáveis;
   - `inserted/updated` compatíveis com uma competência mensal;
   - coverage e plano sem anomalias.
4. Rodar `--apply` uma única vez.
5. Consultar `/admin fipe apply_status YYYY-MM` e `/admin fipe coverage YYYY-MM`.
6. Se necessário, reexecutar `--apply` com o mesmo arquivo: a operação é idempotente para dados de negócio.

## Preparação para cron/systemd mensal

Ainda não há scheduler automático. Para automação futura, criar um timer que execute o comando após o arquivo mensal já estar presente.

Exemplo conceitual de cron (não ativado no repo):

```cron
# 05:20 UTC no dia 5 de cada mês, depois da geração externa do arquivo
20 5 5 * * cd /workspace/autohunter && . .venv/bin/activate && python scripts/run_monthly_fipe_sync.py --reference-month $(date -u +\%Y-\%m) --input /var/lib/autohunter/fipe/fipe_$(date -u +\%Y_\%m).json --format external-pipeline --apply >> /var/log/autohunter/fipe_monthly_sync.log 2>&1
```

Antes de ativar cron/systemd, decidir:

- caminho oficial do arquivo mensal;
- usuário do sistema e permissões;
- política de retenção dos arquivos brutos;
- alerta quando o comando retornar exit code não-zero;
- janela operacional e rollback;
- se o mês de referência deve ser mês corrente ou mês FIPE recém-publicado.

## Guardrails

- Não alterar `score_v2`, matching de anúncios, notificações ou comportamento runtime durante a operação mensal.
- Não chamar API FIPE externa a partir do runtime.
- Não liberar scheduler automático sem revisão operacional explícita.
- Não aplicar updates de preços existentes sem uma flag/revisão separada.
- Sempre tratar `.env` como fallback/kill switch, não como superfície única de configuração de produto.
