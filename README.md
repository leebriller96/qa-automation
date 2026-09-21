# qa-automation

서비스 코드를 투입하면 디렉토리 전체를 검사해 **통합 테스트를 생성·실행**하고,
그 과정에서 드러나는 **결함과 잠재 위험을 레포트**(Markdown/HTML)로 정리하는 Claude Code repo입니다.
(PDF가 필요하면 HTML을 브라우저에서 Ctrl+P로 저장)

## 무엇을 하나요

- `input/`에 서비스 코드를 넣고 `/qa` 한 번이면 끝
- 디렉토리 전체에서 서비스와 통합 지점(DB·외부 API·큐 등)을 자동 식별
- 서비스별 **통합 테스트 생성 + 실제 실행** (행복 경로 + 경계/예외 + 통합 실패 시나리오)
- 실패한 테스트는 결함으로, 미검증 경로·동시성·데이터 위험 등은 잠재 위험으로 정리
- 커버리지 공백과 우선 개선 로드맵, 재현/실행 방법까지 레포트에 포함

## 빠른 시작

### 1. 준비 (Claude Code)

```bash
git clone <이 repo 주소>
cd qa-automation
```

이 디렉토리에서 Claude Code를 실행하면 `CLAUDE.md`, 슬래시 명령, 스킬이 자동 인식됩니다.

### 2. 의존성 설치

레포트(HTML) 생성을 위해 `markdown` 패키지가 필요합니다. (클론 후 1회)

```bash
python -m pip install -r tools/requirements.txt
```

통합 테스트 실행에 필요한 프레임워크(pytest, Jest, JUnit 등)는 **분석 대상 프로젝트 쪽**에 설치합니다.
미설치 등으로 실행이 불가능하면 자동으로 `generate-only` 모드로 폴백하고, 정적 위험 분석으로 보완합니다.

> **Windows**: 테스트 러너 `tools/run_tests.sh`는 bash 스크립트입니다. Git for Windows(Git Bash)가 설치돼 있어야 하며,
> Claude Code가 Bash 도구로 실행합니다. PowerShell 에서 직접 돌리려면 `bash tools/run_tests.sh input` 처럼 호출하세요.

### 환경변수 (선택)

| 변수 | 용도 |
|---|---|
| `GRADLE_ARGS` / `MAVEN_ARGS` | Java 러너 추가 인자. 예: `GRADLE_ARGS="-Pmysql"` (프로파일 조건부 테스트) |
| `QA_PRE_RUN` / `QA_POST_RUN` | 러너 실행 전/후 1회 실행할 셸 명령 (통합 테스트용 DB·서버 기동/정리) |
| `QA_EXCLUDE_DIRS` | 추가 제외 디렉토리(공백 구분). 환경 없이 실행 불가한 스위트를 건너뛸 때 |

Gradle 은 항상 `cleanTest test --no-build-cache` 로 실행해 UP-TO-DATE/FROM-CACHE 로 "실행 안 됨" 이 "통과" 로 기록되지 않게 한다.

### 3. 실행

```text
# input/ 에 분석할 서비스 코드/디렉토리를 넣은 뒤, Claude Code에서:
/qa

# 모드를 지정하려면:
/qa generate-only   # 테스트 생성 + 정적 위험 분석까지만 (실행 환경 없을 때)
/qa run-only        # 기존 테스트 발견·실행·정리 중심
/qa full            # (기본) 생성 + 실행(기존 테스트 포함) + 실패 원인 분류 + 결함/위험 분석

# 대상 경로를 지정하려면 (input/ 에 서비스가 여럿일 때):
/qa input/svc-a
/qa generate-only input/svc-b
```

코드를 채팅에 직접 붙여넣고 `/qa` 해도 됩니다. (`input/pasted_<타임스탬프>/` 에 저장된 뒤 분석됩니다.)

### 4. 결과 확인

```
reports/
  2606291651_qa_report.md
  2606291651_qa_report.html   ← 브라우저로 열고 Ctrl+P로 PDF 저장 가능
```

레포트 파일명은 한국시각(KST) 기준 `yymmddhhmm_` 접두어가 붙습니다.

