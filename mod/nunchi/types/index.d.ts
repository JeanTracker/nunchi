// 눈치 mod가 세션 동안 들고 있는 값 (REQUIREMENTS R17, SCREEN §11, 요구 이력 45)
// turn: 마지막으로 물은 턴, first: 처음 물은 턴 (요구 이력 86)
export type Ask = { n: number; summary: string; turn: number; first: number; quote: string; partial: boolean }

export type Term = { id: string; means: string[] }   // 번호 풀이 (요구 이력 51)

export type Left = { mark: string; summary: string; note: string; turn: number; quote: string; stale?: boolean }   // quote: 에이전트 원문 (⊘·알려진 문제, 요구 이력 86), stale: 10턴 이상 그대로인 진행 중 (요구 이력 103)

export type View = {
  basis: number          // 어느 턴까지 분석했나
  total: number          // 요청 기준 마지막 턴 (흐름을 다시 만드는 중인지 알 때)
  latest: number         // 상태 파일이 알려 준 지금 도는 턴 (분석 중일 때)
  state: string          // idle · queued · running · none
  asks: Ask[]            // 에이전트 질문 (열린 것 모두, 최근 물은 것부터. 그릴 때 펼친 수만큼 자른다)
  askCount: number
  digest: string         // 처음부터 이 턴까지 흐름 한 덩어리 정리 (분석기 추정, 요구 이력 57)
  digestTurn: number     // 그 정리가 어느 턴까지인지
  goal: string           // 지금 목표
  goalTurn: number
  firstGoal: string      // 처음 목표 (flow.first_goal). 지금 목표와 다른 턴일 때만 두 층으로 보인다 (요구 이력 82)
  firstTurn: number
  direction: string      // 지금 목표가 정해진 단계의 방향: 넓힘 · 좁힘 · 옮김 (엔진이 한글로 적음)
  // warn: 이 결정을 빠뜨리거나 어긴 판정이 열려 있음(찾은 턴·종류·무엇) (요구 이력 87·89)
  // label: 결정 번호(한 턴에 결정이 둘 이상이면 '1-2', 아니면 '1', 요구 이력 90)
  decisions: { text: string; turn: number; label?: string; proposed: boolean; id?: string; warn?: { at: number; kind: string; what: string; quote?: string } }[]
  openWarn: number       // 열린 빠뜨림 수: 처리 결과의 프롬프트 복사 하나가 모두 담는다 (요구 이력 90)
  openSince: number      // 열린 빠뜨림 중 가장 먼저 찾은 턴   // 의사결정 (정해진 요건·방침과 그 턴, 제안을 받아들인 것인지. 최근 것부터 모두, 요구 이력 71·72·74·86)
  decisionCount: number  // 의사결정 전체 수
  recent: string         // 방금 한 일 (마지막 턴의 에이전트 요약)
  left: Left[]           // 남은 요청 (내 요청 중 남은 것 모두)
  known: Left[]          // 알려진 문제: 조사는 했으나 결과 없음 (요구 이력 86)
  handled: Left[]        // 처리 결과: 마지막 분석 턴에 생기거나 상태가 바뀐 내 요청 (요구 이력 87·88)
  handledTurn: number
  past: Ask[]            // 지난 질문: 마지막 응답 전에 물은 열린 질문 (요구 이력 86)
  pastCount: number
  leftCount: number
  ratio: number          // 옆 패널 폭 비율 (관제 설정 mod_width_ratio)
  terms: Term[]          // 마지막 응답에 나온 기획 번호와 문서 원문 뜻
  termsMore: number
  tick: number           // '분석 중...' 점을 바꾸려고 1초마다 올린다
  on: boolean            // 이 세션에서 /nunchi로 눈치를 켰는지 (세션 폴더의 want, 요구 이력 53)
  off: boolean           // /nunchi off로 끈 세션인지 (want의 on이 false, 요구 이력 62·84). 켜지 않음은 on·off 둘 다 false
  noHook: boolean        // 이 세션의 발화나 응답 끝을 본 뒤에도 훅 기록(events.jsonl)이 없는지 (요구 이력 84)
  error: string          // 분석 실패 이유 한 줄
  control: boolean       // 관제가 켜져 있는지 (<관제 홈>/control.json, 요구 이력 56)
  behind: number         // 분석이 본 마지막 응답 뒤에 끝난 응답 수 (events.jsonl의 Stop, 요구 이력 65)
  pending: boolean       // 분석이 본 마지막 응답 뒤에 사람이 보낸 발화가 있는지 (요구 이력 82)
  ui: 'ko' | 'en'        // 화면 언어 (요구 이력 76)
  want: string           // 지금 판정된 분석 언어: ko · en · 그 밖은 소문자 원래 값
  from: string           // 판정 출처: saved · claude · terminal · default
  flowLang: string       // 이 세션이 실제로 분석된 언어 (analysis.flow.lang, 없으면 ko)
  analyzed: boolean      // 분석 결과가 있는지
  rebuilding: boolean    // 다시 분석 중 (상태 파일의 rebuild)
}

// 처음 3개보다 더 보이는 수 (요구 이력 74). 세션 동안 남고 세션마다 따로
export type More = { decisions: number; asks: number; left: number; handled: number }   // 이 세션에만 (요구 이력 77)

declare module 'claude-code' {
  interface PluginState {
    nunchi: { view: Shaped<View>; more: Shaped<More>; open: Shaped<Record<string, number>> }   // open: 글을 펼친 덩어리와 그때의 분석 기준 턴 (요구 이력 88)
  }
}
