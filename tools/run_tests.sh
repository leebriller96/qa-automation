#!/usr/bin/env bash
# run_tests.sh — 대상 경로 아래의 프로젝트(서비스)들을 재귀 탐색해 언어별 테스트 러너를 실행하고
#                결과를 reports/.tests/ 에 모은 뒤 summarize_results.py 로 집계한다.
#
# 사용법: tools/run_tests.sh [대상경로] [--timeout <초>] [--keep]
#   대상경로   기본값 input/  (상대경로는 현재 디렉토리 기준)
#   --timeout  러너 1회 실행 제한 시간(초). 기본 900. 초과 시 status=timeout 으로 기록.
#   --keep     이전 실행 결과(reports/.tests/)를 지우지 않음. 기본은 실행 전 삭제.
#
# 산출물 (reports/.tests/):
#   runs.tsv            프로젝트별 실행 기록 (id, lang, dir, status, exit_code, result_path, stdout_path, command)
#   <id>-stdout.txt     러너 표준출력/에러
#   <id>-*.xml|.json    러너의 기계판독 결과 (junit XML, jest JSON, go test JSON, trx 등)
#   summary.json/.md    summarize_results.py 가 만든 집계 (통과/실패/에러/스킵 + 실패 원인)
#
# status 값:
#   ran               러너를 실행함 (exit_code 참고. 실패 테스트가 있으면 0이 아님)
#   timeout           제한 시간 초과로 중단됨
#   runner-missing    러너(pytest/npm/mvn 등)가 설치돼 있지 않음
#   deps-missing      의존성 미설치 (예: node_modules 없음)
#   no-test-script    package.json 에 test 스크립트가 없고 알려진 러너도 없음
#
# 종료 코드: 0 = 하나 이상 실행함, 2 = 실행 가능한 프로젝트/러너 없음
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT/reports/.tests"
TIMEOUT_SEC=900
KEEP=0
TARGET=""

while [ $# -gt 0 ]; do
  case "$1" in
    --timeout) TIMEOUT_SEC="${2:-900}"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) TARGET="$1"; shift ;;
  esac
done
TARGET="${TARGET:-$ROOT/input}"
[ -d "$TARGET" ] || { echo "[run_tests] 대상 디렉토리가 없습니다: $TARGET"; exit 2; }
TARGET="$(cd "$TARGET" && pwd)"

# 탐색에서 제외할 디렉토리 (의존성/빌드 산출물/가상환경). node_modules 안의 .py 등으로 오탐하지 않도록 한다.
EXCLUDE_DIRS=(node_modules .venv venv env .git __pycache__ .pytest_cache .mypy_cache .tox
              target build dist out .gradle .idea .vscode site-packages coverage .next bin obj)

have() { command -v "$1" >/dev/null 2>&1; }

# Git Bash(MSYS)의 /c/... 경로를 Windows 네이티브(C:/...)로 바꾼다. 결과 파일을 파이썬/러너가 읽을 수 있어야 하기 때문.
native() { if have cygpath; then cygpath -m "$1"; else printf '%s\n' "$1"; fi; }
# ';' 로 구분된 glob 목록 각각을 네이티브 경로로 변환
native_globs() {
  local IFS=';' out=() g
  for g in $1; do [ -n "$g" ] && out+=("$(native "$g")"); done
  ( IFS=';'; printf '%s\n' "${out[*]-}" )
}

