// 눈치 mod (REQUIREMENTS R17, SCREEN §11, BUILD_PLAN §4.4)
// 관제가 쓴 분석 결과(<관제 홈>/sessions/<세션 ID>/analysis.json)를 읽기만 하고, 세션 옆 패널(좁으면 입력창 위 한 줄)에 보인다.
// 분석은 하지 않는다. 분석 상태는 같은 폴더의 analysis_status.json에서 읽는다.
// /nunchi로 켜면 세션 폴더에 want를 남긴다. 그러면 관제가 꺼져 있어도 응답이 끝날 때마다 분석기가 이 세션을 분석한다 (요구 이력 53).
// 켜지 않았고 분석 결과도 없는 세션에서는 패널을 저절로 열지 않는다.
import { atom, read, update } from 'claude-code'
import type { Register, EngineInterface } from 'claude-code'

import type { View, Left } from '../types'

const PANE = 'nunchi'
const EMPTY: View = {
  basis: 0, total: 0, latest: 0, state: 'none', asks: [], askCount: 0, blanketClosed: 0,
  goal: '', goalTurn: 0, decisions: [], recent: '', left: [], leftCount: 0, ratio: 0.4, tick: 0,
  terms: [], termsMore: 0, on: false, error: '',
}
const view = atom({ plugin: 'nunchi', key: 'view' } as const, EMPTY, { shape: 'view-5' })

const SHOWN = 3
const MAX_RATIO = 0.45   // Claude Code가 옆 패널에 허락하는 폭
let paneDrawnAt = 0      // 패널이 마지막으로 그려진 때. 패널이 보이는 동안은 띠를 두지 않는다
let askedColumns = 0     // 마지막으로 요청한 옆 패널 폭
let opened = false       // 이 세션에서 패널을 한 번 열었는지 (켠 세션·분석된 세션만 저절로 연다)

async function controlHome($: EngineInterface): Promise<string> {
  return (await $.env.get('CONTROL_TUI_HOME')) || ((await $.env.get('HOME')) || '') + '/.claude-control'
}

async function sessionDir($: EngineInterface): Promise<string> {
  // 시험용: NUNCHI_MOD_SESSION을 주면 다른 세션의 분석을 본다 (실제 사용에서는 비워 둔다)
  const sid = (await $.env.get('NUNCHI_MOD_SESSION')) || (await $.session.id())
  return (await controlHome($)) + '/sessions/' + sid
}

async function readJson($: EngineInterface, path: string): Promise<any> {
  try {
    return JSON.parse(String(await $.fs.read(path)))
  } catch {
    return null
  }
}

function one(text: unknown, cut = 200): string {
  return String(text ?? '').split(/\s+/).join(' ').trim().slice(0, cut)
}

/** 켠 세션이거나 분석 결과가 있으면 패널을 둔다 (요구 이력 53) */
export function enabled(v: View): boolean {
  return v.on || v.basis > 0 || !!v.goal
}

