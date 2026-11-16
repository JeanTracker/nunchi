import { expect, test } from 'claude-code/testing'
import { answersAfter, answerEnded, pieces as piecesOf } from './register.js'

// SCREEN §11: 관제 분석 결과를 읽어 세션 옆 패널에 보인다
const ANALYSIS = {
  last_turn: 3,
  flow: {
    version: 3,
    until: 3,
    current_goal: { text: 'CHANGELOG 만들기', turn: 3 },
    steps: [
      { index: 1, grounded: true, label: '시작', summary: 'README 설치 절', agent_summary: '설치 절 추가', digest: 'README 설치 절을 요청함' },
      { index: 2, grounded: true, label: '확정', summary: '설치 절 확정', agent_summary: '확정함', title: '설치 절 확정' },
      { index: 3, grounded: true, label: '구체화', summary: 'CHANGELOG 요청', agent_summary: 'CHANGELOG를 만들고 폭을 물음', shift: true, digest: '설치 절을 정한 뒤 CHANGELOG를 요청함' },
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

function engine(on: any, status: unknown, want = false, analysis: unknown = ANALYSIS, events = '') {
  on('command.register', () => ({ value: { command: 'nunchi' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: unknown, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'abc' }))
  on('env.get', (_: unknown, e: any) => ({ value: e.name === 'HOME' ? '/home/me' : undefined }))
  on('clock.every', () => ({ value: null }))
  on('clock.now', () => ({ value: 1000 }))
  on('fs.read', (_: unknown, e: any) => {
    const p = String(e.path ?? e)
    if (p.endsWith('/sessions/abc/analysis.json')) return { value: JSON.stringify(analysis) }
    if (p.endsWith('/sessions/abc/analysis_status.json')) return { value: JSON.stringify(status) }
    if (p.endsWith('/sessions/abc/glossary.json')) return { value: JSON.stringify(GLOSS) }
    if (p.endsWith('/sessions/abc/want') && want) return { value: '{"at":"x"}' }
    if (p.endsWith('/sessions/abc/events.jsonl') && events) return { value: events }
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
  expect((await ui.find({ type: 'Text', text: /흐름\s+#1–#3/ }))).toBeTruthy()             // 처음부터 한 덩어리 정리 (요구 이력 57)
  expect((await ui.find({ type: 'Text', text: /^\s+설치 절을 정한 뒤 CHANGELOG를 요청함$/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /README 설치 절을 요청함/ }))).toBeFalsy()   // 마지막 정리 하나만
  expect((await ui.find({ type: 'Text', text: /지금 목표\s+#3부터/ }))).toBeTruthy()       // 이름 줄
  expect((await ui.find({ type: 'Text', text: /^\s+CHANGELOG 만들기$/ }))).toBeTruthy()      // 다음 줄에 들여 쓴 내용
  expect((await ui.find({ type: 'Text', text: /✔ 설치 절 확정/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /CHANGELOG를 만들고 폭을 물음/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /테스트 돌리기 — 못 했거나 미룸/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /도구 실패/ }))).toBeFalsy()          // 도구 실패는 보이지 않는다 (요구 이력 48)
  expect((await ui.find({ type: 'Text', text: /대화 정리/ }))).toBeFalsy()          // 턴별 목록은 두지 않는다
  await ui.unmount()
})

test('a session with only its first turn analyzed shows the goal without a flow summary', async ($, on) => {
  const first = { ...ANALYSIS, last_turn: 1, flow: { ...ANALYSIS.flow, until: 1, steps: ANALYSIS.flow.steps.slice(0, 1) } }
  engine(on, { state: 'idle', turn: 0 }, false, first)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /흐름\s+#1/ }))).toBeFalsy()
  expect((await ui.find({ type: 'Text', text: /^ 목표/ }))).toBeTruthy()
  await ui.unmount()
})

test('while the control analyzes, the head shows 분석 중', async ($, on) => {
  engine(on, { state: 'running', turn: 3 })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /분석 중/ }))).toBeTruthy()
  await ui.unmount()
})

// 요구 이력 55: /nunchi로 켜지 않은 세션은 옛 결과가 더 이어지지 않는다고 머리 줄에 알린다
test('a session not turned on says automatic analysis is off', async ($, on) => {
  engine(on, { state: 'idle', turn: 0 })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /자동 분석 꺼짐 · \/nunchi로 켜기/ }))).toBeTruthy()
  await ui.unmount()
})

test('a session turned on with /nunchi does not say it is off', async ($, on) => {
  engine(on, { state: 'idle', turn: 0 }, true)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /#3 기준/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /자동 분석 꺼짐/ }))).toBeFalsy()
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

// 요구 이력 56: 관제로 버튼. 관제가 켜져 있으면 goto를 남기고 관제 패널을 앞으로, 꺼져 있으면 안내
function withControl(on: any, runs: string[][], written: Record<string, string>, control: boolean, alive = true) {
  on('command.register', () => ({ value: { command: 'nunchi' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: unknown, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'abc' }))
  on('env.get', (_: unknown, e: any) => ({ value: e.name === 'HOME' ? '/home/me' : undefined }))
  on('clock.every', () => ({ value: null }))
  on('clock.now', () => ({ value: 5000 }))
  on('fs.write', (_: unknown, e: any) => { written[String(e.path)] = String(e.data ?? e.content ?? e.text ?? ''); return { value: null } })
  on('process.run', (_: unknown, e: any) => {
    const argv = (e.argv ?? e) as string[]
    runs.push([...argv])
    const ok = argv[0] === 'kill' ? alive : true
    return { value: { exitCode: ok ? 0 : 1, stdout: argv[0] === 'osascript' ? 'ok\n' : '', stderr: '' } }
  })
  on('fs.read', (_: unknown, e: any) => {
    const p = String(e.path ?? e)
    if (p.endsWith('/sessions/abc/analysis.json')) return { value: JSON.stringify(ANALYSIS) }
    if (p.endsWith('/sessions/abc/want')) return { value: '{"at":"x"}' }
    if (p.endsWith('/.claude-control/control.json') && control) return { value: '{"iterm_session_id":"CTRL-1","pid":4321}' }
    throw new Error('missing ' + p)
  })
}

test('with the control running, 관제로 leaves a goto and brings the control panel to front', async ($, on) => {
  const runs: string[][] = []
  const written: Record<string, string> = {}
  withControl(on, runs, written, true)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /또는 ⌘숫자/ }))).toBeTruthy()
  await ui.press({ key: 'control' })
  expect(runs.some(r => r[0] === 'kill' && r[2] === '4321')).toBe(true)
  const goto = Object.entries(written).find(([p]) => p.endsWith('/.claude-control/goto'))
  expect(goto && JSON.parse(goto[1]).session).toBe('abc')
  expect(JSON.parse(goto![1]).at).toBe(5)                       // 초 단위 (관제가 time.time()과 비교)
  expect(runs.some(r => r[0] === 'osascript' && r[r.length - 1] === 'CTRL-1')).toBe(true)
  await ui.unmount()
})

test('without the control, the tail says it is off and offers no button', async ($, on) => {
  const runs: string[][] = []
  withControl(on, runs, {}, false)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /관제 꺼짐 · nunchi로 켜기/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /또는 ⌘숫자/ }))).toBeFalsy()
  await ui.unmount()
})