# find 용 prune 식을 만든다: \( -name a -o -name b ... \) -prune
prune_expr=()
for d in "${EXCLUDE_DIRS[@]}"; do
  [ ${#prune_expr[@]} -gt 0 ] && prune_expr+=(-o)
  prune_expr+=(-name "$d")
done

# 마커 파일을 찾아 그 디렉토리를 반환한다 (제외 디렉토리는 내려가지 않음). 깊이 순 정렬.
find_marker_dirs() {
  local name_expr=()
  for n in "$@"; do
    [ ${#name_expr[@]} -gt 0 ] && name_expr+=(-o)
    name_expr+=(-name "$n")
  done
  find "$TARGET" \( "${prune_expr[@]}" \) -prune -o -type f \( "${name_expr[@]}" \) -print0 2>/dev/null \
    | xargs -0 -r -n1 dirname | sort -u | awk '{ print gsub("/","/"), $0 }' | sort -n | cut -d' ' -f2-
}

# 조상 디렉토리가 이미 목록에 있는 항목을 제거한다 (예: tests/conftest.py 가 별도 루트로 잡히지 않도록).
dedupe_nested() {
  local roots=() d r nested
  while IFS= read -r d; do
    [ -z "$d" ] && continue
    nested=0
    for r in "${roots[@]}"; do
      case "$d/" in "$r/"*) nested=1; break ;; esac
    done
    [ $nested -eq 0 ] && roots+=("$d")
  done
  printf '%s\n' "${roots[@]}"
}

# runs.tsv 기록: id lang dir status exit_code result_path stdout_path command
record() {
  local dir result stdout=""
  dir="$(native "$3")"
  result="$(native_globs "$6")"
  [ -n "$7" ] && stdout="$(native "$7")"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$dir" "$4" "$5" "$result" "$stdout" "$8" >> "$OUT_DIR/runs.tsv"
}

# 러너 실행: run_cmd <id> <dir> <command...>  → 전역 LAST_STATUS/LAST_EXIT 설정
run_cmd() {
  local id="$1" dir="$2"; shift 2
  local stdout="$OUT_DIR/$id-stdout.txt"
  echo "[run_tests]   $ $*"
  if have timeout; then
    (cd "$dir" && timeout --kill-after=30 "$TIMEOUT_SEC" "$@") > "$stdout" 2>&1
  else
    (cd "$dir" && "$@") > "$stdout" 2>&1
  fi
  LAST_EXIT=$?
  if [ "$LAST_EXIT" -eq 124 ] || [ "$LAST_EXIT" -eq 137 ]; then
    LAST_STATUS=timeout
    echo "[run_tests]   ⏱ 제한 시간(${TIMEOUT_SEC}s) 초과"
  else
    LAST_STATUS=ran
  fi
  echo "[run_tests]   -> exit=$LAST_EXIT, stdout: ${stdout#$ROOT/}"
}

rel() { echo "${1#$TARGET/}"; }
mkid() { echo "$1-$(rel "$2" | tr '/ ' '__' | tr -c 'A-Za-z0-9_.\n-' '_')"; }

# ---------- 준비 ----------
if [ $KEEP -eq 0 ]; then rm -rf "$OUT_DIR"; fi
mkdir -p "$OUT_DIR"
[ -f "$OUT_DIR/runs.tsv" ] || printf 'id\tlang\tdir\tstatus\texit_code\tresult_path\tstdout_path\tcommand\n' > "$OUT_DIR/runs.tsv"

echo "[run_tests] 대상: $TARGET"
echo "[run_tests] 결과: $OUT_DIR (타임아웃 ${TIMEOUT_SEC}s)"
ran_any=0

# ---------- 1) Python (pytest) ----------
py_roots="$(find_marker_dirs pyproject.toml setup.py setup.cfg pytest.ini tox.ini requirements.txt conftest.py | dedupe_nested)"
if [ -z "$py_roots" ]; then
  # 마커가 없어도 .py 파일이 있으면 대상 루트 자체를 프로젝트로 본다
  if find "$TARGET" \( "${prune_expr[@]}" \) -prune -o -type f -name '*.py' -print -quit 2>/dev/null | grep -q . ; then
    py_roots="$TARGET"
  fi
fi
while IFS= read -r dir; do
  [ -n "$dir" ] && [ -d "$dir" ] || continue
  id="$(mkid py "$dir")"
  echo "[run_tests] [Python] $(rel "$dir")"
  # 프로젝트 가상환경이 있으면 그 인터프리터를 우선 사용
  PY=python; have python || PY=python3
  for cand in "$dir/.venv/Scripts/python.exe" "$dir/.venv/bin/python" "$dir/venv/Scripts/python.exe" "$dir/venv/bin/python"; do
    [ -x "$cand" ] && { PY="$cand"; break; }
  done
  if ! "$PY" -m pytest --version >/dev/null 2>&1; then
    echo "[run_tests]   pytest 미설치 (설치: $PY -m pip install pytest)"
    record "$id" python "$dir" runner-missing "" "" "" "$PY -m pytest"
    continue
  fi
  junit="$(native "$OUT_DIR/$id-junit.xml")"
  run_cmd "$id" "$dir" "$PY" -m pytest -q -p no:cacheprovider --junitxml="$junit" .
  record "$id" python "$dir" "$LAST_STATUS" "$LAST_EXIT" "$junit" "$OUT_DIR/$id-stdout.txt" "$PY -m pytest -q --junitxml=... ."
  ran_any=1
done <<< "$py_roots"

# ---------- 2) JavaScript / TypeScript (npm: jest / vitest / playwright / 기타) ----------
while IFS= read -r dir; do
  [ -n "$dir" ] && [ -d "$dir" ] || continue
  id="$(mkid js "$dir")"
  echo "[run_tests] [JS/TS] $(rel "$dir")"
  if ! have npm; then
    echo "[run_tests]   npm 미설치 (Node.js 설치 필요)"
    record "$id" js "$dir" runner-missing "" "" "" "npm test"
    continue
  fi
  if [ ! -d "$dir/node_modules" ]; then
    echo "[run_tests]   node_modules 없음 → 의존성 미설치 (cd $(rel "$dir") && npm ci)"
    record "$id" js "$dir" deps-missing "" "" "" "npm test"
    continue
  fi
  # test 스크립트와 사용하는 러너를 파악한다
  test_script="$(cd "$dir" && node -p "((require('./package.json').scripts||{}).test)||''" 2>/dev/null)"
  dev_deps="$(cd "$dir" && node -p "Object.keys(Object.assign({}, (p=require('./package.json')).dependencies, p.devDependencies)).join(' ')" 2>/dev/null)"
  runner=other
  case "$test_script $dev_deps" in
    *vitest*)     runner=vitest ;;
    *jest*)       runner=jest ;;
    *playwright*) runner=playwright ;;
  esac
  case "$test_script" in
    ""|"echo \"Error: no test specified\""*)
      has_script=0 ;;
    *) has_script=1 ;;
  esac
  case "$runner" in
    jest)
      out="$(native "$OUT_DIR/$id-jest.json")"
      if [ $has_script -eq 1 ]; then
        run_cmd "$id" "$dir" npm test --silent -- --ci --json --outputFile="$out"
      else
        run_cmd "$id" "$dir" npx --no-install jest --ci --json --outputFile="$out"
      fi ;;
    vitest)
      out="$(native "$OUT_DIR/$id-junit.xml")"
      if [ $has_script -eq 1 ]; then
        run_cmd "$id" "$dir" npm test --silent -- --run --reporter=junit --outputFile="$out"
      else
        run_cmd "$id" "$dir" npx --no-install vitest run --reporter=junit --outputFile="$out"
      fi ;;
    playwright)
      out="$(native "$OUT_DIR/$id-junit.xml")"
      export PLAYWRIGHT_JUNIT_OUTPUT_NAME="$out"
      if [ $has_script -eq 1 ]; then
        run_cmd "$id" "$dir" npm test --silent -- --reporter=junit
      else
        run_cmd "$id" "$dir" npx --no-install playwright test --reporter=junit
      fi
      unset PLAYWRIGHT_JUNIT_OUTPUT_NAME ;;
    *)
      if [ $has_script -eq 0 ]; then
        echo "[run_tests]   package.json 에 test 스크립트가 없고 알려진 러너(jest/vitest/playwright)도 없음"
        record "$id" js "$dir" no-test-script "" "" "" "npm test"
        continue
      fi
      out=""   # 기계판독 결과 없음 → stdout 만 남김
      run_cmd "$id" "$dir" npm test --silent ;;
  esac
  record "$id" js "$dir" "$LAST_STATUS" "$LAST_EXIT" "$out" "$OUT_DIR/$id-stdout.txt" "npm test ($runner)"
  ran_any=1
