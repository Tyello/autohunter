# DB Review SQL — AutoHunter (PostgreSQL)

> Objetivo: consultas prontas para diagnóstico em staging/prod. Não executar cegamente em horário crítico.

## 1) Maiores tabelas
```sql
select
  schemaname,
  relname as table_name,
  pg_size_pretty(pg_total_relation_size(relid)) as total_size,
  pg_size_pretty(pg_relation_size(relid)) as table_size,
  pg_size_pretty(pg_total_relation_size(relid) - pg_relation_size(relid)) as index_size,
  n_live_tup
from pg_stat_user_tables
order by pg_total_relation_size(relid) desc
limit 30;
```

## 2) Índices existentes por tabela
```sql
select
  schemaname,
  tablename,
  indexname,
  indexdef
from pg_indexes
where schemaname = 'public'
order by tablename, indexname;
```

## 3) Índices pouco usados (candidatos a revisão)
```sql
select
  s.schemaname,
  s.relname as table_name,
  s.indexrelname as index_name,
  s.idx_scan,
  pg_size_pretty(pg_relation_size(s.indexrelid)) as index_size
from pg_stat_user_indexes s
join pg_index i on i.indexrelid = s.indexrelid
where s.schemaname = 'public'
  and s.idx_scan = 0
  and not i.indisunique
order by pg_relation_size(s.indexrelid) desc;
```

## 4) Top queries via pg_stat_statements
```sql
-- requer extensão habilitada
select
  calls,
  total_exec_time,
  mean_exec_time,
  rows,
  query
from pg_stat_statements
order by total_exec_time desc
limit 50;
```

```sql
-- filtro aproximado para objetos do AutoHunter
select
  calls,
  total_exec_time,
  mean_exec_time,
  rows,
  query
from pg_stat_statements
where query ilike any (array[
  '%notifications%',
  '%wishlists%',
  '%wishlist_filters%',
  '%wishlist_tokens%',
  '%car_listings%',
  '%scrape_jobs%',
  '%source_runs%',
  '%source_states%',
  '%system_logs%'
])
order by total_exec_time desc
limit 100;
```

## 5) EXPLAIN — notifications 24h por wishlist
```sql
explain (analyze, buffers)
select count(*)
from notifications
where wishlist_id = $1
  and status = 'sent'
  and sent_at >= now() - interval '24 hours';
```

## 6) EXPLAIN — fila sender pendente
```sql
explain (analyze, buffers)
select id, user_id, wishlist_id, car_listing_id
from notifications
where status in ('queued','processing')
  and (next_attempt_at is null or next_attempt_at <= now())
order by created_at asc
limit 200;
```

## 7) EXPLAIN — jobs dequeue
```sql
explain (analyze, buffers)
select id
from scrape_jobs
where queue = $1
  and status = 'queued'
  and run_at <= now()
order by run_at asc, priority desc, created_at asc
limit 1;
```

## 8) EXPLAIN — admin heartbeat
```sql
explain (analyze, buffers)
select created_at, level
from system_logs
where component = 'scheduler'
  and message = 'heartbeat'
order by created_at desc
limit 1;
```

## 9) EXPLAIN — tracking list por wishlist
```sql
explain (analyze, buffers)
select wtl.*, cl.id, cl.price, cl.url, cl.title, cl.updated_at
from wishlist_tracked_listings wtl
left join car_listings cl on cl.id = wtl.car_listing_id
where wtl.wishlist_id = $1
order by wtl.slot asc;
```

## 10) EXPLAIN — activity/digest por wishlist
```sql
explain (analyze, buffers)
select wla.*, cl.id, cl.price, cl.url
from wishlist_listing_activity wla
join car_listings cl on cl.id = wla.car_listing_id
where wla.wishlist_id = $1
  and wla.status = 'active'
  and cl.is_sold = false
order by wla.last_seen_at desc, wla.created_at desc
limit 100;
```
