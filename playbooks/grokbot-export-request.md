# 헤스티아에게 전달할 운영 내보내기 지시문

아래 내용을 기존 헤스티아 대화에 전달한다. 이 요청은 현황 수집이며 실행 설정 변경이 아니다.

> GitHub OLYMPUS v1.3과 현재 Grokbot 운영을 대조하려고 한다.
> 기존 Bot·루틴·이름·권한·스케줄을 변경하지 말고, 현재 상태를 읽어서 아래 형식으로 내보내라.
> 모든 신·인간의 실제 Bot ID, 부모 신, 단일 직무, 대응 슬롯, Skill 이름·버전·해시,
> 도구 이름, 루틴 ID·소유자·목적·입력 범위·스케줄·시간대·활성 상태를 수집하라.
> 다섯 라인의 최근 실제 업무는 각각 최대 20건, 시작·종료·상태·산출물·검수·비용 근거와 함께 수집하라.
> 표시되지 않는 값은 null과 누락 사유로 남겨라. 비용을 추정해 채우거나 가상 작업을 만들지 마라.
> 기존 /workspace/olympus/REGISTRY-2026-09-03.md와 Notion 스냅샷은 비교 자료로만 사용하고 현재 상태로 단정하지 마라.
> 비밀값·쿠키·액세스 토큰·환경변수 값은 제외하라. 원본 자료는 비공개 /workspace/olympus-private/에 보존하라.
> Notion '그룩봇' 아래 새 운영 내보내기 문서에 JSON 한 블록과 원본 파일 참조를 남겨라.
> 원본 페이지는 덮어쓰지 말고 결과 문서 링크를 제우스에게 반환하라. 수집 실패·읽을 수 없는 범위도 보고하라.

최상위 JSON 형식:

```json
{
  "schema_version": "1.0",
  "collected_at": null,
  "source_ref": null,
  "policy_ref": null,
  "bots": [],
  "routines": [],
  "runs": [],
  "storage_refs": [],
  "unavailable_fields": []
}
```

null은 작성 전 빈칸이다. 실제 collected_at(시간대 포함)·source_ref 없이 가져오기는 거부된다.
bots 항목: bot_id, display_name, kind(GOD/HUMAN/CHANNEL), owner_god, slot_id,
single_job, skill_ref(id/version/sha256), tools, status.
routines 항목: routine_id, owner_bot_id, purpose, input_scope, schedule, timezone, enabled.
runs 항목: run_id, product_line, started_at, ended_at, status, task_refs, artifact_refs,
review_refs, cost_units, budget_unit, cost_evidence_ref, failure_reason.
source_ref는 비공개 원본 시스템/문서 참조다. 없으면 해당 값을 null로 두고 unavailable_fields에 이유를 적는다.

Codex는 읽을 수 있는 Notion 문서에서 JSON을 저장한 뒤 다음 명령으로 대조한다.
문서를 읽은 것만으로 봇 설정이 적용되지는 않는다.

```bash
python -m runtime.bridge --input private-inventory.json --output private-inventory-review.json
```

Craft를 선택하면 접근 가능한 Daily Note에 같은 JSON과 원본 참조를 둔다.
공개 GitHub에는 코드·정책·익명화된 적용 상태만 남기고 실제 Bot ID·비공개 산출물은 올리지 않는다.
