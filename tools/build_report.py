#!/usr/bin/env python3
# build_report.py — Markdown QA 레포트를 HTML로 변환한다. (HTML이 기본 산출물)
#
# 사용법:
#   python tools/build_report.py reports/2606291651_qa_report.md
#   python tools/build_report.py reports/2606291651_qa_report.md --pdf   # (선택) PDF도 시도
#
# 결과: 같은 디렉토리에 동일 이름의 .html 생성. --pdf 옵션 + weasyprint 설치 시 .pdf도 생성.
#   - 제목은 마크다운의 첫 `# ` 헤딩을 사용한다 (없으면 파일명).
#   - h2/h3 기준 목차를 제목 아래에 자동 삽입한다.
#   - 표/코드 안의 등급 단어(Blocker/Critical/Major/Minor/Risk)와 통과/실패/에러를 색상으로 강조한다.
#
# 의존성:
#   필수: markdown        (설치: pip install markdown)
#   선택: weasyprint      (PDF가 꼭 필요할 때만. 보통은 브라우저 Ctrl+P 사용 권장)
#
# PDF가 필요하면: 생성된 HTML을 브라우저로 열고 Ctrl+P → "PDF로 저장"이 가장 간단하고 안정적이다.

import datetime
import os
import re
import sys

# Windows 콘솔(cp949)에서 한글 메시지가 깨지지 않도록 UTF-8 로 출력한다
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# KST 는 서머타임이 없어 고정 오프셋으로 충분하다 (tzdata 의존성 없이 Windows 에서도 동작)
KST = datetime.timezone(datetime.timedelta(hours=9), name="KST")

# 심각도별 색상 — CLAUDE.md 의 등급 체계와 반드시 일치시킨다
SEVERITY_COLORS = {
    "Blocker": "#7f0000",
    "Critical": "#b00020",
    "Major": "#e65100",
    "Minor": "#f9a825",
    "Risk": "#1565c0",
}
# 실행 결과 단어 색상
RESULT_COLORS = {
    "통과": "#2e7d32",
    "실패": "#b00020",
    "에러": "#7f0000",
    "스킵": "#757575",
}

