---
name: review-pr
description: GitHub Pull Request의 diff와 메타데이터를 분석하고 체크리스트 기반으로 코드 품질, 보안, 성능, 테스트 관점의 리뷰를 작성합니다. "PR 리뷰해줘", "#123 PR 검토" 요청에 사용합니다.
argument-hint: "[PR번호] [owner/repo]"
---
# PR Review Skill
## Goal
PR의 변경 사항을 체계적으로 분석하여 구체적이고 실행 가능한 리뷰 코멘트를 작성합니다.
## Arguments
- 전달된 인자: `$ARGUMENTS`
- 첫 번째 인자는 PR 번호, 두 번째 인자(선택)는 `owner/repo` 형식의 저장소입니다.
  - 예: `/review-pr 123`, `/review-pr 2 bellbu/task-keeper`
- 저장소를 지정하면 이후 모든 `gh` 명령에 `-R owner/repo`를 붙입니다.
- 인자가 없으면 현재 브랜치의 PR을 기준으로 확인합니다.
## Instructions
1. PR 번호가 있으면 `gh pr view <번호> [-R owner/repo] --json title,body,files,commits,author`와 `gh pr diff <번호> [-R owner/repo]`를 실행합니다.
2. PR 번호가 없으면 `gh pr view --json title,body,files,commits,author`와 `gh pr diff`를 실행합니다.
3. PR을 찾지 못하면 바로 중단하지 말고:
   - 현재 폴더와 하위 폴더에 있는 git 저장소의 원격(`git -C <폴더> remote -v`)을 확인해 후보 저장소를 찾습니다.
   - 후보가 하나면 `-R`로 다시 조회하고, 여러 개거나 없으면 사용자에게 저장소를 묻습니다.
4. 필요하면 `gh api`로 변경 파일 주변 코드(호출부, 모델, 테스트, README)를 함께 읽습니다.
5. `resources/review_checklist.md`를 읽고 리뷰 기준으로 사용합니다.
6. 문제는 `필수`, `권장`, `제안`, `질문` 중 하나로 분류합니다.
7. 각 문제에는 파일, 위치, 이유, 개선 방향을 함께 적습니다.
8. 전체 평가를 요약하고 `comment`, `approve`, `request-changes` 중 하나를 권장합니다.
9. 사용자가 승인한 경우에만 `gh pr review <번호> [-R owner/repo]` 명령으로 제출합니다.
10. 제출이 실패하면(예: 본인 PR은 `approve`/`request-changes` 불가) 에러 메시지를 그대로 보여 주고, `comment`로 다시 제출할지 사용자에게 묻습니다. 사용자가 승인한 경우에만 다시 제출합니다.
## Constraints
- 리뷰는 한국어로 작성합니다.
- 모호한 지적만 남기지 말고 대안을 함께 제시합니다.
- 실제 리뷰 제출 전 사용자의 명시적 승인을 받습니다.
