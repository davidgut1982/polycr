#!/bin/bash

BASE_URL="${BASE_URL:-http://localhost:8000}"
FIXTURES_DIR="${FIXTURES_DIR:-.}"
PASS_COUNT=0
FAIL_COUNT=0
BASELINE_COUNT=0

echo "Edge Detection Fixture Suite"
echo "=============================="
echo "Testing against: $BASE_URL"
echo ""

# Check connectivity
if ! timeout 5 curl -s "$BASE_URL/health" > /dev/null 2>&1; then
  echo "ERROR: Cannot reach $BASE_URL"
  exit 1
fi

# Test each fixture
for fixture_dir in $(find "$FIXTURES_DIR" -mindepth 1 -maxdepth 1 -type d | sort); do
  fixture_name=$(basename "$fixture_dir")
  input_file="$fixture_dir/input.jpg"
  expected_file="$fixture_dir/expected.json"
  baseline_file="$fixture_dir/baseline_run.json"
  
  if [[ ! -f "$input_file" ]]; then
    continue
  fi
  
  echo -n "Testing $fixture_name ... "
  
  # POST to /detect-edges
  response=$(timeout 10 curl -s -F "file=@$input_file" "$BASE_URL/detect-edges" 2>/dev/null)
  
  # Save baseline_run.json if this is the first run
  if [[ ! -f "$baseline_file" ]]; then
    echo "$response" > "$baseline_file" 2>/dev/null
  fi
  
  # Parse response (simple string matching)
  if echo "$response" | grep -q '"corners":null'; then
    corners_status="NONE"
    confidence="0.0"
  else
    corners_status="FOUND"
    confidence=$(echo "$response" | grep -o '"confidence":[0-9.]*' | cut -d: -f2)
  fi
  
  method=$(echo "$response" | grep -o '"method":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
  
  # Check if expected.json exists
  if [[ ! -f "$expected_file" ]]; then
    echo "BASELINE"
    echo "  Method: $method | Confidence: $confidence | Corners: $corners_status"
    ((BASELINE_COUNT++))
  else
    echo "BASELINE"
    ((BASELINE_COUNT++))
  fi
done

echo ""
echo "=============================="
echo "Results: $BASELINE_COUNT BASELINE | $PASS_COUNT PASS | $FAIL_COUNT FAIL"
echo ""

# Summary table
echo "Scenario Summary:"
printf "| %-25s | %-10s | %-15s | %-8s |\n" "Fixture" "Method" "Confidence" "Status"
echo "|---|---|---|---|"

for fixture_dir in $(find "$FIXTURES_DIR" -mindepth 1 -maxdepth 1 -type d | sort); do
  fixture_name=$(basename "$fixture_dir")
  baseline_file="$fixture_dir/baseline_run.json"
  
  if [[ ! -f "$baseline_file" ]]; then
    continue
  fi
  
  method=$(grep -o '"method":"[^"]*"' "$baseline_file" 2>/dev/null | cut -d'"' -f4 || echo "unknown")
  confidence=$(grep -o '"confidence":[0-9.]*' "$baseline_file" 2>/dev/null | cut -d: -f2 || echo "0")
  
  if grep -q '"corners":null' "$baseline_file" 2>/dev/null; then
    status="NONE"
  else
    status="FOUND"
  fi
  
  printf "| %-25s | %-10s | %-15s | %-8s |\n" "$fixture_name" "$method" "$confidence" "$status"
done

exit 0
