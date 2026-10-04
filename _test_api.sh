#!/usr/bin/env bash
# End-to-end HTTP check of the running Lunar web app.
# Exercises every route the page and the WhatsApp extension use.
# Run:  bash _test_api.sh
set -u
BASE="http://127.0.0.1:8765"
pass=0; fail=0

check() { # name expected actual
  if [ "$2" = "$3" ]; then printf '  ok   %-46s %s\n' "$1" "$3"; pass=$((pass+1));
  else printf '  FAIL %-46s expected %s got %s\n' "$1" "$2" "$3"; fail=$((fail+1)); fi
}

code() { curl -s -m 15 -o /tmp/_api_body -w '%{http_code}' "$@"; }

echo "=== GET routes ==="
check "GET /"                 200 "$(code $BASE/)"
check "GET /lunar.html"       200 "$(code $BASE/lunar.html)"
check "GET /bogus"            404 "$(code $BASE/bogus)"
check "GET /jarvis.html"      404 "$(code $BASE/jarvis.html)"
check "GET /api/state"        200 "$(code $BASE/api/state)"
grep -q '"status"' /tmp/_api_body && { printf '  ok   %-46s\n' "GET /api/state has status"; pass=$((pass+1)); } \
                                  || { printf '  FAIL %-46s\n' "GET /api/state has status"; fail=$((fail+1)); }

echo "=== POST routes ==="
check "POST /api/command hello"  200 "$(code -X POST -H 'Content-Type: application/json' -d '{"command":"hello"}' $BASE/api/command)"
grep -q "Hello. I'm ready." /tmp/_api_body && { printf '  ok   %-46s\n' "command actually executed"; pass=$((pass+1)); } \
                                    || { printf '  FAIL %-46s\n' "command actually executed"; fail=$((fail+1)); }

check "POST /api/command non-text" 400 "$(code -X POST -H 'Content-Type: application/json' -d '{"command":123}' $BASE/api/command)"

check "POST /api/command junk"   200 "$(code -X POST -H 'Content-Type: application/json' -d '{"command":"zzzz nonsense zzzz"}' $BASE/api/command)"
grep -q "not recognized" /tmp/_api_body && { printf '  ok   %-46s\n' "junk falls through to not-recognized"; pass=$((pass+1)); } \
                                      || { printf '  FAIL %-46s\n' "junk falls through to not-recognized"; fail=$((fail+1)); }

check "POST /api/command bad JSON" 400 "$(code -X POST -H 'Content-Type: application/json' -d '{not json' $BASE/api/command)"
check "POST /api/wake bad payload" 400 "$(code -X POST -H 'Content-Type: application/json' -d '{"enabled":"yes"}' $BASE/api/wake)"
check "POST /api/wake valid"       200 "$(code -X POST -H 'Content-Type: application/json' -d '{"enabled":false}' $BASE/api/wake)"
check "POST /api/whatsapp no ext"  403 "$(code -X POST -H 'Content-Type: application/json' -d '{"messages":[]}' $BASE/api/whatsapp/snapshot)"
check "POST /api/unknown"          404 "$(code -X POST -H 'Content-Type: application/json' -d '{}' $BASE/api/nope)"

echo
echo "passed: $pass   failed: $fail"
[ "$fail" -eq 0 ]