#!/usr/bin/env python3
# summarize_results.py — run_tests.sh 가 남긴 결과(runs.tsv + 러너별 결과 파일)를 파싱해
#                        통과/실패/에러/스킵 수와 실패 원인을 집계한다.
#
# 사용법:
#   python tools/summarize_results.py [reports/.tests] [--target <대상경로>]
#   --target 를 주면 표의 프로젝트 경로를 대상 기준 상대경로로 표시한다 (JSON 에는 절대경로 유지).
#
# 산출물 (같은 디렉토리):
#   summary.json  기계판독용. 레포트의 수치는 반드시 여기서 가져온다 (직접 세지 않는다).
#   summary.md    사람이 읽는 표 + 실패 목록. stdout 에도 같은 내용을 출력한다.
#
# 지원 형식:
#   junit XML  (pytest, vitest, playwright, maven surefire/failsafe, gradle)
#   jest JSON  (jest --json)
#   go test    (go test -json)
#   cargo test (stdout 텍스트)
#   trx        (dotnet test --logger trx)
#
# 의존성: 표준 라이브러리만 사용.

import csv
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

# Windows 콘솔(cp949)에서 한글이 깨지지 않도록 UTF-8 로 출력한다
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

MAX_MSG_LINES = 12   # 실패 메시지는 앞부분만 보관 (레포트에 요약으로 쓰기 위해)
MAX_MSG_CHARS = 1500


def clip(text: str) -> str:
    text = (text or "").strip()
    lines = text.splitlines()
    if len(lines) > MAX_MSG_LINES:
        text = "\n".join(lines[:MAX_MSG_LINES]) + f"\n... (+{len(lines) - MAX_MSG_LINES}줄)"
    if len(text) > MAX_MSG_CHARS:
        text = text[:MAX_MSG_CHARS] + " ..."
    return text


def new_counts():
    return {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}


def add_case(run, status, name, classname="", message="", duration=None):
    run["counts"]["total"] += 1
    run["counts"][status] += 1
    case = {"name": name, "classname": classname, "status": status}
    if duration is not None:
        case["duration_s"] = duration
    if status in ("failed", "errors"):
        case["message"] = clip(message)
        run["failures"].append(case)
    run["cases"].append(case)


# ---------- 파서 ----------

def parse_junit(path, run):
    tree = ET.parse(path)
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else root.iter("testsuite")
    for suite in suites:
        for tc in suite.findall("testcase"):
            name = tc.get("name", "")
            classname = tc.get("classname", "") or suite.get("name", "")
            try:
                duration = float(tc.get("time", "0") or 0)
            except ValueError:
                duration = None
            child = None
            status = "passed"
            for tag, st in (("error", "errors"), ("failure", "failed"), ("skipped", "skipped")):
                child = tc.find(tag)
                if child is not None:
                    status = st
                    break
            message = ""
            if child is not None and status != "skipped":
                message = (child.get("message") or "") + "\n" + (child.text or "")
                # pytest 는 system-out/err 에도 단서를 남긴다
                for extra_tag in ("system-err",):
                    extra = tc.find(extra_tag)
                    if extra is not None and extra.text and extra.text.strip():
                        message += "\n[stderr]\n" + extra.text
            add_case(run, status, name, classname, message, duration)


def parse_jest_json(path, run):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for file_result in data.get("testResults", []):
        classname = os.path.relpath(file_result.get("name", ""), run["dir"]) if run.get("dir") else file_result.get("name", "")
        # 파일 자체가 로드 실패한 경우 (구문 오류 등)
        if file_result.get("status") == "failed" and not file_result.get("assertionResults"):
            add_case(run, "errors", "(파일 로드 실패)", classname, file_result.get("message", ""))
            continue
        for a in file_result.get("assertionResults", []):
            st = a.get("status")
            status = {"passed": "passed", "failed": "failed", "pending": "skipped", "skipped": "skipped",
                      "todo": "skipped", "disabled": "skipped"}.get(st, "errors")
            dur = a.get("duration")
            add_case(run, status, a.get("fullName") or a.get("title", ""), classname,
                     "\n".join(a.get("failureMessages", [])), (dur / 1000.0) if dur else None)