# HTML 문서 골격 + 스타일. 가독성 있는 레포트 출력을 위해 CSS를 내장한다.
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", "Malgun Gothic", "Noto Sans KR", sans-serif;
         line-height: 1.65; color: #1a1a1a; max-width: 960px; margin: 0 auto; padding: 40px 24px; }}
  h1 {{ border-bottom: 3px solid #1a1a1a; padding-bottom: 8px; }}
  h2 {{ margin-top: 2.2em; border-bottom: 1px solid #ddd; padding-bottom: 6px; }}
  h3 {{ margin-top: 1.6em; }}
  code {{ background: #f4f4f4; padding: 2px 5px; border-radius: 3px; font-size: 0.92em; }}
  pre {{ background: #f7f7f7; border: 1px solid #e0e0e0; border-radius: 6px;
        padding: 14px; overflow-x: auto; }}
  pre code {{ background: none; padding: 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 0.95em; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 10px; text-align: left; vertical-align: top; }}
  th {{ background: #f0f0f0; }}
  tr:nth-child(even) td {{ background: #fafafa; }}
  blockquote {{ border-left: 4px solid #ccc; margin: 1em 0; padding: 4px 16px; color: #555; }}
  .pdf-hint {{ background: #eef4ff; border: 1px solid #c7dbff; border-radius: 6px;
              padding: 10px 14px; margin-bottom: 24px; font-size: 0.9em; color: #1a3a6b; }}
  .toc {{ background: #fafafa; border: 1px solid #e5e5e5; border-radius: 6px; padding: 12px 20px; margin: 1.2em 0 2em; }}
  .toc ul {{ margin: 0.2em 0; padding-left: 1.2em; }}
  .toc a {{ text-decoration: none; color: #1a3a6b; }}
  .footer {{ margin-top: 3em; padding-top: 1em; border-top: 1px solid #ddd;
            color: #888; font-size: 0.85em; }}
  .sev, .res {{ font-weight: 700; }}
  {severity_css}
  /* 인쇄(브라우저 Ctrl+P로 PDF 저장) 시 안내 배너는 숨기고 여백을 정리한다 */
  @media print {{
    body {{ padding: 0; max-width: none; }}
    .pdf-hint {{ display: none; }}
    pre, blockquote, table {{ page-break-inside: avoid; }}
    h2, h3 {{ page-break-after: avoid; }}
  }}
</style>
</head>
<body>
<div class="pdf-hint">PDF로 저장하려면: 이 화면에서 <b>Ctrl + P</b> (Mac은 Cmd + P) → 프린터를 "PDF로 저장" 또는 "Microsoft Print to PDF"로 선택하세요.</div>
{content}
<div class="footer">생성: {generated} (KST) · qa-automation</div>
</body>
</html>
"""


def build_severity_css() -> str:
    # 등급/결과 단어를 색상으로 강조하는 CSS 클래스 생성
    rules = []
    for name, color in SEVERITY_COLORS.items():
        rules.append(f".sev-{name.lower()} {{ color: {color}; }}")
    for name, color in RESULT_COLORS.items():
        rules.append(f".res-{name} {{ color: {color}; }}")
    return "\n  ".join(rules)


# <td>Blocker</td>, <td><code>Blocker</code></td>, <li><strong>등급</strong>: <code>Blocker</code> 같은 형태를 잡는다.
_SEV_WORDS = "|".join(SEVERITY_COLORS)
_RES_WORDS = "|".join(RESULT_COLORS)
_SEV_RE = re.compile(rf"(<(?:td|code)>)\s*({_SEV_WORDS})\s*(</(?:td|code)>)")
_RES_RE = re.compile(rf"(<td>)\s*({_RES_WORDS})\s*(</td>)")


def highlight(html: str) -> str:
    # 마크다운 변환 후, 등급/결과 단어를 색상 span 으로 감싼다 (단어 단독인 셀/코드만 대상 → 문장 속 오탐 방지)
    html = _SEV_RE.sub(lambda m: f'{m.group(1)}<span class="sev sev-{m.group(2).lower()}">{m.group(2)}</span>{m.group(3)}', html)
    html = _RES_RE.sub(lambda m: f'{m.group(1)}<span class="res res-{m.group(2)}">{m.group(2)}</span>{m.group(3)}', html)
    return html


def extract_title(md_text: str, fallback: str) -> str:
    for line in md_text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def md_to_html(md_text: str, title: str) -> str:
    try:
        import markdown  # 지연 임포트로 미설치 시 친절한 에러 제공
    except ImportError:
        sys.exit("[build_report] 'markdown' 패키지가 필요합니다. "
                 "설치: python -m pip install markdown")

    # 표/코드펜스/목차 등 확장 기능 활성화. 목차는 h2~h3 만.
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        extension_configs={"toc": {"toc_depth": "2-3", "title": "목차"}},
    )
    body = md.convert(md_text)
    body = highlight(body)

    # 목차를 첫 h1 바로 뒤에 삽입 (h1 이 없으면 본문 맨 앞)
    toc = getattr(md, "toc", "") or ""
    if toc.strip() and "<li>" in toc:
        idx = body.find("</h1>")
        body = body[: idx + 5] + "\n" + toc + body[idx + 5:] if idx >= 0 else toc + body

    generated = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    return HTML_TEMPLATE.format(
        title=title,
        content=body,
        severity_css=build_severity_css(),
        generated=generated,
    )


def try_make_pdf(html_text: str, pdf_path: str) -> None:
    # --pdf 옵션을 줬을 때만 호출. weasyprint가 없으면 조용히 안내만 한다(에러 아님).
    try:
        from weasyprint import HTML
    except Exception:
        print("[build_report] (참고) PDF는 건너뜁니다. weasyprint가 설치돼 있지 않습니다. "
              "PDF가 필요하면 생성된 HTML에서 Ctrl+P로 저장하세요.")
        return
    try:
        HTML(string=html_text).write_pdf(pdf_path)
        print(f"[build_report] PDF 생성: {pdf_path}")
    except Exception as exc:
        print(f"[build_report] (참고) PDF 생성에 실패했습니다: {exc}. "
              "HTML에서 Ctrl+P로 저장하세요.")


def main():
    args = sys.argv[1:]
    want_pdf = "--pdf" in args
    paths = [a for a in args if not a.startswith("--")]
    if not paths:
        sys.exit("사용법: python tools/build_report.py <레포트.md> [--pdf]")

    md_path = paths[0]
    if not os.path.isfile(md_path):
        sys.exit(f"[build_report] 파일을 찾을 수 없습니다: {md_path}")

    base, _ = os.path.splitext(md_path)
    html_path = base + ".html"

    with open(md_path, encoding="utf-8") as f:
        md_text = f.read()

    title = extract_title(md_text, os.path.basename(base))
    html_text = md_to_html(md_text, title)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_text)
    print(f"[build_report] HTML 생성: {html_path}")

    if want_pdf:
        try_make_pdf(html_text, base + ".pdf")
    else:
        print("[build_report] PDF가 필요하면 HTML을 브라우저로 열고 Ctrl+P로 저장하세요. "
              "(또는 --pdf 옵션 + weasyprint 설치)")


if __name__ == "__main__":
    main()
