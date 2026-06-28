#!/usr/bin/env bash
# Uso: ./scripts/pi_load_probe.sh [intervalo_seg] [arquivo_csv]
# Amostra RAM disponível, pressão de I/O e nº de processos chromium ao longo do tempo.
set -euo pipefail
INTERVAL="${1:-15}"
OUT="${2:-pi_load_probe_$(date +%Y%m%d_%H%M%S).csv}"

echo "ts,mem_total_mb,mem_avail_mb,swap_used_mb,load1,chromium_procs,chromium_rss_mb" > "$OUT"
echo "Coletando a cada ${INTERVAL}s em ${OUT} (Ctrl-C para parar)"

while true; do
  ts=$(date -Iseconds)
  mem_total=$(awk '/MemTotal/{printf "%.0f",$2/1024}' /proc/meminfo)
  mem_avail=$(awk '/MemAvailable/{printf "%.0f",$2/1024}' /proc/meminfo)
  swap_used=$(awk '/SwapTotal/{t=$2}/SwapFree/{f=$2} END{printf "%.0f",(t-f)/1024}' /proc/meminfo)
  load1=$(awk '{print $1}' /proc/loadavg)
  chromium_procs=$(pgrep -c -f 'chrom(e|ium)' || echo 0)
  chromium_rss=$(ps -C chrome,chromium -o rss= 2>/dev/null | awk '{s+=$1} END{printf "%.0f", s/1024}' || echo 0)
  echo "${ts},${mem_total},${mem_avail},${swap_used},${load1},${chromium_procs},${chromium_rss}" >> "$OUT"
  sleep "$INTERVAL"
done
