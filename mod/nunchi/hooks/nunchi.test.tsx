import { expect, test } from 'claude-code/testing'

// SCREEN §11: 관제 분석 결과를 읽어 세션 옆 패널에 보인다
const ANALYSIS = {
  last_turn: 3,
  flow: {
    version: 3,
    until: 3,
    current_goal: { text: 'CHANGELOG 만들기', turn: 3 },
    steps: [
      { index: 1, grounded: true, label: '시작', summary: 'README 설치 절', agent_summary: '설치 절 추가' },
      { index: 2, grounded: true, label: '확정', summary: '설치 절 확정', agent_summary: '확정함', title: '설치 절 확정' },
      { index: 3, grounded: true, label: '구체화', summary: 'CHANGELOG 요청', agent_summary: 'CHANGELOG를 만들고 폭을 물음', shift: true },
    ],
    requests: [
      { id: 'R1', from_turn: 1, summary: '설치 절 추가', state: 'addressed', tool_failed: true },
      { id: 'R2', from_turn: 3, summary: '테스트 돌리기', state: 'deferred' },
    ],
    asks: [
      { id: 'Q1', turn: 1, last_turn: 1, summary: '색 고르기', quote: '색은 어느 쪽으로 할까요?', state: 'open' },
      { id: 'Q2', turn: 3, last_turn: 3, summary: '폭 정하기', quote: '폭은 몇 칸으로 할지 알려 주세요', state: 'partial' },
      { id: 'Q3', turn: 2, summary: '진행할지', quote: '진행할까요?', state: 'answered', by_blanket: true },
    ],
  },
}

const GLOSS = { turn: 3, total: 3, items: [
  { id: 'R17', means: ['세션 안(mod)에서 흐름을 빠르게 되짚고, 부족하면 관제로 간다'] },
  { id: '요구 이력 46', means: ['6,000자 상한 없애기', 'dockColumns 지우기'] },
] }

const PANE = {
  plugin: 'nunchi',
  component: 'Pane',
  requestId: 'nunchi',
  props: { title: '눈치', isFocused: false, bodyColumns: 50, placement: 'dock', scroll: { offset: 0, bodyRows: 30 }, view: {} },
} as const

function engine(on: any, status: unknown) {
  on('command.register', () => ({ value: { command: 'nunchi' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: unknown, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'abc' }))
  on('env.get', (_: unknown, e: any) => ({ value: e.name === 'HOME' ? '/home/me' : undefined }))
  on('clock.every', () => ({ value: null }))
  on('clock.now', () => ({ value: 1000 }))
  on('fs.read', (_: unknown, e: any) => {
    const p = String(e.path ?? e)
    if (p.endsWith('/sessions/abc/analysis.json')) return { value: JSON.stringify(ANALYSIS) }
    if (p.endsWith('/sessions/abc/analysis_status.json')) return { value: JSON.stringify(status) }
    if (p.endsWith('/sessions/abc/glossary.json')) return { value: JSON.stringify(GLOSS) }
    throw new Error('missing ' + p)
  })
}

test('the pane shows what the agent asks first, then so far, then what is left', async ($, on) => {
  engine(on, { state: 'idle', turn: 0 })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /에이전트가 묻는 것 2/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /1 폭 정하기 #3 · 일부 답함/ }))).toBeTruthy()      // 최근에 물은 것부터
  expect((await ui.find({ type: 'Text', text: /2 색 고르기 #1부터 답 없음/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /“폭은 몇 칸으로 할지 알려 주세요”/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /통째 승인으로 닫은 것 1/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /목표\s+#3부터/ }))).toBeTruthy()             // 이름 줄
  expect((await ui.find({ type: 'Text', text: /^\s+CHANGELOG 만들기$/ }))).toBeTruthy()      // 다음 줄에 들여 쓴 내용
  expect((await ui.find({ type: 'Text', text: /✔ 설치 절 확정/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /CHANGELOG를 만들고 폭을 물음/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /테스트 돌리기 — 못 했거나 미룸/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /도구 실패/ }))).toBeFalsy()          // 도구 실패는 보이지 않는다 (요구 이력 48)
  expect((await ui.find({ type: 'Text', text: /대화 정리/ }))).toBeFalsy()          // 턴별 목록은 두지 않는다
  await ui.unmount()
})

test('while the control analyzes, the head shows 분석 중', async ($, on) => {
  engine(on, { state: 'running', turn: 3 })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /분석 중/ }))).toBeTruthy()
  await ui.unmount()
})

test('on a narrow pane the summary wraps onto indented lines instead of being cut', async ($, on) => {
  engine(on, { state: 'idle', turn: 0 })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, props: { ...PANE.props, bodyColumns: 24 }, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /^\s+CHANGELOG를 만들고$/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /^\s+폭을 물음$/ }))).toBeTruthy()          // 잘리지 않고 다음 줄로
  await ui.unmount()
})

