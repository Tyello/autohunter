# Baseline — relatório Query Performance (Supabase), 2026-08-27

Números reportados pelo usuário antes de qualquer mudança desta spec. Comparar contra o painel "Query Performance" do Supabase depois do deploy de cada fase (aguardar ao menos 1h de tráfego real antes de comparar).

| # | Query | Chamadas | Observação | Fase que ataca |
|---|---|---|---|---|
| 1 | `UPDATE apscheduler_jobs SET next_run_time=..., job_state=...` | 405.041 | bookkeeping do `browser_queue_worker` (5s) + `http_queue_worker` ×2 (2s) no jobstore persistente | Fase 1 (etapas 2-3) |
| 2 | `SELECT ... FROM source_configs` | 1.165.695 | `_get_cfg` sem cache no hot path de scan/match | Fase 1 (etapa 4) |
| 3 | `DELETE FROM source_runs WHERE id IN (SELECT ...)` / `telemetry_events` | — (pico ~20s numa chamada) | já batched (1000/lote) desde spec 002; índice com created_at líder já existe nas 3 tabelas | Fase 2 (etapa 7, investigativa) |
| 4 | `INSERT INTO system_logs` | 102.545 | inclui log de sucesso a cada tick do `browser_queue_worker` | Fase 1 (etapa 5) |
| 5 | `UPDATE car_listings SET updated_at=...` | 105.034 | bump incondicional a cada upsert, mesmo sem mudança real | Fase 1 (etapa 6) |
| 6 | `COPY telemetry_events / car_listings / source_runs` | — (cache hit 14-99%, até ~6s) | confirmado: `pg_dump` externo (`scripts/backup_db.sh`, cron do SO), não é código nosso agendado | Fase 2 (etapa 8, informativo) |

## Checklist por fase

- **Antes do deploy**: anotar aqui os números atuais das linhas 1, 2, 4 e 5 (as que a Fase 1 ataca), copiados do painel Query Performance.
- **Depois do deploy + 1h de tráfego**: reabrir o painel, comparar. Só prosseguir para a Fase 2 com confirmação explícita de melhoria (ou de que nada quebrou).
