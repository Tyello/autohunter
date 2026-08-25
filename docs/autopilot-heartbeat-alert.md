# Autopilot: alertas de scheduler/heartbeat

Documenta a lógica dos dois findings operacionais que cobrem "o scheduler parou de
processar fontes", implementados em `app/services/autopilot_service.py::_candidate_operational`.

## Os dois checks

### 1. `scheduler_heartbeat_missing` (processo do scheduler caiu)

- O processo do scheduler grava um `SystemLog(component="scheduler", message="heartbeat")`
  a cada 10s (`app/scheduler/run.py`), independente dos workers de scraping.
- Se o heartbeat mais recente tem mais de `autopilot_scheduler_heartbeat_missing_minutes`
  (default **5 min**) de idade (ou nunca existiu), dispara `error`.
- Cobre: crash loop do `autohunter-scheduler.service`, processo travado/matado, deploy que
  não voltou a subir.
- **Não cobre**: processo vivo mas os jobs individuais (workers) travados — é exatamente
  para isso que existe o check #2.

### 2. `scheduler_heartbeat_without_runs` (processo vivo, mas nada é processado)

- Conta `SourceRun` com `status in (success, error)` criados nos últimos
  `autopilot_source_runs_zero_window_minutes` (default **55 min**).
- Só dispara se **ambas** as condições forem verdadeiras:
  - heartbeat fresco pelo padrão mais rígido do check #1 (senão os dois disparariam juntos
    pelo mesmo problema subjacente — heartbeat sumido já é coberto lá);
  - `source_runs` no período = 0.
- Cobre: heartbeat do processo scheduler continua batendo, mas o enqueue/execução real de
  fontes parou — ex. worker de browser travado com sessão de DB corrompida, fila entupida,
  conectividade do worker com o banco quebrada. Esse foi o cenário do incidente real
  (worker de browser travado após crash loop do scheduler).
- Severidade `error` (não `warn`): esse cenário historicamente correspondeu a um incidente
  real, não a ruído esperado.

## Calibração da janela (55 min)

A janela original era 30 min e gerava falsos positivos: gaps naturais entre execuções de
fontes (9 fontes ativas, `sched_minutes` de 60–90 escalonados) já passam de 30 min sem
nenhum problema.

Medido contra `source_runs` reais das últimas 48h em produção (2026-08-25):

| métrica | valor |
|---|---|
| fontes ativas | 9 |
| `sched_minutes` das fontes | 60 (8 fontes) / 90 (1 fonte, `turboclass`) |
| gap p95 entre execuções | ~34.9 min |
| gap p99 entre execuções | ~40.6 min |
| gap máximo observado | ~41.9 min |

Threshold de **55 min** dá ~13 min de margem acima do maior gap natural observado — grande
o suficiente para não confundir com o pior caso saudável, apertado o suficiente para não
demorar mais de ~1h para detectar um worker realmente travado.

Se o número de fontes ativas ou os `sched_minutes` mudarem de forma relevante, refazer essa
medição (query abaixo) e reajustar `autopilot_source_runs_zero_window_minutes`.

```sql
-- p95/p99 de gap entre source_runs bem-sucedidos/com erro, últimas 48h
select created_at from source_runs
where status in ('success','error') and created_at > now() - interval '2 days'
order by created_at;
-- calcular diffs consecutivos em minutos e olhar p95/p99/max
```

## Limitação conhecida: não há histórico append-only dos disparos

`AutopilotFinding` é uma linha *singleton* por `fingerprint` (kind fixo, sem
time-bucketing): `first_seen_at`/`last_seen_at`/`hit_count`/`evidence` são sobrescritos a
cada scan, e `evidence` guarda só o snapshot mais recente. Isso significa:

- Não dá para reconstruir, depois do fato, exatamente quando cada disparo começou/terminou
  historicamente — só o estado atual e um contador cumulativo de scans em que a condição
  esteve verdadeira desde a criação (ou desde a última reabertura, se o kind for
  auto-fechável — ver abaixo).
- `system_logs` (heartbeat, erros) também não é retenção longa — não é uma fonte confiável
  para investigar incidentes de mais de ~1-2 dias atrás.

Se for necessário auditar incidentes específicos no futuro, considerar uma tabela
append-only (`autopilot_finding_events`) gravando um snapshot de evidence a cada transição
open→closed / closed→open, em vez de confiar só no estado atual.

## Auto-close (resolve_stale_operational_findings)