export function buildView(analysis: any, status: any, tick: number, ratio: number, gloss: any = null, on = false): View {
  const terms = (gloss?.items ?? []).map((x: any) => ({ id: one(x.id, 20), means: (x.means ?? []).map((m: any) => one(m, 120)) }))
  const termsMore = Math.max(0, (gloss?.total ?? 0) - terms.length)
  const error = status?.state === 'failed' ? one(status?.error, 60) : ''
  const base = { ...EMPTY, state: status?.state ?? 'none', latest: status?.turn ?? 0, tick, ratio, terms, termsMore, on, error }
  if (!analysis) return base
  const flow = analysis.flow ?? {}
  const steps: any[] = (flow.steps ?? []).filter((s: any) => s.grounded)
  const basis = flow.until ?? analysis.last_turn ?? 0
  const open = (flow.asks ?? []).filter((a: any) => a.state !== 'answered')
    .sort((a: any, b: any) => (b.last_turn ?? b.turn ?? 0) - (a.last_turn ?? a.turn ?? 0))
  const asks = open.slice(0, SHOWN).map((a: any, k: number) => ({
    n: k + 1, summary: one(a.summary, 60), turn: a.turn ?? 0, quote: one(a.quote, 60),
    partial: a.state === 'partial', stale: (a.last_turn ?? a.turn ?? 0) < basis - 1,
  }))
  const left: Left[] = []
  for (const r of flow.requests ?? []) {
    if (r.state === 'open') left.push({ mark: '○', summary: one(r.summary), note: '', turn: r.from_turn ?? 0 })
    else if (r.state === 'deferred') left.push({ mark: '⊘', summary: one(r.summary), note: '못 했거나 미룸', turn: r.from_turn ?? 0 })
  }
  // 도구 실패(△)는 보이지 않는다: 도구 사용은 모으지도 보이지도 않는다 (요구 이력 48)
  const decisions = steps.filter((s: any) => s.label === '확정').slice(-SHOWN)
    .map((s: any) => one(s.title || s.decision || s.summary, 80))
  const last = steps.length ? steps[steps.length - 1] : null
  return {
    ...base,
    basis,
    total: analysis.last_turn ?? 0,
    state: status?.state ?? 'idle',
    asks,
    askCount: open.length,
    blanketClosed: (flow.asks ?? []).filter((a: any) => a.state === 'answered' && a.by_blanket).length,
    goal: one(flow.current_goal?.text ?? analysis.current_goal ?? ''),
    goalTurn: flow.current_goal?.turn ?? 0,
    decisions,
    recent: one(last?.agent_summary ?? '', 240),
    left: left.slice(0, SHOWN),
    leftCount: left.length,
  }
}

/** 칸 수(한글 2칸)로 자른다. 대화 정리는 턴마다 한 줄 (SCREEN §11) */
function cut(text: string, cols: number): string {
  let used = 0
  let out = ''
  for (const ch of text) {
    const w = /[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe30-\ufe4f\uff00-\uff60\uffe0-\uffe6]/.test(ch) ? 2 : 1
    if (used + w > cols - 1) return out + '…'
    out += ch
    used += w
  }
  return out
}

/** 칸 수(한글 2칸)에 맞춰 여러 줄로 감싼다. 넘치면 마지막 줄 끝을 …로 (요구 이력 50) */
function wrap(text: string, cols: number, maxLines: number): string[] {
  const wide = (ch: string) => /[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe30-\ufe4f\uff00-\uff60\uffe0-\uffe6\u2714]/.test(ch) ? 2 : 1
  const lines: string[] = []
  let cur = ''
  let used = 0
  for (const word of text.split(/(\s+)/)) {
    const w = [...word].reduce((n, ch) => n + wide(ch), 0)
    if (used + w > cols && cur.trim()) {
      lines.push(cur.trimEnd())
      cur = ''
      used = 0
      if (/^\s+$/.test(word)) continue
    }
    if (w > cols) {   // 한 낱말이 한 줄보다 길면 글자 단위로 자른다
      for (const ch of word) {
        if (used + wide(ch) > cols) { lines.push(cur); cur = ''; used = 0 }
        cur += ch
        used += wide(ch)
      }
      continue
    }
    cur += word
    used += w
  }
  if (cur.trim()) lines.push(cur.trimEnd())
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines)
    kept[maxLines - 1] = cut(kept[maxLines - 1] + ' …', cols)
    return kept
  }
  return lines
}

function dots(tick: number, state = 'running'): string {
  return (state === 'queued' ? '분석 대기' : '분석 중') + ['.', '..', '...'][tick % 3]
}

async function openPane($: EngineInterface) {
  opened = true
  return $.ui.open({ id: PANE, title: '눈치' })
}

