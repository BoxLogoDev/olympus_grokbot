# 헤스티아: bridge 재검사와 기존 바인딩 재확인

범위: 원본 보존 → 수정된 bridge 검사 → 기존 객체 분류 → 소수 인간의 연결 근거 확인 → Notion 본문 기록.
봇·루틴·권한·원장 등록·제작 작업을 새로 실행하는 지시가 아니다.

## 1. 검사기 버전 고정

기존 import와 원본 export를 보존한다. bridge 0.1.1을 포함하는 새 번들을 별도 디렉터리에 풀고
BUNDLE-MANIFEST.json의 implementation_commit과 파일 해시를 확인한다. 기존 import에 덮어쓰지 않는다.
Grokbot 환경에서는 python3가 사용 가능했으므로 python3 --version으로 3.11 이상을 확인한다.

runtime/bridge.py가 있는 새 번들 루트에서 실행한다. 출력 파일이 존재하면 새 이름을 사용한다.

```bash
python3 -m runtime.bridge --input /workspace/olympus-private/export-2026-09-05/private-inventory.json --output /workspace/olympus-private/export-2026-09-05/bridge-review-02-original.json
python3 -m runtime.bridge --input /workspace/olympus-private/export-2026-09-05/private-inventory.lines-upper.json --output /workspace/olympus-private/export-2026-09-05/bridge-review-02-lines-upper.json
```

원본의 product_line이 소문자이면 첫 명령은 종료 코드 2이며 성공 보고서를 만들지 않아야 한다.
오류 메시지와 원본 해시를 기록한다. 대문자 사본은 성공 시 bridge_version=0.1.1인지 확인한다.
자동으로 원본을 고치지 않는다. 기존 변환 로그로 바꾼 필드가 product_line뿐인지 대조한다.

run_count와 categorized_run_count가 원본 총 업무 수와 일치해야 한다.
라인별 available_runs = inspected_runs + omitted_by_limit인지 확인한다.
시작 시각이 없으면 unknown_started_at으로 드러나고 최신순 확인은 미완료로 남는다.
중복 루틴 검사는 eligible_count/total_count와 incomplete_records를 함께 보고한다.
후보 0건을 중복 없음으로 판정하지 않는다.

## 2. 기존 객체를 재분류한다

원본에서 HUMAN으로 분류된 각 객체가 실제 인간, 채널, 빈 프로필, 미확인 중 무엇인지
현재 공개 가능한 메타데이터로 확인한다. 이름만으로 바꾸지 않고 원본 kind와 분류 근거를 함께 보존한다.
채널·빈 프로필·미확인 항목은 배정 가능한 인간 수에 포함하지 않는다. 삭제·이름 변경·중복 생성은 하지 않는다.

원장 등록에 필요한 owner_god는 슬롯 카탈로그의 department 코드다.
예를 들어 표시 이름 헤라와 HERA를 같은 값으로 가정하지 않는다.
원문 값, 정규화 후보, 근거를 각각 기록하고 single_job도 카탈로그와 대조한다.

## 3. 이미 슬롯이 알려진 소수 인간부터 확인한다

우선 아래 슬롯과 연결됐다고 보고된 기존 인간들을 확인한다. 실제 Bot ID는 비공개 기록을 따른다.
이 목록은 해당 인간의 직무가 현재 검증됐다는 뜻이 아니다.

- HERA-ACCEPTANCE-GATE
- HEPHAESTUS-CHARACTER-ILLUSTRATOR
- HEPHAESTUS-CHARACTER-ANIMATOR
- DEMETER-ASSET-LIBRARIAN
- HEPHAESTUS-IMAGE-PROCESSOR
- APHRODITE-EXPRESSION-DESIGNER

각 항목에 human_id 후보, 기존 bot_id, 객체 종류, 부모 신 원문/코드, slot_id, single_job,
Skill 출처·ID·버전·바이트 해시, 도구 이름, 확인 근거, 누락 사유를 기록한다.
없는 human_id를 이미 등록된 ID처럼 보고하지 않는다.

스킬 카탈로그에 존재한다는 사실과 해당 봇/업무에서 실제 선택·사용했다는 사실을 구분한다.
skill_ref가 null이라는 이유만으로 Skill을 사용하지 않았다고 결론내리지 않는다.
봇에 고정 Skill이 없는 구조라면 그 사실과 업무별 선택 방식부터 기록한다.
적용을 제안하는 Skill과 현재 사용을 확인한 Skill을 서로 다른 필드로 둔다.

도구 이름과 적용 범위는 비밀값이 없는 프로필·Skill 지침·호출 기록·도구 목록에서 확인한다.
목록에 선언됨, 연결 사용 가능, 실제 호출 근거 있음도 구분한다.
도구 목록 확보를 위해 시크릿을 읽지 않는다. null은 미확인, []는 확인 결과 사용할 도구 없음으로 구분한다.
확인할 수 없는 값은 근거 있는 누락 사유로 남긴다.

나머지는 슬롯 매핑 후보와 근거만 정리한다. 빈칸을 채우려고 직무나 권한을 바꾸지 않는다.
BAM 원형·SRC·제작 승인은 별도 준비 조건으로 유지한다.

## 4. 수신 가능한 결과를 남긴다

기존 Notion 상세 페이지에 다음을 본문으로 기록하고 다시 읽어 확인한다.

- 검사기 버전·실제 구현 커밋·명령·종료 코드
- 전체/분류/검사/제외 업무 수, 날짜 미확인 수, 루틴 비교 가능 범위
- 객체 분류 수정 후보와 근거, 배정 가능한 인간 수의 확인 상태
- 우선 인간들의 연결 확인표: 확인됨 / 미확인 / 불일치, 누락 필드별 다음 행동
- 원본·사본·변환 로그·결과 파일 참조와 해시
- 비용 미측정과 실제 수동 검증 미실시 상태

본문에는 Codex가 첨부를 받지 못해도 다음 판단을 할 수 있는 필드와 근거 요약을 포함한다.
실제 Bot ID와 운영 자료는 비공개 Notion에만 둔다.
이 범위의 정상적인 검사·조회·기록은 추가 진행 승인을 묻지 않고 마친다.