Antes de 2026-08-25, os kinds operacionais (`scrape_jobs_stuck`,
`scheduler_heartbeat_missing`, `scheduler_heartbeat_without_runs`,
`sender_idle_with_backlog`, `scrape_jobs_missing_critical_index`) nunca fechavam sozinhos —
uma vez `open`, ficavam `open` indefinidamente até fechamento manual, mesmo depois da
condição real desaparecer. Combinado com o throttle de 30 min em `should_alert`, isso fazia
o mesmo finding reabrir e re-alertar em cada scan em que a condição voltasse a ser
momentaneamente verdadeira (ex.: um gap natural de 35-40 min com a janela antiga de 30 min),
sem nunca "resetar" — daí a sensação de alerta batendo "de vez em quando" sem dar pra
distinguir sinal de ruído.

Agora `job_autopilot_scan` chama `resolve_stale_operational_findings` a cada scan, fechando
automaticamente qualquer finding operacional cuja condição não é mais verdadeira. Reabertura
depois disso reseta `first_seen_at`/`hit_count`, então o histórico de `hit_count` volta a
significar "quantos scans consecutivos essa instância do problema esteve ativa", não um
contador cumulativo desde maio.

## Como simular um disparo para validar

Sem mexer em dados de produção, chamando a lógica diretamente com um `now` deslocado:

```python
from datetime import datetime, timezone
from app.db.session import SessionLocal
from app.services.autopilot_service import build_candidates, format_alert
from app.models.autopilot_finding import AutopilotFinding

with SessionLocal() as db:
    # empurra "agora" pra depois do último heartbeat real ficar velho o suficiente
    # NÃO precisa inserir heartbeat futuro — heartbeat real continua sendo gravado
    # a cada 10s pelo processo rodando; para simular heartbeat "sumido", desligar o
    # scheduler localmente e rodar isso alguns minutos depois.
    now = datetime.now(timezone.utc)
    cands = build_candidates(db, now)
    for c in cands:
        print(c.kind, c.severity, c.title)
        if c.kind == "scheduler_heartbeat_without_runs":
            # monta uma linha fake só pra ver o texto que iria pro Telegram
            fake = AutopilotFinding(kind=c.kind, source=c.source, title=c.title,
                                     severity=c.severity, evidence=c.evidence)
            print(format_alert(fake))
```

Para validar de ponta a ponta contra o cenário real (heartbeat vivo, source_runs zerado):

1. Em um ambiente de teste/staging (nunca em prod), pausar temporariamente o worker que
   grava `SourceRun` (ex.: comentar o enqueue no scheduler) mantendo o processo do scheduler
   de pé (heartbeat continua rodando).
2. Esperar mais que `autopilot_source_runs_zero_window_minutes` (55 min, ou reduza
   temporariamente via env var `AUTOPILOT_SOURCE_RUNS_ZERO_WINDOW_MINUTES=2` num ambiente de
   teste para não esperar quase 1h).
3. Rodar `job_autopilot_scan()` manualmente (ou esperar o scan de 60s) e conferir:
   - o finding `scheduler_heartbeat_without_runs` aparece com `status=open`;
   - o texto do alerta (via `format_alert`) traz `minutes_since_last_run`,
     `expected_active_sources` e `recent_errors_sample` preenchidos;
   - a mensagem chega no Telegram de admin (`send_admin_text`).
4. Religar o worker, esperar um `SourceRun` novo ser gravado, rodar o scan de novo e
   confirmar que o finding fecha sozinho (`status=closed`) sem intervenção manual.

Testes automatizados equivalentes já existem em `tests/test_autopilot_operational.py`
(cobrem: disparo com heartbeat fresco + zero runs, não-disparo com heartbeat velho,
auto-close quando a condição some, reabertura resetando `hit_count`).

## Status em 2026-08-25

- Janela recalibrada de 30→55 min e enriquecimento de evidence (`minutes_since_last_run`,
  `expected_active_sources`, `recent_errors_sample`) + auto-close: commit `fe0deb0`.
- Validado contra produção: o finding `scheduler_heartbeat_without_runs` disparou às 18:42
  ainda com a lógica antiga (`window_minutes: 30` no evidence) e fechou sozinho às 20:17
  depois do deploy da lógica nova — primeira confirmação real de que o auto-close funciona
  em produção.
- **Pendente de confirmar**: que o deploy do commit `fe0deb0` está de fato ativo e estável
  no `autohunter-scheduler.service` (o fechamento às 20:17 é evidência forte, mas vale
  observar mais um ciclo antes de considerar 100% validado).