def parse_go_json(path, run):
    # 한 줄에 JSON 이벤트 하나. Test 필드가 있는 pass/fail/skip 이벤트만 센다.
    outputs = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            test = ev.get("Test")
            pkg = ev.get("Package", "")
            key = (pkg, test)
            action = ev.get("Action")
            if action == "output":
                outputs.setdefault(key, []).append(ev.get("Output", ""))
            elif action in ("pass", "fail", "skip"):
                if test is None:
                    # 패키지 단위 실패(빌드 실패 등)는 테스트가 하나도 없을 때만 에러로 기록
                    if action == "fail" and not any(k[0] == pkg and k[1] for k in outputs):
                        add_case(run, "errors", "(패키지 빌드/실행 실패)", pkg, "".join(outputs.get(key, [])))
                    continue
                status = {"pass": "passed", "fail": "failed", "skip": "skipped"}[action]
                add_case(run, status, test, pkg, "".join(outputs.get(key, [])), ev.get("Elapsed"))


CARGO_LINE = re.compile(r"^test (\S+) \.\.\. (ok|FAILED|ignored)", re.M)
CARGO_FAIL_BLOCK = re.compile(r"^---- (\S+) stdout ----\n(.*?)(?=^---- |\nfailures:|\Z)", re.M | re.S)


def parse_cargo_stdout(path, run):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    details = {m.group(1): m.group(2) for m in CARGO_FAIL_BLOCK.finditer(text)}
    for m in CARGO_LINE.finditer(text):
        name, result = m.group(1), m.group(2)
        status = {"ok": "passed", "FAILED": "failed", "ignored": "skipped"}[result]
        add_case(run, status, name, "", details.get(name, ""))
    if run["counts"]["total"] == 0 and "error" in text.lower():
        add_case(run, "errors", "(컴파일/실행 실패)", "", text)


def _strip_ns(elem):
    # trx 는 기본 네임스페이스를 쓰므로 태그에서 {ns} 를 제거해 단순 조회가 가능하게 한다
    for e in elem.iter():
        if isinstance(e.tag, str) and e.tag.startswith("{"):
            e.tag = e.tag.split("}", 1)[1]
    return elem


def parse_trx(path, run):
    root = _strip_ns(ET.parse(path).getroot())
    for r in root.iter("UnitTestResult"):
        outcome = r.get("outcome", "")
        status = {"Passed": "passed", "Failed": "failed", "NotExecuted": "skipped",
                  "Skipped": "skipped", "Inconclusive": "skipped"}.get(outcome, "errors")
        message = ""
        err = r.find("Output/ErrorInfo")
        if err is not None:
            msg = err.findtext("Message") or ""
            st = err.findtext("StackTrace") or ""
            message = msg + "\n" + st
        try:
            # duration 형식: HH:MM:SS.fffffff
            h, m, sec = r.get("duration", "0:0:0").split(":")
            duration = int(h) * 3600 + int(m) * 60 + float(sec)
        except Exception:
            duration = None
        add_case(run, status, r.get("testName", ""), "", message, duration)


def pick_parser(path, lang):
    p = path.lower()
    if p.endswith(".trx"):
        return parse_trx
    if p.endswith("-jest.json"):
        return parse_jest_json
    if p.endswith("-gotest.json"):
        return parse_go_json
    if p.endswith(".xml"):
        return parse_junit
    if lang == "rust":
        return parse_cargo_stdout
    return None


def expand_result_paths(spec):
    # result_path 는 ';' 로 구분된 glob 목록. '**' 도 허용.
    paths = []
    for pattern in (spec or "").split(";"):
        pattern = pattern.strip()
        if pattern:
            paths.extend(sorted(glob.glob(pattern, recursive=True)))
    return paths


# ---------- 집계 ----------

