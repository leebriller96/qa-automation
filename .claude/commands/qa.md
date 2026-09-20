---
description: input/의 서비스 코드를 검사해 통합 테스트를 생성·실행하고, 결함/위험 레포트를 만듭니다.
argument-hint: "[full|generate-only|run-only] [대상경로]  (예: /qa, /qa generate-only, /qa full input/svc-a)"
---

# /qa — 통합 테스트 자동화 + 결함/위험 레포트

인자: `$ARGUMENTS`

## 인자 해석

공백으로 나눠 해석합니다. 순서는 무관합니다.

- `full` | `generate-only` | `run-only` 중 하나 → **모드**. 없으면 `full`.
- 그 외 토큰 → **대상 경로**. 없으면 `input/`.
- 모드 토큰이 위 셋 중 어느 것도 아니고 경로로도 존재하지 않으면, 사용법을 안내하고 중단합니다.
  (예: `/qa fast` → "알 수 없는 모드 'fast'. full | generate-only | run-only 중 선택")

| 모드 | 하는 일 |
|------|---------|
| `full` (기본) | 생성 + 실행(기존 테스트 포함) + 실패 원인 분류 + 결함/위험 분석 |
| `generate-only` | 생성 + 정적 위험 분석. 실행하지 않음 (실행 환경이 없을 때) |
| `run-only` | 기존 테스트 발견·실행 + 실패 원인 분류 + 결함/위험 분석. 생성하지 않음 |

## 수행

`.claude/skills/test-automation/SKILL.md`를 **먼저 읽고** 그 절차(§1 → §11)를 순서대로 따릅니다.
상세 규칙은 모두 SKILL.md 한 곳에 있으며, 여기서는 반복하지 않습니다.

핵심만 요약하면:

1. **대상 확보** (§1) — 경로/`input/`/붙여넣은 코드(`input/pasted_<ts>/`에 저장). 없으면 안내 후 중단.
2. **인벤토리** (§2) — 서비스, 진입점, 통합 지점, 기존 테스트, 의존성.
3. **환경 준비** (§3, full/run-only) — 불가하면 사유 기록 후 `generate-only` 폴백.
4. **테스트 생성** (§4, full/generate-only) — `references/fixture-patterns.md` 참고.
5. **실행** (§5, full/run-only) — `tools/run_tests.sh <대상경로>` → `reports/.tests/summary.md` 수치 사용.
6. **실패 원인 분류** (§6) — 서비스 결함 / 테스트 결함(수정 후 재실행) / 환경 문제. 서비스 결함은 재실행으로 확인.
7. **결함/위험 분석** (§7) — CLAUDE.md 등급 기준.
8. **레포트** (§8–§9) — `templates/report_template.md` 구조, `reports/<KST타임스탬프>_qa_report.md` + HTML 빌드 확인.
9. **요약 보고** (§10) — 두괄식, 레포트 경로, 생성 테스트 위치와 회수 방법.

## 주의

- 검증을 약화시켜 통과시키지 않습니다. 실패는 원인 분류를 거쳐 정직하게 보고합니다.
- 수치는 `summary.json`에서 가져옵니다. 직접 세지 않습니다.
- 실서버/실데이터에 부수효과를 주는 테스트는 만들지 않습니다. 시크릿은 레포트에 복사하지 않습니다.
- 모든 출력은 한글로 작성합니다.
