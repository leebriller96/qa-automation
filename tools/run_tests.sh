#!/usr/bin/env bash
# run_tests.sh — 대상 경로의 언어를 감지해 적절한 테스트 러너를 실행하고 결과를 모은다.
# 사용법: tools/run_tests.sh <대상경로>
# 출력: reports/.tests/ 아래에 러너별 결과 파일 생성, 요약을 stdout에 출력.
set -uo pipefail

TARGET="${1:-input}"
OUT_DIR="reports/.tests"
mkdir -p "$OUT_DIR"

echo "[run_tests] 대상: $TARGET"
have() { command -v "$1" >/dev/null 2>&1; }
ran_any=0

# 1) Python (pytest)
if find "$TARGET" -name '*.py' -print -quit 2>/dev/null | grep -q . ; then
  if have pytest; then
    echo "[run_tests] pytest 실행 중..."
    # junit XML로 결과 저장 (실패해도 계속 진행)
    pytest "$TARGET" -q --junitxml="$OUT_DIR/pytest-junit.xml" \
      > "$OUT_DIR/pytest-stdout.txt" 2>&1 || true
    ran_any=1
    echo "  -> $OUT_DIR/pytest-junit.xml"
  else
    echo "[run_tests] pytest 미설치 (설치: pip install pytest)"
  fi
fi

# 2) JavaScript / TypeScript (npm test / jest / playwright)
if [ -f "$TARGET/package.json" ]; then
  if have npm; then
    echo "[run_tests] npm test 실행 중..."
    (cd "$TARGET" && npm test --silent) > "$OUT_DIR/npm-test-stdout.txt" 2>&1 || true
    ran_any=1
    echo "  -> $OUT_DIR/npm-test-stdout.txt"
  else
    echo "[run_tests] npm 미설치 (Node.js 설치 필요)"
  fi
fi

# 3) Java / Kotlin (maven / gradle)
if [ -f "$TARGET/pom.xml" ] && have mvn; then
  echo "[run_tests] mvn test 실행 중..."
  (cd "$TARGET" && mvn -q test) > "$OUT_DIR/mvn-test-stdout.txt" 2>&1 || true
  ran_any=1
  echo "  -> $OUT_DIR/mvn-test-stdout.txt (리포트: target/surefire-reports/)"
elif { [ -f "$TARGET/build.gradle" ] || [ -f "$TARGET/build.gradle.kts" ]; }; then
  if [ -x "$TARGET/gradlew" ]; then
    echo "[run_tests] ./gradlew test 실행 중..."
    (cd "$TARGET" && ./gradlew test) > "$OUT_DIR/gradle-test-stdout.txt" 2>&1 || true
    ran_any=1
    echo "  -> $OUT_DIR/gradle-test-stdout.txt (리포트: build/reports/tests/)"
  elif have gradle; then
    echo "[run_tests] gradle test 실행 중..."
    (cd "$TARGET" && gradle test) > "$OUT_DIR/gradle-test-stdout.txt" 2>&1 || true
    ran_any=1
    echo "  -> $OUT_DIR/gradle-test-stdout.txt"
  else
    echo "[run_tests] gradle 미설치 (gradlew 래퍼도 없음)"
  fi
fi

if [ "$ran_any" -eq 0 ]; then
  echo "[run_tests] 실행 가능한 테스트 러너가 없습니다. generate-only 모드로 진행하세요."
  exit 2
fi

echo "[run_tests] 완료. 결과 디렉토리: $OUT_DIR"
echo "[run_tests] 주의: 결과 파일을 직접 파싱해 통과/실패/에러 수와 실패 원인을 레포트에 정리하세요."