done < <(find_marker_dirs package.json | dedupe_nested)

# ---------- 3) Java / Kotlin (Maven / Gradle) ----------
while IFS= read -r dir; do
  [ -n "$dir" ] && [ -d "$dir" ] || continue
  id="$(mkid mvn "$dir")"
  echo "[run_tests] [Maven] $(rel "$dir")"
  MVN=""
  if [ -f "$dir/mvnw" ]; then MVN="./mvnw"; elif have mvn; then MVN=mvn; fi
  if [ -z "$MVN" ]; then
    echo "[run_tests]   mvn 미설치 (mvnw 래퍼도 없음)"
    record "$id" java "$dir" runner-missing "" "" "" "mvn test"
    continue
  fi
  run_cmd "$id" "$dir" $MVN -B -q test
  # surefire(단위)/failsafe(통합) 리포트 모두 집계 대상
  record "$id" java "$dir" "$LAST_STATUS" "$LAST_EXIT" "$dir/target/surefire-reports/TEST-*.xml;$dir/target/failsafe-reports/TEST-*.xml" "$OUT_DIR/$id-stdout.txt" "$MVN -B -q test"
  ran_any=1
done < <(find_marker_dirs pom.xml | dedupe_nested)

while IFS= read -r dir; do
  [ -n "$dir" ] && [ -d "$dir" ] || continue
  # settings.gradle 이 있는 상위가 있으면 그것이 진짜 루트(멀티모듈). dedupe_nested 가 이미 처리.
  id="$(mkid gradle "$dir")"
  echo "[run_tests] [Gradle] $(rel "$dir")"
  GRADLE=""
  if [ -f "$dir/gradlew" ]; then GRADLE="./gradlew"; elif have gradle; then GRADLE=gradle; fi
  if [ -z "$GRADLE" ]; then
    echo "[run_tests]   gradle 미설치 (gradlew 래퍼도 없음)"
    record "$id" java "$dir" runner-missing "" "" "" "gradle test"
    continue
  fi
  [ "$GRADLE" = "./gradlew" ] && chmod +x "$dir/gradlew" 2>/dev/null
  run_cmd "$id" "$dir" $GRADLE test --continue --console=plain -q
  record "$id" java "$dir" "$LAST_STATUS" "$LAST_EXIT" "$dir/**/build/test-results/**/*.xml" "$OUT_DIR/$id-stdout.txt" "$GRADLE test --continue"
  ran_any=1