def summarize(out_dir, target=None):
    runs_tsv = os.path.join(out_dir, "runs.tsv")
    if not os.path.isfile(runs_tsv):
        sys.exit(f"[summarize] runs.tsv 가 없습니다: {runs_tsv} (tools/run_tests.sh 를 먼저 실행)")

    runs = []
    with open(runs_tsv, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            run = {
                "id": row["id"], "lang": row["lang"], "dir": row["dir"], "status": row["status"],
                "exit_code": int(row["exit_code"]) if row.get("exit_code") else None,
                "command": row.get("command", ""), "stdout_path": row.get("stdout_path", ""),
                "result_files": [], "counts": new_counts(), "failures": [], "cases": [], "notes": [],
            }
            if run["status"] in ("ran", "timeout"):
                files = expand_result_paths(row.get("result_path", ""))
                if not files:
                    run["notes"].append("기계판독 결과 파일이 없음 — stdout 을 직접 확인해야 함")
                for path in files:
                    parser = pick_parser(path, run["lang"])
                    if parser is None:
                        run["notes"].append(f"알 수 없는 결과 형식: {path}")
                        continue
                    try:
                        parser(path, run)
                        run["result_files"].append(path)
                    except Exception as exc:  # 손상된 결과 파일도 집계를 멈추지 않는다
                        run["notes"].append(f"파싱 실패 {os.path.basename(path)}: {exc}")
                if run["status"] == "ran" and run["exit_code"] not in (0, None) and run["counts"]["failed"] == 0 \
                        and run["counts"]["errors"] == 0:
                    run["notes"].append(f"실패 테스트는 없지만 러너 exit={run['exit_code']} — 수집/설정 오류 가능, stdout 확인 필요")
                if run["status"] == "timeout":
                    run["notes"].append("제한 시간 초과로 중단됨 — 집계는 중단 시점까지의 부분 결과")
            runs.append(run)

    total = new_counts()
    for run in runs:
        for k in total:
            total[k] += run["counts"][k]
    not_run = [r for r in runs if r["status"] not in ("ran", "timeout")]

    summary = {
        "out_dir": out_dir,
        "projects": len(runs),
        "projects_ran": len(runs) - len(not_run),
        "projects_not_run": [{"id": r["id"], "dir": r["dir"], "status": r["status"]} for r in not_run],
        "totals": total,
        "runs": [{k: v for k, v in r.items() if k != "cases"} for r in runs],
    }
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    # 개별 케이스 목록은 별도 파일로 (레포트 3절 '생성 테스트 목록' 작성에 활용)
    with open(os.path.join(out_dir, "cases.json"), "w", encoding="utf-8") as f:
        json.dump([{"run": r["id"], **c} for r in runs for c in r["cases"]], f, ensure_ascii=False, indent=2)

    summary["target"] = target
    md = render_md(summary, runs, target)
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write(md)
    return summary, md


STATUS_KO = {"ran": "실행", "timeout": "타임아웃", "runner-missing": "러너 미설치",
             "deps-missing": "의존성 미설치", "no-test-script": "test 스크립트 없음"}


def _display(path, target):
    if not target:
        return path
    try:
        r = os.path.relpath(path, target)
        return "." if r == "." else r.replace(os.sep, "/")
    except ValueError:  # 드라이브가 다른 경우 등
        return path


def render_md(summary, runs, target=None):
    t = summary["totals"]
    lines = ["# 테스트 실행 집계", ""]
    lines.append(f"- 프로젝트: {summary['projects']}개 (실행 {summary['projects_ran']}개, 미실행 {len(summary['projects_not_run'])}개)")
    lines.append(f"- 합계: 전체 {t['total']} / 통과 {t['passed']} / 실패 {t['failed']} / 에러 {t['errors']} / 스킵 {t['skipped']}")
    lines += ["", "| 프로젝트 | 언어 | 상태 | exit | 전체 | 통과 | 실패 | 에러 | 스킵 | 비고 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in runs:
        c = r["counts"]
        ec = "" if r["exit_code"] is None else str(r["exit_code"])
        note = "; ".join(r["notes"])
        lines.append(f"| `{_display(r['dir'], target)}` | {r['lang']} | {STATUS_KO.get(r['status'], r['status'])} | {ec} "
                     f"| {c['total']} | {c['passed']} | {c['failed']} | {c['errors']} | {c['skipped']} | {note} |")
    failures = [(r, f) for r in runs for f in r["failures"]]
    if failures:
        lines += ["", "## 실패 / 에러 목록", ""]
        for i, (r, f) in enumerate(failures, 1):
            where = f"{f['classname']}::{f['name']}" if f["classname"] else f["name"]
            lines.append(f"### {i}. [{'에러' if f['status'] == 'errors' else '실패'}] `{where}`")
            lines.append(f"- 프로젝트: `{_display(r['dir'], target)}`")
            if f.get("message"):
                lines += ["", "```text", f["message"], "```"]
            lines.append("")
    if summary["projects_not_run"]:
        lines += ["", "## 실행하지 못한 프로젝트", ""]
        for p in summary["projects_not_run"]:
            lines.append(f"- `{_display(p['dir'], target)}` — {STATUS_KO.get(p['status'], p['status'])}")
    lines += ["", "> 원인 분류(서비스 결함 / 테스트 결함 / 환경 문제)는 자동으로 판단하지 않습니다. "
              "각 실패의 메시지와 stdout 을 보고 SKILL.md 의 triage 절차대로 분류하세요."]
    return "\n".join(lines) + "\n"


def main():
    args = sys.argv[1:]
    target = None
    if "--target" in args:
        i = args.index("--target")
        target = os.path.normpath(args[i + 1]) if i + 1 < len(args) else None
        del args[i:i + 2]
    out_dir = os.path.normpath(args[0] if args else os.path.join("reports", ".tests"))
    summary, md = summarize(out_dir, target)
    print(md)
    print(f"[summarize] 저장: {os.path.join(out_dir, 'summary.json')}, summary.md, cases.json")


if __name__ == "__main__":
    main()
