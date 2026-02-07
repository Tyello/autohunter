-- Seed source_configs com defaults para todas as fontes conhecidas
-- Execute com: psql $DATABASE_URL -f migrations/seed_source_configs.sql

-- HTTP-Only sources
INSERT INTO source_configs (
    source, enabled, sched_minutes, fetch_mode, 
    circuit_breaker_threshold, circuit_breaker_cooldown_s,
    extra
)
VALUES
    -- iCarros: API pública, HTTP estável
    ('icarros', true, 30, 'http', 3, 180,
     '{
         "http_timeout_s": 20,
         "http_min_delay_ms": 200,
         "http_max_delay_ms": 600,
         "extractor_version": "v2"
     }'::jsonb),
    
    -- Kavak: API REST
    ('kavak', true, 45, 'http', 3, 180,
     '{
         "http_timeout_s": 25,
         "http_min_delay_ms": 300,
         "http_max_delay_ms": 800
     }'::jsonb),
    
    -- Chaves na Mão: SSR tradicional
    ('chavesnamao', true, 60, 'http', 5, 300,
     '{
         "http_timeout_s": 30,
         "http_min_delay_ms": 250,
         "http_max_delay_ms": 700
     }'::jsonb)

ON CONFLICT (source) 
DO UPDATE SET
    fetch_mode = EXCLUDED.fetch_mode,
    extra = EXCLUDED.extra,
    circuit_breaker_threshold = EXCLUDED.circuit_breaker_threshold,
    circuit_breaker_cooldown_s = EXCLUDED.circuit_breaker_cooldown_s;


-- Hybrid sources (HTTP + browser fallback)
INSERT INTO source_configs (
    source, enabled, sched_minutes, fetch_mode, 
    browser_fallback_enabled,
    circuit_breaker_threshold, circuit_breaker_cooldown_s,
    extra
)
VALUES
    -- Mercado Livre: prioriza HTTP, usa browser se bloqueado
    ('mercadolivre', true, 20, 'http', true, 5, 300,
     '{
         "http_timeout_s": 25,
         "http_min_delay_ms": 250,
         "http_max_delay_ms": 900,
         "browser_timeout_ms": 35000,
         "browser_wait_until": "domcontentloaded"
     }'::jsonb),
    
    -- OLX: HTTP + fallback quando bloqueado
    ('olx', true, 30, 'http', true, 5, 300,
     '{
         "http_timeout_s": 25,
         "http_min_delay_ms": 300,
         "http_max_delay_ms": 800,
         "browser_timeout_ms": 40000,
         "browser_wait_until": "networkidle"
     }'::jsonb)

ON CONFLICT (source)
DO UPDATE SET
    fetch_mode = EXCLUDED.fetch_mode,
    browser_fallback_enabled = EXCLUDED.browser_fallback_enabled,
    extra = EXCLUDED.extra,
    circuit_breaker_threshold = EXCLUDED.circuit_breaker_threshold,
    circuit_breaker_cooldown_s = EXCLUDED.circuit_breaker_cooldown_s;


-- Browser-Required sources (sempre usa Playwright)
INSERT INTO source_configs (
    source, enabled, sched_minutes, fetch_mode, 
    force_browser,
    circuit_breaker_threshold, circuit_breaker_cooldown_s,
    extra
)
VALUES
    -- Webmotors: SPA React + PerimeterX
    ('webmotors', false, 60, 'browser', true, 5, 600,
     '{
         "browser_timeout_ms": 40000,
         "browser_wait_until": "networkidle",
         "browser_min_delay_ms": 1000,
         "browser_max_delay_ms": 2000,
         "max_concurrent_requests": 1
     }'::jsonb),
    
    -- GoGarage: SPA Vue
    ('gogarage', false, 90, 'browser', true, 5, 600,
     '{
         "browser_timeout_ms": 45000,
         "browser_wait_until": "networkidle"
     }'::jsonb),
    
    -- Mobiauto: híbrido com proteção
    ('mobiauto', false, 60, 'browser', true, 5, 600,
     '{
         "browser_timeout_ms": 40000,
         "browser_wait_until": "domcontentloaded"
     }'::jsonb)

ON CONFLICT (source)
DO UPDATE SET
    fetch_mode = EXCLUDED.fetch_mode,
    force_browser = EXCLUDED.force_browser,
    extra = EXCLUDED.extra,
    circuit_breaker_threshold = EXCLUDED.circuit_breaker_threshold,
    circuit_breaker_cooldown_s = EXCLUDED.circuit_breaker_cooldown_s;


-- Nota: sources com enabled=false não serão executadas até serem habilitadas manualmente
COMMENT ON TABLE source_configs IS 'Configuração de fontes de scraping (DB é source of truth)';