done < <(find_marker_dirs build.gradle build.gradle.kts | dedupe_nested)

# ---------- 4) Go ----------
while IFS= read -r dir; do
  [ -n "$dir" ] && [ -d "$dir" ] || continue
  id="$(mkid go "$dir")"
  echo "[run_tests] [Go] $(rel "$dir")"
  if ! have go; then
    echo "[run_tests]   go 미설치"
    record "$id" go "$dir" runner-missing "" "" "" "go test ./..."
    continue
  fi
  out="$OUT_DIR/$id-gotest.json"
  (cd "$dir" && ( have timeout && timeout --kill-after=30 "$TIMEOUT_SEC" go test ./... -json || go test ./... -json ) > "$out" 2> "$OUT_DIR/$id-stdout.txt")
  LAST_EXIT=$?
  LAST_STATUS=ran; { [ "$LAST_EXIT" -eq 124 ] || [ "$LAST_EXIT" -eq 137 ]; } && LAST_STATUS=timeout
  echo "[run_tests]   -> exit=$LAST_EXIT"
  record "$id" go "$dir" "$LAST_STATUS" "$LAST_EXIT" "$out" "$OUT_DIR/$id-stdout.txt" "go test ./... -json"
  ran_any=1
done < <(find_marker_dirs go.mod | dedupe_nested)

# ---------- 5) Rust ----------
while IFS= read -r dir; do
  [ -n "$dir" ] && [ -d "$dir" ] || continue
  id="$(mkid cargo "$dir")"
  echo "[run_tests] [Rust] $(rel "$dir")"
  if ! have cargo; then
    echo "[run_tests]   cargo 미설치"
    record "$id" rust "$dir" runner-missing "" "" "" "cargo test"
    continue
  fi
  run_cmd "$id" "$dir" cargo test --no-fail-fast -q
  record "$id" rust "$dir" "$LAST_STATUS" "$LAST_EXIT" "$OUT_DIR/$id-stdout.txt" "$OUT_DIR/$id-stdout.txt" "cargo test --no-fail-fast"
  ran_any=1
done < <(find_marker_dirs Cargo.toml | dedupe_nested)

# ---------- 6) .NET ----------
while IFS= read -r dir; do
  [ -n "$dir" ] && [ -d "$dir" ] || continue
  id="$(mkid dotnet "$dir")"
  echo "[run_tests] [.NET] $(rel "$dir")"
  if ! have dotnet; then
    echo "[run_tests]   dotnet 미설치"
    record "$id" dotnet "$dir" runner-missing "" "" "" "dotnet test"
    continue
  fi
  trx_dir="$OUT_DIR/$id-trx"; mkdir -p "$trx_dir"; trx_dir="$(native "$trx_dir")"
  run_cmd "$id" "$dir" dotnet test --nologo --logger "trx" --results-directory "$trx_dir"
  record "$id" dotnet "$dir" "$LAST_STATUS" "$LAST_EXIT" "$trx_dir/*.trx" "$OUT_DIR/$id-stdout.txt" "dotnet test --logger trx"
  ran_any=1
done < <(find_marker_dirs '*.sln' '*.csproj' '*.fsproj' | dedupe_nested)

# ---------- 집계 ----------
echo
summarize() {
  local PYBIN=python; have python || PYBIN=python3
  if have "$PYBIN"; then
    "$PYBIN" "$(native "$ROOT/tools/summarize_results.py")" "$(native "$OUT_DIR")" --target "$(native "$TARGET")" \
      || echo "[run_tests] 집계 실패 — runs.tsv 와 결과 파일을 직접 확인하세요."
  else
    echo "[run_tests] python 이 없어 자동 집계를 건너뜁니다. runs.tsv 와 결과 파일을 직접 확인하세요."
  fi
}

if [ "$ran_any" -eq 0 ]; then
  if [ "$(wc -l < "$OUT_DIR/runs.tsv")" -gt 1 ]; then
    echo "[run_tests] 프로젝트는 찾았지만 실행하지 못했습니다 (runner-missing / deps-missing / no-test-script)."
    summarize   # 미실행 사유 목록(summary.md)은 레포트 작성에 필요하므로 남긴다
  else
    echo "[run_tests] 테스트 대상 프로젝트를 찾지 못했습니다."
  fi
  echo "[run_tests] generate-only 모드로 진행하고, 사유를 레포트에 기록하세요."
  exit 2
fi

summarize
echo "[run_tests] 완료. 결과 디렉토리: ${OUT_DIR#$ROOT/}"
