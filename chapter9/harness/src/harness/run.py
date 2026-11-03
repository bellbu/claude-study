
# harness/src/harness/run.py
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
PROMPTS = HARNESS_DIR / "prompts"  # ① 프롬프트는 harness 패키지 안에 고정


def parse_args() -> Path:
    """작업 디렉터리를 인자나 환경 변수에서 받아온다."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "project_dir",
        nargs="?",
        default=os.environ.get("PROJECT_DIR"),
        help="작업 디렉터리 (예: ../projects/rss-wiki)",
    )
    args = parser.parse_args()
    if not args.project_dir:
        print("작업 디렉터리를 지정해주세요.")
        print("사용법: uv run python -m harness.run <프로젝트 디렉터리>")
        sys.exit(1)
    return Path(args.project_dir).resolve()


ROOT = parse_args()  # ② 작업 디렉터리는 외부에서 결정
DOCS = ROOT / "docs"
STATE = DOCS / ".cycle_count"  # ③ 사이클 카운터 저장 위치
DECISIONS = DOCS / "decisions"  # 결정 합의 기록 위치

MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", "50"))
PLANNER_MODEL = os.environ.get("PLANNER_MODEL", "opus")
EVALUATOR_MODEL = os.environ.get("EVALUATOR_MODEL", "opus")
MAX_DECISION_TRIES = 3  # 결정 합의 재시도 상한


def log(message: str) -> None:
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"[{timestamp}] {message}", flush=True)


def load_cycle_count() -> int:
    """이전 실행에서 저장된 사이클 번호를 읽어온다."""
    if not STATE.exists():
        return 0
    try:
        return int(STATE.read_text(encoding="utf-8").strip())
    except ValueError:
        return 0


def save_cycle_count(count: int) -> None:
    STATE.write_text(str(count), encoding="utf-8")


def bootstrap_prd() -> None:
    """PRD.md가 없으면 사용자와 대화하여 작성한다."""
    if (DOCS / "PRD.md").exists():
        return

    log("PRD.md가 없습니다. Planner를 대화형으로 실행합니다.")
    log("사용자와 대화하여 PRD.md를 작성한 뒤 종료하세요. (claude 종료: /exit)")

    prompt_text = (PROMPTS / "planner_bootstrap.md").read_text(encoding="utf-8")

    cmd = [
        "claude",
        "--allowedTools", "Read", "Glob", "Grep",
        "Edit(docs/**)",
        "--append-system-prompt", prompt_text,
    ]

    subprocess.run(cmd, cwd=ROOT)

    if not (DOCS / "PRD.md").exists():
        log("PRD.md가 작성되지 않았습니다. 종료합니다.")
        sys.exit(1)


def clear_done_at_cycle_start() -> None:
    """매 사이클 시작마다 DONE을 제거해 Planner가 PRD와 코드의 간극을 재평가하게 한다."""
    done = DOCS / "DONE"
    if done.exists():
        done.unlink()
        log("이전 사이클의 docs/DONE을 제거했습니다. Planner가 PRD와 코드의 간극을 재평가합니다.")


def run_agent(
    name: str,
    prompt_file: str,
    allowed_tools: list[str],
    accept_edits: bool = False,
    model: str | None = None
) -> int:
    """Claude Code 에이전트를 실행하고 종료 코드를 반환한다."""
    prompt_path = PROMPTS / prompt_file
    prompt_text = prompt_path.read_text(encoding="utf-8")

    cmd = [
        "claude",
        "-p",
        prompt_text,
        "--allowedTools",
        *allowed_tools
    ]

    if accept_edits:
        cmd += ["--permission-mode", "acceptEdits"]

    if model:
        cmd += ["--model", model]

    log(f"--- {name} 시작 (model={model or 'default'}) ---")

    result = subprocess.run(cmd, cwd=ROOT)

    log(f"--- {name} 종료 (exit={result.returncode}) ---")

    return result.returncode


def read_choice(path: Path) -> str | None:
    """선택 파일의 첫 줄에서 '선택: {라벨}'을 읽어온다."""
    if not path.exists():
        return None

    lines = path.read_text(encoding="utf-8").strip().splitlines()

    if not lines or not lines[0].startswith("선택:"):
        return None

    return lines[0].split(":", 1)[1].strip()


def resolve_decisions() -> None:
    """블라인드로 기록된 두 선택을 비교해 합의, 재시도, HALT를 판정한다."""
    if not DECISIONS.exists():
        return

    for topic in sorted(DECISIONS.glob("*.md")):

        if topic.name.endswith((".planner.md", ".evaluator.md")):
            continue

        stem = topic.name[:-3]

        p_file = DECISIONS / f"{stem}.planner.md"
        e_file = DECISIONS / f"{stem}.evaluator.md"

        p_choice = read_choice(p_file)
        e_choice = read_choice(e_file)

        if p_choice is None or e_choice is None:
            continue

        text = topic.read_text(encoding="utf-8")
        tries = text.count("합의 불발") + 1

        if p_choice == e_choice:
            topic.write_text(
                text + f"\n합의: {p_choice} (시도 {tries}회)\n",
                encoding="utf-8"
            )
            log(f"결정 합의: {stem} → {p_choice}")

        elif tries >= MAX_DECISION_TRIES:
            halt = (
                f"결정 합의 {MAX_DECISION_TRIES}회 불발: {stem}\n\n"
                f"[planner]\n{p_file.read_text(encoding='utf-8')}\n\n"
                f"[evaluator]\n{e_file.read_text(encoding='utf-8')}\n"
            )

            (DOCS / "HALT").write_text(halt, encoding="utf-8")
            log(f"결정 합의 불발로 HALT: {stem}")

        else:
            topic.write_text(
                text + "\n합의 불발. 후보를 처음부터 다시 나열하고 "
                "장단점을 비교한 뒤 결정하라.\n",
                encoding="utf-8"
            )
            log(f"결정 합의 불발({tries}회): {stem} — 재시도")

        p_file.unlink()
        e_file.unlink()


def main() -> int:
    DOCS.mkdir(exist_ok=True)

    log(f"작업 디렉터리: {ROOT}")

    bootstrap_prd()

    start = load_cycle_count()

    if start > 0:
        log(f"이전 실행에서 {start} 사이클까지 진행되었습니다. 이어서 시작합니다.")

    for i in range(MAX_ITERATIONS):

        iteration = start + i + 1

        log(f"=== 사이클 {iteration} 시작 ===")

        clear_done_at_cycle_start()

        # 1. Planner — Opus
        planner_exit = run_agent(
            "planner",
            "planner.md",
            allowed_tools=[
                "Read", "Glob", "Grep",
                "Edit(docs/**)"
            ],
            model=PLANNER_MODEL
        )

        if planner_exit != 0:
            log("Planner 실행 실패. 사이클을 중단합니다.")
            save_cycle_count(iteration - 1)
            return 1

        if (DOCS / "DONE").exists():
            log("PLAN의 모든 항목이 완료되었습니다. 종료.")
            save_cycle_count(iteration)
            return 0

        if (DOCS / "HALT").exists():
            log("사람의 개입이 필요합니다. docs/HALT를 확인하세요.")
            save_cycle_count(iteration)
            return 1

        # 2. Generator — Sonnet
        generator_exit = run_agent(
            "generator",
            "generator.md",
            allowed_tools=[
                "Read", "Write", "Edit",
                "Bash", "Glob", "Grep"
            ],
            accept_edits=True,
            model="sonnet"
        )

        if generator_exit != 0:
            log("Generator 실행 실패. 사이클을 중단합니다.")
            save_cycle_count(iteration - 1)
            return 1

        # 3. Evaluator — Opus
        evaluator_exit = run_agent(
            "evaluator",
            "evaluator.md",
            allowed_tools=[
                "Read", "Glob", "Grep", "Bash",
                "Edit(docs/**)"
            ],
            model=EVALUATOR_MODEL
        )

        if evaluator_exit != 0:
            log("Evaluator 실행 실패. 사이클을 중단합니다.")
            save_cycle_count(iteration - 1)
            return 1

        # 4. 결정 합의
        resolve_decisions()

        if (DOCS / "HALT").exists():
            log("사람의 개입이 필요합니다. docs/HALT를 확인하세요.")
            save_cycle_count(iteration)
            return 1

        # 5. 사이클 완료 및 카운터 저장
        save_cycle_count(iteration)

        log(f"=== 사이클 {iteration} 종료 ===")

        time.sleep(3)

    log("최대 반복 횟수에 도달했습니다. 종료.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
