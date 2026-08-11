#!/usr/bin/env bash
# =============================================================================
# Phase 1 — Prepare the Space: environment readiness check for LINA's desktop
# home. Verifies directory structure, local databases, ports, resources,
# toolchain, and configuration. Exit 0 when the space is ready.
#
#   scripts/check-environment.sh
# =============================================================================
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

PASS=0; FAIL=0; WARN=0
ok()   { PASS=$((PASS+1)); echo "  [ OK ] $1"; }
warn() { WARN=$((WARN+1)); echo "  [WARN] $1"; }
fail() { FAIL=$((FAIL+1)); echo "  [FAIL] $1"; }

echo "LINA environment check — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Repo: $ROOT"
echo

# ── 1. Directory structure ───────────────────────────────────────────────────
echo "── Directory structure ──"
for d in backend/lina backend/db backend/ipc-core backend/triton docs scripts runtime; do
    if [ -d "$d" ]; then ok "$d exists"; else fail "$d MISSING"; fi
done

# ── 2. Runtime storage (her desk) ────────────────────────────────────────────
echo
echo "── Runtime storage ──"
for d in runtime runtime/logs runtime/state runtime/ipc runtime/workspace; do
    if [ -d "$d" ]; then
        if [ -w "$d" ]; then ok "$d (writable)"; else fail "$d NOT writable"; fi
    else
        if mkdir -p "$d" 2>/dev/null; then ok "$d created"; else fail "$d could not be created"; fi
    fi
done

# ── 3. Local databases ───────────────────────────────────────────────────────
echo
echo "── Local databases ──"
if command -v docker >/dev/null 2>&1; then
    for svc in postgres dragonfly; do
        st=$(docker compose ps --format '{{.Name}} {{.Status}}' 2>/dev/null | grep "collabsmart-$svc" || true)
        case "$st" in
            *healthy*) ok "$svc running (healthy)" ;;
            *Up*)      warn "$svc up, health not yet reported" ;;
            *)         fail "$svc not running — docker compose up -d $svc" ;;
        esac
    done
else
    warn "docker not found — cannot verify local databases"
fi

# ── 4. Ports ─────────────────────────────────────────────────────────────────
echo
echo "── Ports ──"
for port in 5432 6379 8001; do
    if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
        exec 3>&- 3<&- || true
        ok "port $port open"
    else
        warn "port $port closed"
    fi
done

# ── 5. System resources ──────────────────────────────────────────────────────
echo
echo "── System resources ──"
cpus=$(nproc 2>/dev/null || echo "?")
mem_free_mb=$(free -m 2>/dev/null | awk '/Mem:/ {print $7}')
disk_free_gb=$(df -Pk . 2>/dev/null | awk 'NR==2 {printf "%.1f", $4/1024/1024}')
echo "  CPUs: $cpus (want >= 2)"
[ "$cpus" = "?" ] || [ "$cpus" -ge 2 ] && ok "CPU count: $cpus" || warn "fewer than 2 CPUs"
if [ -n "$mem_free_mb" ] && [ "$mem_free_mb" -ge 2048 ]; then
    ok "available RAM: ${mem_free_mb} MB (want >= 2048)"
else
    warn "available RAM: ${mem_free_mb:-?} MB (want >= 2048)"
fi
if [ -n "$disk_free_gb" ]; then
    if awk "BEGIN {exit !($disk_free_gb >= 5)}"; then ok "free disk: ${disk_free_gb} GB (want >= 5)"; else warn "free disk: ${disk_free_gb} GB (want >= 5)"; fi
fi

# ── 6. Toolchain ─────────────────────────────────────────────────────────────
echo
echo "── Toolchain ──"
for tool in python3 docker rustc cargo; do
    if command -v "$tool" >/dev/null 2>&1; then
        ok "$tool: $($tool --version 2>&1 | head -1)"
    else
        fail "$tool missing"
    fi
done

# ── 7. Configuration ─────────────────────────────────────────────────────────
echo
echo "── Configuration ──"
if [ -f .env ]; then ok ".env present"; else fail ".env missing"; fi
for k in AI_PROVIDER AI_PROVIDERS DEEPSEEK_API_KEY OPENROUTER_API_KEY GEMINI_API_KEY; do
    v=$(grep -E "^$k=" .env 2>/dev/null | head -1 | cut -d= -f2-)
    if [ -n "$v" ] && [ "$v" != '""' ]; then
        case "$v" in
            *your-*|*API-Key*|*xxxxx*|*XXXXX*|"<"*">"*)
                warn "$k looks like a placeholder — provider will not activate"
                ;;
            *)
                ok "$k set"
                ;;
        esac
    else
        warn "$k not set"
    fi
 done

# ── 8. LINA service ──────────────────────────────────────────────────────────
echo
echo "── LINA service ──"
if curl -sf --max-time 5 http://localhost:8001/health >/tmp/lina_health.$$ 2>/dev/null; then
    db=$(grep -o '"database_connected":[a-z]*' /tmp/lina_health.$$ | cut -d: -f2)
    bridge=$(grep -o '"bridge_available":[a-z]*' /tmp/lina_health.$$ | cut -d: -f2)
    voices=$(grep -o '"voice_providers":\[[^]]*\]' /tmp/lina_health.$$)
    ok "health endpoint responds (db:$db bridge:$bridge voices:$voices)"
    rm -f /tmp/lina_health.$$
else
    warn "no LINA service on :8001 — run the aiomisc entrypoint (python -m lina_service)"
fi

# ── 9. Memory Imprint System ──────────────────────────────────────────────────
echo
echo "── Memory Imprint System ──"
pg_user=$(grep -E '^POSTGRES_USER=' .env 2>/dev/null | head -1 | cut -d= -f2-)
pg_db=$(grep -E '^POSTGRES_DB=' .env 2>/dev/null | head -1 | cut -d= -f2-)
if command -v docker >/dev/null 2>&1 && [ -n "$pg_user" ] && [ -n "$pg_db" ]; then
    for tbl in lina_memory_items lina_promotion_log lina_feedback lina_learning_patterns lina_adaptations; do
        exists=$(docker exec collabsmart-postgres psql -U "$pg_user" -d "$pg_db" -tAc "SELECT to_regclass('public.$tbl');" 2>/dev/null)
        if [ "$exists" = "$tbl" ] || [ "$exists" = "public.$tbl" ]; then
            ok "MPS table $tbl present"
        else
            fail "MPS table $tbl MISSING"
        fi
    done
else
    warn "cannot verify MPS tables (docker or .env db config missing)"
fi

echo
echo "──────────────────────────────────────────────────────────────"
echo "Result: $PASS ok, $WARN warnings, $FAIL failures"
if [ "$FAIL" -eq 0 ]; then
    echo "The space is ready. LINA can move in."
    exit 0
else
    echo "Fix the failures above before continuing (warnings are advisory)."
    exit 1
fi