test('a stale control file (dead pid) does not write goto or run osascript', async ($, on) => {
  const runs: string[][] = []
  const written: Record<string, string> = {}
  withControl(on, runs, written, true, false)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'control' })
  expect(Object.keys(written).some(p => p.endsWith('/goto'))).toBe(false)
  expect(runs.some(r => r[0] === 'osascript')).toBe(false)
  await ui.unmount()
})

test('a wide symbol touching the next letter gets one space after it (요구 이력 58)', async ($, on) => {
  const touching = { ...ANALYSIS, flow: { ...ANALYSIS.flow, current_goal: { text: 'A→B …끝 ◆ 그대로 ─선', turn: 3 } } }
  engine(on, { state: 'idle', turn: 0 }, false, touching)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /^\s+A→ B … 끝 ◆ 그대로 ─선$/ }))).toBeTruthy()   // 괘선은 그대로
  await ui.unmount()
})

test('links in the pane are drawn as Link elements a click opens (요구 이력 60)', async ($, on) => {
  const steps = ANALYSIS.flow.steps.map((x: any) => x.index === 3 ? { ...x, agent_summary: '[가이드](https://example.com/g)를 읽고 정리함.' } : x)
  const linked = { ...ANALYSIS, flow: { ...ANALYSIS.flow, steps,
    current_goal: { text: '시안 https://claude.ai/artifact/R8EpVcd9cueTtn7Ep2MS82 확인.', turn: 3 } } }
  engine(on, { state: 'idle', turn: 0 }, false, linked)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, props: { ...PANE.props, bodyColumns: 30 }, surface: 'terminal' })
  const hrefs = (await ui.findAll({ type: 'Link' })).map((l: any) => l.props?.href)
  expect(hrefs.filter((h: string) => h === 'https://claude.ai/artifact/R8EpVcd9cueTtn7Ep2MS82').length).toBe(2)  // 줄이 나뉘어도 조각마다 같은 주소
  expect(hrefs).toContain('https://example.com/g')
  expect(hrefs).not.toContain('https://claude.ai/artifact/R8EpVcd9cueTtn7Ep2MS82.')                           // 끝 마침표는 주소가 아니다
  expect((await ui.find({ type: 'Text', text: /\]\(/ }))).toBeFalsy()                                           // [이름](주소)는 이름만
  await ui.unmount()
})