async function refresh($: EngineInterface) {
  const dir = await sessionDir($)
  const [analysis, status, config, gloss, want] = await Promise.all([
    readJson($, dir + '/analysis.json'), readJson($, dir + '/analysis_status.json'),
    readJson($, (await controlHome($)) + '/config.json'), readJson($, dir + '/glossary.json'),
    readJson($, dir + '/want'),
  ])
  const ratio = Math.min(MAX_RATIO, Math.max(0.2, Number(config?.mod_width_ratio) || 0.4))
  await update($, view, old => buildView(analysis, status, (old?.tick ?? 0) + 1, ratio, gloss, want !== null))
  if (!opened && enabled(await read($, view))) void openPane($)   // 켠 세션이나 관제가 분석한 세션만 저절로 연다
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'nunchi', description: '눈치 켜기: 이 세션을 분석하고 패널을 연다 (관제 없이도)' })
    await refresh($)
    $.clock.every(1000, () => { void refresh($) })   // 분석 파일이 바뀌면 다시 그린다. '분석 중' 점도 1초마다
    return next(e)
  })

  on('command.run', { command: 'nunchi' }, async $ => {
    const dir = await sessionDir($)
    const was = (await readJson($, dir + '/want')) !== null
    await $.fs.write(dir + '/want', JSON.stringify({ at: new Date(await $.clock.now()).toISOString(), by: 'nunchi' }) + '\n')
    await refresh($)
    const r = await openPane($)
    const where = r.isPlaced ? '' : ' 창이 좁아 패널 대신 입력창 위 한 줄로 보입니다.'
    const v = await read($, view)
    if (was || v.basis > 0) return { text: '눈치 패널을 열었습니다.' + where }
    return { text: '눈치를 켰습니다. 다음 응답이 끝나면 이 세션을 분석합니다(관제를 켜지 않아도 됩니다).' + where }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const v = await read($, view)
    const cols = Math.max(20, e.props.bodyColumns ?? 50)
    paneDrawnAt = await $.clock.now()
    // viewport는 패널을 뺀 나머지 폭이라(실측 2026-11-12: 200칸 창에서 141), 창 전체 = 나머지 + 패널 + 경계로 본다
    const whole = (e.viewport?.columns ?? 0) + (e.props.placement === 'dock' ? cols + 2 : 0)
    const want = Math.round(whole * v.ratio)
    if (e.props.placement === 'dock' && want >= 24 && Math.abs(want - askedColumns) > 1) {
      askedColumns = want   // 창 폭의 비율로 다시 요청한다 (사용자가 끌어 정한 폭이 있으면 그것이 앞선다)
      void $.ui.open({ id: PANE, title: '눈치', columns: want })
    }
    const busy = v.state === 'running' || v.state === 'queued'
    const rebuilding = busy && v.latest > 0 && v.total > 0 && v.latest < v.total
    if (!v.goal && v.basis === 0) {   // 아직 분석 결과가 없다 (SCREEN §11)
      const line = v.state === 'running' || v.state === 'queued' ? <Text color="yellow">{dots(v.tick, v.state)}</Text>
        : v.state === 'failed' ? <Text color="red">분석 실패 · {v.error}</Text>
        : v.on ? <Text dimColor>눈치 켜짐 · 다음 응답이 끝나면 분석합니다</Text>
        : <Text dimColor>눈치 꺼짐 · /nunchi로 켜면 이 세션을 분석합니다</Text>
      return (
        <Box flexDirection="column">
          <Text bold>눈치</Text>
          {line}
        </Box>
      )
    }
    return (
      <Box flexDirection="column">
        <Text>
          <Text bold>눈치</Text>
          <Text dimColor> · #{v.basis} 기준</Text>
          {rebuilding ? <Text color="yellow">  {v.basis <= 1 ? '흐름 처음부터 만드는 중' : '밀린 턴 반영 중'} #{v.latest}/#{v.total} {dots(v.tick)}</Text>
            : busy ? <Text color="yellow">  {dots(v.tick, v.state)}</Text>
            : v.state === 'failed' ? <Text color="red">  분석 실패 · {v.error}</Text> : null}
        </Text>
        <Text> </Text>
        <Text><Text bold>에이전트가 묻는 것 </Text><Text color={v.askCount ? 'yellow' : 'green'}>{v.askCount ? String(v.askCount) : '없음'}</Text></Text>
        {v.asks.map(a => (
          <Box flexDirection="column">
            <Text><Text color="yellow" bold> {a.n} </Text>{cut(a.summary, cols - 12)}<Text dimColor> #{a.turn}{a.stale ? '부터 답 없음' : ''}{a.partial ? ' · 일부 답함' : ''}</Text></Text>
            <Text dimColor>   “{cut(a.quote, cols - 6)}”</Text>
          </Box>
        ))}
        {v.askCount > v.asks.length ? <Text dimColor>   … {v.askCount - v.asks.length}개 더 · 관제에서</Text> : null}
        {v.blanketClosed ? <Text dimColor>   통째 승인으로 닫은 것 {v.blanketClosed}</Text> : null}
        <Text> </Text>
        <Text bold>지금까지</Text>
        <Text><Text dimColor> 목표</Text><Text dimColor>{v.goalTurn ? `  #${v.goalTurn}부터` : ''}</Text></Text>
        {wrap(v.goal, cols - 4, 3).map(line => <Text>   {line}</Text>)}
        {v.decisions.length ? <Text dimColor> 정한 것</Text> : null}
        {v.decisions.map(d => wrap('✔ ' + d, cols - 9, 2).map((line, k) => <Text>   {k ? '  ' : ''}{line}</Text>))}
        {v.recent ? <Text dimColor> 방금</Text> : null}
        {v.recent ? wrap(v.recent, cols - 4, 3).map(line => <Text>   {line}</Text>) : null}
        <Text> </Text>
        <Text><Text bold>남은 것 </Text><Text color={v.leftCount ? 'yellow' : 'green'}>{v.leftCount ? String(v.leftCount) : '없음'}</Text><Text dimColor> 내 요청 중</Text></Text>
        {v.left.map(x => (
          <Text><Text color="yellow"> {x.mark} </Text>{cut(x.summary + (x.note ? ' — ' + x.note : ''), cols - 8)}<Text dimColor> #{x.turn}</Text></Text>
        ))}
        {v.terms.length ? <Text> </Text> : null}
        {v.terms.length ? <Text><Text bold>번호 풀이</Text><Text dimColor>  이번 응답 · 문서 원문</Text></Text> : null}
        {v.terms.map(x => (
          <Box flexDirection="column">
            <Text color="yellow"> {x.id}</Text>
            {(x.means.length ? x.means.slice(0, 2) : ['문서에 없음']).map((m, k) =>
              wrap((x.means.length > 1 ? '①②'[k] + ' ' : '') + m, cols - 4, 2).map(line =>
                <Text dimColor={!x.means.length}>   {line}</Text>))}
          </Box>
        ))}
        {v.termsMore ? <Text dimColor>   … {v.termsMore}개 더 · 관제에서</Text> : null}
        <Text dimColor>자세히는 관제</Text>
      </Box>
    )
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    // 패널이 옆이든 입력창 위든 그려지고 있으면 띠는 두지 않는다 (겹쳐 보이지 않게). 패널은 1초마다 다시 그려진다
    if ((await $.clock.now()) - paneDrawnAt < 3000) return next(e)
    // 좁은 창에서 시작해 패널이 기다리는 중인데 창이 넓어졌으면 다시 연다 (관제 확인 2026-11-12: 넓혀도 저절로 붙지 않음)
    const v = await read($, view)
    if ((e.viewport?.columns ?? 0) >= 110 && enabled(v)) {   // 켜지 않은 세션에서는 열지 않는다 (요구 이력 53)
      const mine = (await $.ui.panes()).find(x => x.id === PANE)
      if (!mine || !mine.isPlaced) void openPane($)
    }
    const busy = v.state === 'running' || v.state === 'queued'
    if (!v.goal && !busy) return next(e)
    if (!busy && v.leftCount === 0 && !v.goal) return next(e)
    const { Text } = $.ui.resolve(e)
    return (
      <Text>
        <Text bold>눈치 </Text>
        <Text>목표: {cut(v.goal, Math.max(10, (e.props.bodyColumns ?? 80) - 52))}</Text>
        <Text color={v.askCount ? 'yellow' : 'green'}> · 묻는 것 {v.askCount}</Text>
        <Text color={v.leftCount ? 'yellow' : 'green'}> · 남은 것 {v.leftCount}</Text>
        {busy ? <Text color="yellow"> · {dots(v.tick, v.state)}</Text> : <Text dimColor> · #{v.basis} 기준</Text>}
      </Text>
    )
  })
}