생성된 통합 테스트는 `input/<서비스>/tests/integration/`(또는 그 프로젝트의 관례 위치)에 저장됩니다.
**`input/`은 git 무시 대상**이므로, 보존하려면 레포트 4절의 파일 목록을 보고 원본 저장소로 복사하세요.

실행 원본 데이터(러너별 결과, `summary.json`)는 `reports/.tests/`에 남습니다.

## 모드

| 모드 | 설명 | 추천 상황 |
|------|------|-----------|
| full | 생성 + 실행(기존 테스트 포함) + 실패 원인 분류 + 결함/위험 분석 (기본) | 테스트 환경 구성 가능 |
| generate-only | 생성 + 정적 위험 분석까지 | 실행 환경/의존성 없음 |
| run-only | 기존 테스트 실행 + 실패 원인 분류 + 결함/위험 분석 | 이미 테스트가 있는 프로젝트 |

### 실패 원인 분류 (triage)

실패한 테스트를 곧바로 결함으로 보고하지 않습니다. 각 실패를 **서비스 결함 / 테스트 결함 / 환경 문제**로 나누고,
테스트 결함은 수정 후 재실행, 서비스 결함은 재실행으로 재현을 확인한 뒤에만 레포트의 "결함" 절에 올립니다.
결과가 실행마다 달라지면 결함이 아닌 플래키(Risk)로 분류합니다.

## 지원 언어 / 프레임워크

| 언어 | 통합 테스트 프레임워크 |
|------|------------------------|
| Python | pytest (+ httpx/requests, pytest-asyncio, testcontainers) |
| JavaScript/TypeScript | Jest/Vitest (+ supertest), Playwright |
| Java/Kotlin | JUnit 5 (+ Spring Boot Test, Testcontainers, RestAssured) — Maven/Gradle |
| Go / Rust / .NET | `go test` / `cargo test` / `dotnet test` (러너 실행·집계 지원) |
| 그 외(범용) | 표준 러너 자동 감지, 불가 시 시나리오 문서화 |

러너(`tools/run_tests.sh`)는 대상 아래의 프로젝트를 **재귀 탐색**(`node_modules`, `.venv`, `build` 등 제외)해
프로젝트마다 적절한 명령을 실행하고, `tools/summarize_results.py`가 junit XML / jest JSON / go test JSON / trx 등을
파싱해 통과·실패·에러·스킵 수와 실패 메시지를 `reports/.tests/summary.{json,md}`로 집계합니다.

## 디렉토리 구조

```
qa-automation/
├── .claude/
│   ├── commands/qa.md                  # /qa 슬래시 명령 (얇은 디스패처)
│   └── skills/test-automation/
│       ├── SKILL.md                    # 테스트 자동화 + 실패 triage + 결함/위험 분석 방법론
│       └── references/fixture-patterns.md  # 언어별 통합 테스트 픽스처 스니펫
├── tools/
│   ├── run_tests.sh                    # 프로젝트 재귀 탐색 + 언어별 러너 실행 (타임아웃, 결과 수집)
│   ├── summarize_results.py            # 러너 결과 파싱 → summary.json / summary.md
│   ├── build_report.py                 # MD → HTML 변환 (목차, 등급 강조; PDF는 선택)
│   └── requirements.txt
├── templates/report_template.md        # QA 레포트 템플릿
├── input/                              # 분석 대상 서비스 + 생성 테스트 (git 무시)
├── reports/                            # 생성 레포트 (git 무시)
└── CLAUDE.md                           # 프로젝트 규칙/컨텍스트
```

## 주의사항

- 테스트를 통과시키려고 검증을 약화시키지 않습니다. 실패는 원인 분류를 거쳐 정직하게 보고합니다.
- 실서버/실데이터에 부수효과를 주는 테스트는 만들지 않습니다. 격리된 테스트 환경을 전제로 합니다.
- **`input/`의 코드는 실제로 실행됩니다** (`npm test`의 postinstall, conftest 등 포함). 신뢰할 수 있는 코드만 투입하세요.
  출처가 불분명하면 `generate-only`로 돌리세요.
- `input/`의 `.env`·키·토큰은 레포트에 복사하지 않고 마스킹합니다. 노출된 자격증명은 Risk로 보고됩니다.
- 자동 생성·실행은 보조 수단입니다. 중요한 시스템은 사람 검토와 병행하세요.

## 라이선스

MIT (필요 시 변경)