test('more than three remaining requests end with how many more (요구 이력 64)', async ($, on) => {
  const many = { ...ANALYSIS, flow: { ...ANALYSIS.flow, requests: [1, 2, 3, 4].map(i =>
    ({ id: `R${i}`, from_turn: i, summary: `남은 일 ${i}`, state: 'deferred' })) } }
  engine(on, { state: 'idle', turn: 0 }, false, many)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /남은 것 4/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /남은 일 4/ }))).toBeFalsy()
  expect((await ui.find({ type: 'Text', text: /… 1개 더 · 관제 c/ }))).toBeTruthy()
  await ui.unmount()
})

test('the head says how many answers came after the analyzed one (요구 이력 65)', async ($, on) => {
  const at = { ...ANALYSIS, source_ts: '2026-11-16T05:57:07.474Z' }
  const ev = [
    { ts: '2026-11-16T05:57:07.474Z', event: 'Stop' },            // 분석이 본 응답
    { ts: '2026-11-16T06:07:56.011Z', event: 'UserPromptSubmit' },
    { ts: '2026-11-16T06:08:06.653Z', event: 'Stop' },
    { ts: '2026-11-16T06:08:57.311Z', event: 'Stop' },
    { ts: '2026-11-16T06:09:14.662Z', event: 'Stop' },             // 같은 턴에서 이어 끝난 응답도 센다
  ].map(e => JSON.stringify(e)).join('\n') + '\n'
  engine(on, { state: 'idle', turn: 0 }, false, at, ev)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /#3 기준 · 응답 3개 밀림/ }))).toBeTruthy()
  await ui.unmount()
})

test('nothing is said when the analysis has seen the last answer', async ($, on) => {
  const at = { ...ANALYSIS, source_ts: '2026-11-16T06:09:14.662Z' }
  const ev = JSON.stringify({ ts: '2026-11-16T06:09:14.662Z', event: 'Stop' }) + '\n'
  engine(on, { state: 'idle', turn: 0 }, false, at, ev)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /밀림/ }))).toBeFalsy()
  await ui.unmount()
})

test('a request still in progress stays in what is left with a half mark (요구 이력 66)', async ($, on) => {
  const prog = { ...ANALYSIS, flow: { ...ANALYSIS.flow, requests: [
    { id: 'R1', from_turn: 2, by_turn: 4, summary: '약관 취소 버튼', state: 'in_progress', agent_quote: '병합은 하지 않았습니다' }] } }
  engine(on, { state: 'idle', turn: 0 }, false, prog)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /남은 것 1/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /◐ 약관 취소 버튼 — 진행 중 #4/ }))).toBeTruthy()
  await ui.unmount()
})

test('the events file is read again only after an answer ends, not every second', async () => {
  let reads = 0
  let now = 1000
  let ev = JSON.stringify({ ts: '2026-11-16T05:57:07.474Z', event: 'Stop' }) + '\n'
  const fake: any = { clock: { now: async () => now }, fs: { read: async () => { reads++; return ev } } }
  answerEnded(-99999)   // 앞 테스트가 남긴 값을 지운다
  const since = '2026-11-16T05:57:07.474Z'
  expect(await answersAfter(fake, '/d', since)).toBe(0)
  ev += JSON.stringify({ ts: '2026-11-16T06:08:00.000Z', event: 'PostToolUse' }) + '\n'
  ev += JSON.stringify({ ts: '2026-11-16T06:08:06.653Z', event: 'Stop' }) + '\n'
  now = 2000
  expect(await answersAfter(fake, '/d', since)).toBe(0)       // 응답이 끝났다는 알림 전에는 다시 읽지 않는다
  expect(reads).toBe(1)
  answerEnded(now)
  expect(await answersAfter(fake, '/d', since)).toBe(1)       // 응답이 끝나면 다시 센다
  now = 9000
  await answersAfter(fake, '/d', since)
  expect(reads).toBe(2)                                       // 5초가 지나면 다시 읽지 않는다
  expect(await answersAfter(fake, '/d', '2026-11-16T06:08:06.653Z')).toBe(0)   // 분석 기준이 바뀌면 다시 센다
  expect(reads).toBe(3)
})

test('a bare link stops before Korean particles, backticks and bold marks', async () => {
  const { pieces } = await Promise.resolve({ pieces: piecesOf })
  const hrefs = (t: string) => pieces(t).filter(p => p.href).map(p => p.href)
  expect(hrefs('https://git.example.com/merge_requests/12를 올렸습니다')).toEqual(['https://git.example.com/merge_requests/12'])
  expect(hrefs('주소는 `https://x.com/a` 입니다')).toEqual(['https://x.com/a'])
  expect(hrefs('**https://x.com/a**에서 보세요')).toEqual(['https://x.com/a'])
  expect(hrefs('https://x.com/a?b=1&c=2.')).toEqual(['https://x.com/a?b=1&c=2'])
})