test('the glossary of the last answer shows at the bottom', async ($, on) => {
  engine(on, { state: 'idle', turn: 0 })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /번호 풀이/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /^ R17$/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /세션 안\(mod\)에서 흐름을 빠르게/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /① 6,000자 상한 없애기/ }))).toBeTruthy()      // 같은 번호의 두 뜻
  expect((await ui.find({ type: 'Text', text: /② dockColumns 지우기/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /1개 더/ }))).toBeTruthy()
  await ui.unmount()
})


// 요구 이력 53: 켜지 않은 세션은 패널을 열지 않고, /nunchi로 켜면 관제 없이도 분석 대상이 된다
function bare(on: any, status: unknown, opened: string[], written: string[], want = false) {
  on('command.register', () => ({ value: { command: 'nunchi' } }))
  on('ui.open', (_: unknown, e: any) => { opened.push(String(e.id)); return { value: { isPlaced: true } } })
  on('session.start', (_: unknown, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'abc' }))
  on('env.get', (_: unknown, e: any) => ({ value: e.name === 'HOME' ? '/home/me' : undefined }))
  on('clock.every', () => ({ value: null }))
  on('clock.now', () => ({ value: 1000 }))
  on('fs.write', (_: unknown, e: any) => { written.push(String(e.path)); want = true; return { value: null } })
  on('fs.read', (_: unknown, e: any) => {
    const p = String(e.path ?? e)
    if (p.endsWith('/sessions/abc/analysis_status.json') && status) return { value: JSON.stringify(status) }
    if (p.endsWith('/sessions/abc/want') && want) return { value: '{"at":"x"}' }
    throw new Error('missing ' + p)
  })
}

test('a session that never turned nunchi on and has no analysis opens no pane', async ($, on) => {
  const opened: string[] = [], written: string[] = []
  bare(on, null, opened, written)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(opened.length).toBe(0)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /눈치 꺼짐 · \/nunchi로 켜면/ }))).toBeTruthy()
  await ui.unmount()
})

test('/nunchi writes the want mark, opens the pane and says the next answer will be analyzed', async ($, on) => {
  const opened: string[] = [], written: string[] = []
  bare(on, null, opened, written)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'nunchi' })
  expect(written.some(p => p.endsWith('/home/me/.claude-control/sessions/abc/want'))).toBe(true)
  expect(opened).toContain('nunchi')
  expect(String(r.text)).toMatch(/다음 응답이 끝나면 이 세션을 분석합니다/)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /눈치 켜짐 · 다음 응답이 끝나면 분석합니다/ }))).toBeTruthy()
  await ui.unmount()
})

test('a turned-on session opens by itself and shows waiting and failure lines', async ($, on) => {
  const opened: string[] = [], written: string[] = []
  bare(on, { state: 'queued', turn: 0 }, opened, written, true)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(opened).toContain('nunchi')
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /분석 대기/ }))).toBeTruthy()
  await ui.unmount()
})

test('a failed analysis shows its reason', async ($, on) => {
  const opened: string[] = [], written: string[] = []
  bare(on, { state: 'failed', turn: 0, error: '시간 초과 (150초)' }, opened, written, true)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /분석 실패 · 시간 초과/ }))).toBeTruthy()
  await ui.unmount()
})
