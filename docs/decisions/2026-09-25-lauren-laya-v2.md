# 2026-09-25 — Lauren Tan 방식 + Laya 라우터 (문서 레이어)

- 상태: DOCUMENTED. 라이브 봇·루틴·업로드·Studio는 이 커밋으로 바뀌지 않는다.
- 운영 기준은 그대로 [SHORTS_Operating_v1.md](../../SHORTS_Operating_v1.md).
- 이 문서는 창구 설계, 토큰 절감, 프로필 교체 초안이다. 적용은 사용자 채택 후.

## 판단

1. 현재 살아있는 조직은 올림푸스 12신이 아니라 숏츠 12슬롯이다. 91개 VACANT 슬롯과 빈 `humans.yaml`을 부활시키지 않는다.
2. Lauren Tan의 첫 고용은 Chief of Staff다. 이미 `[숏츠] 총괄`이 그 자리이다. 새 창구 봇을 만들지 않는다.
3. Grok Bot 안에서 모델을 Laya로 바꿀 수는 없다. Laya는 생성 모델이 아니라 깨우기 전 분류기다.
4. 토큰이 새는 지점은 워커 상시 기동, 죽은 헌법 루틴, 게이트 3중 Grok 호출, 긴 헌법 프롬프트다.
5. 채널기준·채널운영 봇은 당장 삭제하지 않는다. Laya 1차 뒤로 후퇴시키고, 실패가 줄면 그때 흡수한다.

## 채택하면 하는 일

1. `[숏츠] 총괄` 프로필을 `prompts/SHORTS_Bot_Prompts_v2.md`의 CoS 블록으로 교체한다.
2. 워커 프로필을 같은 파일의 4줄 계약으로 교체한다. OLYMPUS 헌법 본문을 프로필에 넣지 않는다.
3. 총괄 루틴 3개만 남긴다. `헌법 아침 동기화`, `헌법 개선 제안`, paused `개발 승인 확인`은 삭제 또는 유지 pause.
4. Mac mini에서 Laya multilingual을 띄우고 `runtime/laya_router.py`를 총괄 스킬로 연결한다.
5. 설치 실패 시 총괄이 같은 질문셋을 직접 답하고, Laya 미사용을 Facts에 적는다.

## 채택해도 하지 않는 일

- 업로드, 예약, Studio 한도, UPLOAD-HOLD, #100 순서 변경
- 신 이름 슬롯 재배정
- 새 봇 대량 생성
- 품질게이트 최종 PASS를 Laya에 넘기기
