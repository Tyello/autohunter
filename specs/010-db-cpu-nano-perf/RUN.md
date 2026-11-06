# RUN 010 (append-only)

- 2026-11-06 spec escrita; branch perf/db-cpu-nano-optimizations criada; autorizações: DDL, mode on, janela 30min.
- 2026-11-06 etapa 1: executor OK (21 testes, TDD red->green); aguardando spec-reviewer. Etapas 2,3,4 em execucao paralela.
- 2026-11-06 etapa 2: executor OK (20 testes). Achado do executor: _next_wait podia cair abaixo do base se teto<base; orquestrador corrigiu com piso max(seconds, ...) + teste. Aguardando revisor.
- 2026-11-06 etapa 3: executor OK (18 testes, red->green no teste de 1 query). found_drop (N+1 real por source) NAO alterado: fora de D7/REQ-008; candidato a etapa futura.
- 2026-11-06 etapa 4: executor OK (18 testes); spec-reviewer APROVADO (nenhum leitor de pipeline_summary em system_logs).
- 2026-11-06 etapa 3: spec-reviewer APROVADO (lacuna nao-bloqueante: fronteiras start/b_start/b_end exatas sem teste).
- 2026-11-06 etapa 1: spec-reviewer APROVADO.
- 2026-11-06 etapa 5: executor ESCALOU (gatilho 4) - teste pre-existente afirma last_seen_at avancando a cada upsert. Orquestrador decide D10 (reescrever teste p/ novo contrato 30min, decisao do usuario). Tambem revisada D8 (manter location_trgm). Executor retomado.
- 2026-11-06 etapa 2: spec-reviewer APROVADO (25 testes; mutacao em HEAD: 13 falhas). Orquestrador limitou expoente do streak (min(streak,16)) + teste.
- 2026-11-06 etapa 6 (orquestrador, aguardando revisor senior): migration p4_listing_last_seen_idx (head unico; upgrade/downgrade SQL offline OK; revision id encurtado p/ <32 chars), model Index adicionado, DATABASE_SCHEMA.md regenerado (--check OK). NUNCA rodar alembic upgrade com DATABASE_URL real fora da janela de operacao (etapa 7).
- 2026-11-06 etapa 5: executor ESCALOU 2a vez (teste pre-existente test_car_listings_repo_bulk_homogenize: mock sobrescrevia captured["stmt"] com o novo SELECT de ids). Orquestrador editou 1 linha (setdefault) - detalhe de teste, asserção preservada. Recorte amplo -k (listing/upsert/ingest/presence/repo/autopilot/worker/system_log/scrape/notification): exit 0. LACUNA: testes PG (xmax: inserted_new/updated) pulados sem TEST_DATABASE_URL. Enviado ao spec-reviewer-senior (etapas 5+6).
- 2026-11-06 spec-reviewer-senior: etapa 5 APROVADA c/ ressalvas, etapa 6 APROVADA c/ ressalvas (sem DVG bloqueante). Ressalvas: (a) PG pula linha mas MANTEM o row lock -> ganho = sem tupla morta/indices/WAL, nao "zero escrita"; medir n_dead_tup/n_tup_upd/hot apos deploy; (b) testes marcados postgres (xmax: inserted_new/updated) NAO executados; (c) CREATE INDEX CONCURRENTLY pode deixar indice INVALID -> checar indisvalid; (d) REQ-009 texto corrigido (2 indices, nao 3).
