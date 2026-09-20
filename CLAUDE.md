# CLAUDE.md — qa-automation

이 repo는 **QA(테스트) 자동화 도구**입니다. 사용자가 서비스 코드를 투입하면 Claude Code가
디렉토리 전체를 검사해 **통합 테스트를 생성·실행**하고, 그 과정에서 드러나는 **잠재 결함과 위험**을
레포트로 정리합니다.

## 핵심 원칙

- **통합 테스트 중심**: 단위 동작이 아니라 서비스/컴포넌트가 함께 동작할 때(예: API ↔ 비즈니스 로직 ↔ DB,
  서비스 간 호출, 외부 의존성 연동)의 동작을 검증합니다.
- **생성 + 실행**: 테스트를 만들기만 하지 않고 실제로 실행해 통과/실패를 확인합니다.
- **정직한 결과**: 통합 테스트는 외부 의존성(DB, 네트워크 등)이 필요해 실행이 불가능할 수 있습니다.
  이 경우 억지로 통과시키지 말고, 무엇이 없어서 실행하지 못했는지 명확히 레포트에 남깁니다.
- **근거 기반**: 모든 결함/위험은 `파일:라인` 또는 실패한 테스트를 근거로 제시합니다.
- **실패 ≠ 결함**: 실패 테스트는 서비스 결함 / 테스트 결함 / 환경 문제로 분류(triage)하고, 재실행으로 확인된 서비스 결함만 결함으로 보고합니다.
- **수치는 도구에서**: 통과/실패 수는 `tools/summarize_results.py`가 만든 `reports/.tests/summary.json`을 사용합니다. 직접 세지 않습니다.
- **안전**: `input/` 코드는 실제로 실행되므로 신뢰 가능한 코드만 대상으로 하고, 시크릿은 레포트에 복사하지 않습니다.
- 모든 레포트와 사용자 대상 출력은 **한글**로 작성합니다. (코드 주석도 한글)

## 동작 흐름 (/qa)

1. 사용자가 `input/`에 서비스 코드/디렉토리를 넣거나 코드를 붙여넣습니다.
2. 사용자가 `/qa [mode] [path]` 슬래시 명령을 실행합니다.
3. Claude Code가 `.claude/skills/test-automation/SKILL.md` 방법론(상세 절차의 단일 출처)에 따라
   서비스 인벤토리 → 테스트 환경 준비 → 통합 테스트 생성 → 실행(`tools/run_tests.sh`) → 실패 원인 분류 → 결함/위험 분석을 수행합니다.
4. 결과를 `reports/`에 레포트(MD + HTML)로 생성합니다. PDF가 필요하면 HTML을 브라우저에서 Ctrl+P로 저장합니다.

생성한 테스트 코드는 대상 서비스의 관례 위치(없으면 `input/<서비스>/tests/integration/`)에 저장합니다.
`input/`은 git 무시 대상이므로 사용자가 원본 저장소로 복사해야 한다는 점을 요약 보고에 포함합니다.

## 모드

- **full (기본값)**: 통합 테스트 생성 + 실행(기존 테스트 포함) + 실패 triage + 결함/위험 분석.
- **generate-only**: 실행 환경이 없을 때. 테스트 생성 + 정적 위험 분석까지만.
- **run-only**: 이미 존재하는 테스트를 발견·실행하고 triage + 결함/위험을 정리.

`/qa generate-only`, `/qa full input/svc-a` 처럼 모드와 대상 경로를 인자로 지정합니다.

## 지원 언어 / 프레임워크

| 언어 | 통합 테스트 프레임워크(권장) |
|------|------------------------------|
| Python | pytest (+ httpx/requests, pytest-asyncio, testcontainers) |
| JavaScript/TypeScript | Jest/Vitest (+ supertest), Playwright(API/E2E) |
| Java/Kotlin | JUnit 5 (+ Spring Boot Test, Testcontainers, RestAssured/MockMvc) |
| Go / Rust / .NET | 표준 러너(`go test`/`cargo test`/`dotnet test`) 실행·집계 지원 |
| 그 외(범용) | 언어 표준 러너 자동 감지, 불가 시 테스트 시나리오 문서화 |

## 레포트 파일명 규칙 (반드시 준수)

생성되는 모든 레포트 파일명은 **한국시각(KST) 기준** 타임스탬프를 접두어로 붙입니다.

```
형식: yymmddhhmm_<설명>.<확장자>
예시: 2606291651_qa_report.md
```

타임스탬프 생성: `TZ=Asia/Seoul date '+%y%m%d%H%M'`
(윈도우 PowerShell이면 `Get-Date -Format 'yyMMddHHmm'`)

## 결함/위험 분류 기준

| 등급 | 의미 | 예시 |
|------|------|------|
| Blocker | 핵심 기능이 동작하지 않음 | 통합 경로에서 예외/크래시, 데이터 손상 |
| Critical | 심각하나 우회 가능 | 특정 조건에서 잘못된 결과, 트랜잭션 미롤백 |
| Major | 기능 결함이나 영향 제한적 | 경계값 처리 오류, 부분 실패 미처리 |
| Minor | 사소한 결함/품질 이슈 | 부정확한 에러 메시지, 미흡한 검증 |
| Risk | 결함은 아니나 잠재 위험 | 미검증 통합 경로, 동시성/플래키 가능성 |

## 디렉토리

- `input/` — 분석 대상 서비스 코드 + 생성된 테스트 (git 무시)
- `reports/` — 생성된 레포트 (git 무시)
- `tools/` — 테스트 러너(`run_tests.sh`), 결과 집계(`summarize_results.py`), 레포트 빌더(`build_report.py`)
- `templates/` — 레포트 템플릿
- `reports/.tests/` — 러너 원본 결과와 `summary.json` (레포트 수치의 출처)
