#!/bin/bash

BASE_URL="${BASE_URL:-http://localhost:8000}"
FIXTURES_DIR="${FIXTURES_DIR:-$(dirname "$(realpath "$0")")}"
PASS=0
FAIL=0
BASELINE=0

echo "Polycr Fixture Suite - /correct Pipeline"
echo "========================================"
echo "Testing against: $BASE_URL"
echo ""

# Health check
if ! timeout 5 curl -sf "$BASE_URL/health" >/dev/null 2>&1; then
  echo "ERROR: $BASE_URL unreachable"
  exit 1
fi

declare -a ROWS

for fix in $(find "$FIXTURES_DIR" -mindepth 1 -maxdepth 1 -type d -name '[0-9]*' | sort); do
  name=$(basename "$fix")
  input="$fix/input.jpg"
  expected_file="$fix/expected.json"
  
  [ -f "$input" ] || continue
  
  # POST to /correct (text-region clustering + OSD orient + perspective warp + OSD2 second-pass)
  out_file=$(mktemp /tmp/correct-out.XXX.jpg)
  hdr_file=$(mktemp /tmp/correct-h.XXX)
  http=$(timeout 30 curl -s -o "$out_file" -D "$hdr_file" -w "%{http_code}" -X POST -F "file=@$input" "$BASE_URL/correct" 2>/dev/null)
  
  # Extract response headers (case-insensitive, strip carriage return)
  status=$(grep -i '^x-redetect-status:' "$hdr_file" 2>/dev/null | tr -d '\r' | awk '{print $2}' || echo "unknown")
  rotation=$(grep -i '^x-pre-crop-rotation:' "$hdr_file" 2>/dev/null | tr -d '\r' | awk '{print $2}' || echo "0")
  osd2_rot=$(grep -i '^x-osd2-rotation:' "$hdr_file" 2>/dev/null | tr -d '\r' | awk '{print $2}' || echo "0")
  osd2_conf=$(grep -i '^x-osd2-confidence:' "$hdr_file" 2>/dev/null | tr -d '\r' | awk '{print $2}' || echo "0.00")
  w_out=$(grep -i '^x-output-width:' "$hdr_file" 2>/dev/null | tr -d '\r' | awk '{print $2}' || echo "0")
  h_out=$(grep -i '^x-output-height:' "$hdr_file" 2>/dev/null | tr -d '\r' | awk '{print $2}' || echo "0")
  
  rm -f "$out_file" "$hdr_file"
  
  # Compute aspect ratio (h/w)
  aspect="0.00"
  if [ "$w_out" -gt 0 ] 2>/dev/null; then
    aspect=$(awk "BEGIN { printf \"%.2f\", $h_out / $w_out }")
  fi
  
  # Check against expected.json assertions
  if [ -f "$expected_file" ]; then
    must_portrait=$(grep -o '"must_be_portrait":[[:space:]]*[a-z]*' "$expected_file" 2>/dev/null | head -1 | awk -F: '{print $2}' | tr -d ' ' || echo "false")
    aspect_min=$(grep -o '"aspect_min":[[:space:]]*[0-9.]*' "$expected_file" 2>/dev/null | head -1 | awk -F: '{print $2}' | tr -d ' ')
    aspect_max=$(grep -o '"aspect_max":[[:space:]]*[0-9.]*' "$expected_file" 2>/dev/null | head -1 | awk -F: '{print $2}' | tr -d ' ')
    status_not=$(grep -o '"status_not":[[:space:]]*"[^"]*"' "$expected_file" 2>/dev/null | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
    
    fail_reasons=""
    
    # HTTP 200 check
    [ "$http" != "200" ] && fail_reasons+=" http=$http"
    
    # Portrait check
    if [ "$must_portrait" = "true" ]; then
      if [ "$h_out" -le "$w_out" ] 2>/dev/null; then
        fail_reasons+=" not-portrait($h_out<=$w_out)"
      fi
    fi
    
    # Aspect min check
    if [ -n "$aspect_min" ]; then
      cmp=$(awk "BEGIN { print ($aspect < $aspect_min) ? 1 : 0 }")
      [ "$cmp" = "1" ] && fail_reasons+=" aspect<$aspect_min"
    fi
    
    # Aspect max check
    if [ -n "$aspect_max" ]; then
      cmp=$(awk "BEGIN { print ($aspect > $aspect_max) ? 1 : 0 }")
      [ "$cmp" = "1" ] && fail_reasons+=" aspect>$aspect_max"
    fi
    
    # Status exclusion check
    if [ -n "$status_not" ] && [ "$status" = "$status_not" ]; then
      fail_reasons+=" status=$status"
    fi
    
    if [ -z "$fail_reasons" ]; then
      ((PASS++))
      result="PASS"
    else
      ((FAIL++))
      result="FAIL$fail_reasons"
    fi
  else
    ((BASELINE++))
    result="BASELINE"
  fi
  
  ROWS+=("$name|$status|$rotation|$osd2_rot|$osd2_conf|${w_out}x${h_out}|$aspect|$result")
done

echo
echo "========================================"
echo "Results: $PASS PASS | $FAIL FAIL | $BASELINE BASELINE"
echo
printf "%-22s %-12s %-5s %-7s %-6s %-10s %-7s %s\n" "Fixture" "Status" "Rot" "OSD2R" "OSD2C" "Dims" "Aspect" "Result"
echo "----------------------------------------------------------------------------------------------------"
for r in "${ROWS[@]}"; do
  IFS='|' read -r f s rot o2r o2c d a res <<< "$r"
  printf "%-22s %-12s %-5s %-7s %-6s %-10s %-7s %s\n" "$f" "$s" "$rot" "$o2r" "$o2c" "$d" "$a" "$res"
done

[ "$FAIL" -gt 0 ] && exit 1 || exit 0
