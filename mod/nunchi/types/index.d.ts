// 눈치 mod가 세션 동안 들고 있는 값 (REQUIREMENTS R17, SCREEN §11, 요구 이력 45)
export type Ask = { n: number; summary: string; turn: number; quote: string; partial: boolean; stale: boolean }

export type Term = { id: string; means: string[] }   // 번호 풀이 (요구 이력 51)

export type Left = { mark: string; summary: string; note: string; turn: number }

export type View = {
  basis: number          // 어느 턴까지 분석했나
  total: number          // 요청 기준 마지막 턴 (흐름을 다시 만드는 중인지 알 때)
  latest: number         // 상태 파일이 알려 준 지금 도는 턴 (분석 중일 때)
  state: string          // idle · queued · running · none
  asks: Ask[]            // 에이전트 질문 (열린 것, 최근 물은 것부터)
  askCount: number
  blanketClosed: number  // 통째 승인으로 닫힌 것 수
  digest: string         // 처음부터 이 턴까지 흐름 한 덩어리 정리 (분석기 추정, 요구 이력 57)
  digestTurn: number     // 그 정리가 어느 턴까지인지
  goal: string           // 지금 목표
  goalTurn: number
  decisions: { text: string; turn: number }[]   // 의사결정 (결정 턴 이름과 그 턴, 최근 3개, 요구 이력 71)
  decisionCount: number  // 의사결정 전체 수
  recent: string         // 방금 한 일 (마지막 턴의 에이전트 요약)
  left: Left[]           // 남은 요청 (내 요청 중 남은 것)
  leftCount: number
  ratio: number          // 옆 패널 폭 비율 (관제 설정 mod_width_ratio)
  terms: Term[]          // 마지막 응답에 나온 기획 번호와 문서 원문 뜻
  termsMore: number
  tick: number           // '분석 중...' 점을 바꾸려고 1초마다 올린다
  on: boolean            // 이 세션에서 /nunchi로 눈치를 켰는지 (세션 폴더의 want, 요구 이력 53)
  error: string          // 분석 실패 이유 한 줄
  control: boolean       // 관제가 켜져 있는지 (<관제 홈>/control.json, 요구 이력 56)
  behind: number         // 분석이 본 마지막 응답 뒤에 끝난 응답 수 (events.jsonl의 Stop, 요구 이력 65)
}

declare module 'claude-code' {
  interface PluginState {
    nunchi: { view: Shaped<View> }
  }
}
