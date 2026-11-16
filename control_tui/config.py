"""관제 설정 값 (BUILD_PLAN §5.1, SCREEN §3, §4)."""

# 허락 창에서 보낼 키 (BUILD_PLAN §6 확인 2, 2026-11-09 실제 패널 실험, Claude Code 2.1.319).
# - 허락 창은 번호 목록이다: 1. Yes / 2. 늘 허용(문구가 명령마다 바뀜) / 3. auto로 바꾸기 / 4. No. 선택지 수는 바뀔 수 있다.
# - y, n 글자는 무시됐다. Enter는 강조된 1번(Yes)을 고르므로 절대 보내지 않는다.
# - "1"은 Enter 없이 바로 한 번 허용한다. Esc는 거절한다 ("No"의 번호는 선택지 수에 따라 바뀌므로 쓰지 않는다).
# - 거절하면 훅이 더 오지 않는다. 상태 복구는 대화 기록의 중단 표시로 한다 (store.load_sessions).
PERMISSION_KEYS = {"y": "1", "n": "\x1b"}
PERMISSION_KEYS_VERIFIED = True

# 닫힌 세션은 종료 뒤 이 시간(초)이 지나면 ① 목록에서 숨긴다. 기록은 지우지 않는다 (요청 35, BUILD_PLAN §3.1.1)
ENDED_HIDE_SECONDS = 600

# 질문 창(AskUserQuestion)에 키를 보낼 때 키 사이 간격(초). 숫자 하나에 창이 다음 질문을 그리므로 잠깐 기다린다.
# 2026-11-10 실험은 1초 간격으로 확인했다 (SCREEN §8, 요청 39)
QUESTION_KEY_GAP = 0.4
# 보내기 전에 패널 화면에서 질문 창을 알아보는 글 (Claude Code 2.1.322 질문 창 맨 아래 안내)
QUESTION_SCREEN_MARK = "Esc to cancel"
