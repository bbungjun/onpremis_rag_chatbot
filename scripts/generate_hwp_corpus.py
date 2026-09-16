"""대용량 검색 실험용 합성 사내 규정 HWP 5.0 문서를 생성한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.chunking import chunk_text
from app.document_reader import read_document


@dataclass(frozen=True)
class Theme:
    title: str
    action: str
    evidence: str
    approver: str


THEMES = (
    Theme("연차", "연차 사용 신청", "휴가 신청서", "팀장"),
    Theme("재택근무", "재택근무 신청", "근무 계획서", "팀장"),
    Theme("출장비", "출장비 정산", "교통·숙박 영수증", "재무 담당자"),
    Theme("경비 처리", "업무 경비 신청", "법인카드 전표", "재무 담당자"),
    Theme("온보딩", "입사 절차 등록", "입사 확인서", "인사 담당자"),
    Theme("개인정보", "개인정보 문서 열람", "열람 목적 확인서", "개인정보 보호 담당자"),
    Theme("계정 보안", "업무 계정 권한 요청", "권한 요청서", "보안 담당자"),
    Theme("교육비", "교육비 지원 신청", "교육 과정 안내서", "인사 담당자"),
    Theme("비품 구매", "업무 비품 구매 요청", "견적서", "구매 담당자"),
    Theme("보안 사고", "보안 사고 신고", "사고 경위서", "보안 담당자"),
)

UNITS = (
    "서울본부", "부산본부", "대전본부", "광주본부", "대구본부",
    "인천본부", "수원센터", "성남센터", "울산센터", "창원센터",
    "연구개발본부", "제품본부", "고객지원본부", "운영본부", "물류본부",
    "해외사업본부", "영업본부", "품질관리본부", "플랫폼본부", "서비스본부",
)
ROLES = ("정규직", "계약직", "파견직", "인턴", "관리자")


@dataclass(frozen=True)
class GeneratedPolicy:
    filename: str
    markdown: str
    question: str
    answer: str
    policy_id: str
    theme: str
    unit: str
    role: str


def make_policy(index: int) -> GeneratedPolicy:
    if index < 0:
        raise ValueError("index must be non-negative")
    theme = THEMES[index % len(THEMES)]
    unit = UNITS[(index // len(THEMES)) % len(UNITS)]
    role = ROLES[(index // (len(THEMES) * len(UNITS))) % len(ROLES)]
    series = index // (len(THEMES) * len(UNITS) * len(ROLES))
    scope = f"{unit} {role}" if series == 0 else f"{unit} {role} 운영군 {series + 1}"
    policy_id = f"SYN-POL-{index + 1:05d}"
    days = 1 + (index * 7 + 2) % 9
    retention = 1 + (index * 3 + 1) % 5
    paragraphs = [
        f"# 제1편 {theme.title} 운영",
        f"## 제1장 {scope} 기준",
        "### 제1절 공통 절차",
        "**제1조 (목적)**",
        "① 이 문서는 가상회사 대규모 검색 실험을 위한 합성 테스트 문서이며 실제 사내 규정이 아니다.",
        f"② 문서 식별자는 {policy_id}이고 적용 주제는 {theme.title}이다.",
        f"③ {scope}에 관한 {theme.action} 절차를 정한다.",
        "**제2조 (적용 범위)**",
        f"① 이 규정은 {scope}에게 적용한다.",
        f"② 다른 조직이나 고용 형태에는 해당 조직의 별도 {theme.title} 규정을 적용한다.",
        f"③ 동일 주제의 문의에는 문서 식별자 {policy_id}를 함께 기재한다.",
        "**제3조 (처리 기한)**",
        f"① {scope}은 {theme.action}을 기준일 {days}영업일 전까지 등록한다.",
        f"② 접수 담당자는 등록 후 {1 + index % 3}영업일 이내에 접수 여부를 확인한다.",
        "③ 기한을 넘긴 요청은 제6조의 예외 절차로 처리한다.",
        "**제4조 (승인 절차)**",
        f"① 신청자는 {theme.action}을 내부 신청 시스템에 등록한다.",
        f"② {theme.approver}가 신청 내용과 적용 범위를 확인한다.",
        "③ 승인 결과는 신청 시스템의 기록으로 통지한다.",
        "**제5조 (필수 증빙)**",
        f"① 신청자는 {theme.evidence}를 첨부한다.",
        "② 증빙에 개인정보가 포함되면 접근 권한을 제한한다.",
        "③ 증빙이 누락된 신청은 보완 요청 상태로 돌린다.",
        "**제6조 (예외 처리)**",
        "① 긴급한 사유가 있으면 사유와 발생 시각을 기록한다.",
        f"② {theme.approver}가 예외 승인 여부를 결정한다.",
        "③ 예외 승인도 일반 승인과 동일하게 출처와 처리 이력을 남긴다.",
        "**제7조 (보관 및 폐기)**",
        f"① 승인 기록은 종료일부터 {retention}년간 보관한다.",
        "② 보관 기간이 끝나면 지정된 절차에 따라 폐기한다.",
        "③ 폐기 기록에는 문서 식별자와 처리 일자를 남긴다.",
        "**제8조 (문의 및 개정)**",
        f"① {scope}의 {theme.title} 문의는 담당 부서에 접수한다.",
        "② 규정 개정 시 이전 판의 효력 종료일을 명시한다.",
        "③ 답변자는 적용 범위와 조 번호를 함께 제시한다.",
    ]
    markdown = "\n\n".join(paragraphs) + "\n"
    question = f"가상회사 {scope}의 {theme.action}은 기준일 며칠 전까지 등록해야 하나요?"
    answer = f"기준일 {days}영업일 전까지 등록한다. ({policy_id} 제3조 제1항)"
    return GeneratedPolicy(
        filename=f"synthetic-policy-{index + 1:05d}.hwp",
        markdown=markdown,
        question=question,
        answer=answer,
        policy_id=policy_id,
        theme=theme.title,
        unit=unit,
        role=role,
    )


def generate_corpus(count: int, output: Path, *, hwp_cli: str) -> dict:
    if count <= 0:
        raise ValueError("count must be greater than zero")
    docs_dir = output / "docs"
    source_dir = output / "source_md"
    docs_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    qa = []
    total_children = 0
    for index in range(count):
        policy = make_policy(index)
        md_path = source_dir / f"{Path(policy.filename).stem}.md"
        hwp_path = docs_dir / policy.filename
        md_path.write_text(policy.markdown, encoding="utf-8")
        try:
            subprocess.run(
                [hwp_cli, "new", "-o", str(hwp_path), "--from", str(md_path), "--strict"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
                timeout=120,
                shell=False,
            )
            subprocess.run(
                [hwp_cli, "validate", str(hwp_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
                timeout=120,
                shell=False,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"HWP 생성/검증 실패: {policy.filename}") from exc
        extracted = read_document(hwp_path, hwp_cli=hwp_cli)
        if policy.policy_id not in extracted or policy.answer.split(". (")[0] not in extracted:
            raise ValueError(f"HWP 왕복 검사 실패: {policy.filename}")
        chunks = chunk_text(extracted)
        parents = sum(chunk["type"] == "parent" for chunk in chunks)
        children = sum(chunk["type"] == "child" for chunk in chunks)
        if (parents, children) != (8, 24):
            raise ValueError(f"HWP 구조 손실: {policy.filename}: parent={parents}, child={children}")
        total_children += children
        manifest.append({
            "policy_id": policy.policy_id,
            "path": hwp_path.relative_to(output).as_posix(),
            "bytes": hwp_path.stat().st_size,
            "sha256": hashlib.sha256(hwp_path.read_bytes()).hexdigest(),
            "parent_chunks": parents,
            "child_chunks": children,
            "theme": policy.theme,
            "unit": policy.unit,
            "role": policy.role,
        })
        try:
            source_path = hwp_path.resolve().relative_to(Path.cwd().resolve()).as_posix()
        except ValueError:
            source_path = hwp_path.resolve().as_posix()
        qa.append({
            "question": policy.question,
            "expected_answer": policy.answer,
            "source_path": source_path,
            "kind": "generated-development-only",
        })

    (output / "manifest.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in manifest) + "\n",
        encoding="utf-8",
    )
    (output / "qa_generated_dev.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in qa) + "\n",
        encoding="utf-8",
    )
    return {
        "documents": count,
        "hwp_bytes": sum(item["bytes"] for item in manifest),
        "parent_chunks": 8 * count,
        "child_chunks": total_children,
        "output": str(output),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--output", type=Path, default=Path("reports/hwp-large-corpus"))
    parser.add_argument("--hwp-cli", default=os.environ.get("HWP_CLI_PATH", "hwp"))
    args = parser.parse_args(argv)
    print(json.dumps(generate_corpus(args.count, args.output, hwp_cli=args.hwp_cli), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
