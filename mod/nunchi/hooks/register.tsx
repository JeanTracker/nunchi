// 눈치 mod (REQUIREMENTS R17, SCREEN §11, BUILD_PLAN §4.4)
// 분석기(nunchi-engine)가 쓴 분석 결과(<관제 홈>/sessions/<세션 ID>/analysis.json)를 읽기만 하고, 세션 옆 패널(좁으면 입력창 위 한 줄)에 보인다.
// 분석은 하지 않는다. 분석 상태는 같은 폴더의 analysis_status.json에서 읽는다.
// /nunchi로 켜면 세션 폴더에 want를 남긴다. 그러면 응답이 끝날 때마다 분석기가 이 세션을 분석한다 (요구 이력 53).
// 켜지 않았고 분석 결과도 없는 세션에서는 패널을 저절로 열지 않는다.
import { atom, read, update } from 'claude-code'
import type { Register, EngineInterface } from 'claude-code'

import type { View, Left } from '../types'

const PANE = 'nunchi'
const EMPTY: View = {
  basis: 0, total: 0, latest: 0, state: 'none', asks: [], askCount: 0, blanketClosed: 0,
  digest: '', digestTurn: 0, goal: '', goalTurn: 0, decisions: [], recent: '', left: [], leftCount: 0, ratio: 0.4, tick: 0,
  terms: [], termsMore: 0, on: false, error: '', control: false, behind: 0,
}
const view = atom({ plugin: 'nunchi', key: 'view' } as const, EMPTY, { shape: 'view-8' })

const SHOWN = 3
const MAX_RATIO = 0.45   // Claude Code가 옆 패널에 허락하는 폭
let paneDrawnAt = 0      // 패널이 마지막으로 그려진 때. 패널이 보이는 동안은 띠를 두지 않는다
let askedColumns = 0     // 마지막으로 요청한 옆 패널 폭
let opened = false       // 이 세션에서 패널을 한 번 열었는지 (켠 세션·분석된 세션만 저절로 연다)

async function controlHome($: EngineInterface): Promise<string> {
  return (await $.env.get('CONTROL_TUI_HOME')) || ((await $.env.get('HOME')) || '') + '/.claude-control'
}

async function sessionId($: EngineInterface): Promise<string> {
  // 시험용: NUNCHI_MOD_SESSION을 주면 다른 세션의 분석을 본다 (실제 사용에서는 비워 둔다)
  return (await $.env.get('NUNCHI_MOD_SESSION')) || (await $.session.id())
}

async function sessionDir($: EngineInterface): Promise<string> {
  return (await controlHome($)) + '/sessions/' + (await sessionId($))
}

// 관제 패널을 앞으로 가져온다 (요구 이력 56). 관제 화면은 지웠지만(요구 이력 70) 살아 있는 관제(control.json)가 있을 때만 쓰이므로 남겨 둔다
const FOCUS_SCRIPT = `on run argv
  set targetId to item 1 of argv
  tell application "iTerm2"
    repeat with w in windows
      repeat with t in tabs of w
        repeat with s in sessions of t
          if (id of s) is targetId then
            select w
            tell t to select
            tell s to select
            activate
            return "ok"
          end if
        end repeat
      end repeat
    end repeat
  end tell
  return "missing"
end run`

/** 관제로 (요구 이력 56, BUILD_PLAN §4.8): 이 세션으로 와 달라는 요청(goto)을 남기고 관제 패널을 앞으로 */
export async function goControl($: EngineInterface): Promise<string> {
  const home = await controlHome($)
  const ctl = await readJson($, home + '/control.json')
  if (!ctl?.iterm_session_id) return '관제가 꺼져 있습니다. 다른 패널에서 nunchi로 켜세요.'
  const alive = await $.process.run(['kill', '-0', String(ctl.pid ?? '')]).catch(() => null)
  if (!alive || alive.exitCode !== 0) return '관제가 꺼져 있습니다. 다른 패널에서 nunchi로 켜세요.'
  await $.fs.write(home + '/goto', JSON.stringify({ session: await sessionId($), at: (await $.clock.now()) / 1000 }) + '\n')
  const r = await $.process.run(['osascript', '-e', FOCUS_SCRIPT, String(ctl.iterm_session_id)]).catch(() => null)
  if (!r || r.exitCode !== 0 || !String(r.stdout).includes('ok')) return '관제 패널을 찾지 못했습니다. ⌘숫자로 옮겨 가세요.'
  return ''
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
    else if (r.state === 'in_progress') left.push({ mark: '◐', summary: one(r.summary), note: '진행 중', turn: r.by_turn ?? r.from_turn ?? 0 })   // 요구 이력 66
  }
  // 도구 실패(△)는 보이지 않는다: 도구 사용은 모으지도 보이지도 않는다 (요구 이력 48)
  const decisions = steps.filter((s: any) => s.label === '확정').slice(-SHOWN)
    .map((s: any) => one(s.title || s.decision || s.summary, 80))
  const last = steps.length ? steps[steps.length - 1] : null
  // 처음부터 이 턴까지 한 덩어리 정리: 분석기가 턴마다 써 둔 digest 중 마지막 것 (요구 이력 57, 추정)
  const digested = (flow.steps ?? []).filter((s: any) => s.digest).pop()
  return {
    ...base,
    basis,
    total: analysis.last_turn ?? 0,
    state: status?.state ?? 'idle',
    asks,
    askCount: open.length,
    blanketClosed: (flow.asks ?? []).filter((a: any) => a.state === 'answered' && a.by_blanket).length,
    digest: digested && digested.index > 1 ? one(digested.digest, 240) : '',
    digestTurn: digested?.index ?? 0,
    goal: one(flow.current_goal?.text ?? analysis.current_goal ?? ''),
    goalTurn: flow.current_goal?.turn ?? 0,
    decisions,
    recent: one(last?.agent_summary ?? '', 240),
    left: left.slice(0, SHOWN),
    leftCount: left.length,
  }
}

// 넓게 그려지는 기호(… → ◆ ● ① ⚠ 등) 바로 뒤에 글자가 붙으면 한 칸 띄운다 (요구 이력 58).
// iTerm이 영문 외 글자를 Noto Sans CJK KR로 그리면 이 기호들이 한 칸의 약 1.7배로 그려져 뒤 글자를 덮는다.
// 범위는 SCREEN §8 기호 겹침 실측에서 정했다(BUILD_PLAN §4.9). 괘선(─ │ ┊ └)은 터미널이 직접 그려 넣지 않는다.
const WIDE = /[\u00a7\u00a9\u00b1\u00b6\u00bc-\u00be\u00d7\u00f7\u2010\u2014-\u2016\u2020\u2021\u2025-\u2027\u2030\u2035\u203b\u2042\u2047-\u2049\u2051\u2100-\u214f\u2190-\u23ff\u2460-\u24ff\u25a0-\u27bf]/
export function gap(text: string): string {
  return text.replace(new RegExp(WIDE.source + '(?=[^\\s])', 'g'), m => m + ' ')
}

// 글 속 링크 (요구 이력 60): 맨 주소(https://…)와 마크다운 [이름](주소). 줄을 감싸거나 잘라도 조각마다 원래 주소를 들고 간다.
export type Piece = { t: string; href?: string }
const URL_RE = /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[A-Za-z0-9\-._~:\/?#@!$&*+,;=%]+)/g   // 맨 주소는 ASCII 주소 글자만 (뒤 한글 조사·백틱이 붙지 않게)
export function pieces(text: string): Piece[] {
  const out: Piece[] = []
  let at = 0
  for (const m of text.matchAll(URL_RE)) {
    let url: string = m[2] ?? m[3] ?? ""
    let label: string = m[1] ?? url
    if (!m[2]) {   // 맨 주소 끝의 문장 부호는 주소가 아니다
      const trail = /[.,;:!?*]+$/.exec(url)
      if (trail) { url = url.slice(0, -trail[0].length); label = url }
    }
    if (m.index! > at) out.push({ t: gap(text.slice(at, m.index)) })
    out.push({ t: label, href: url })
    at = m.index! + (m[2] ? m[0].length : url.length)
  }
  if (at < text.length) out.push({ t: gap(text.slice(at)) })
  return out
}
const flat = (line: Piece[]) => line.map(p => p.t).join('')
function push(line: Piece[], t: string, href?: string) {
  const last = line[line.length - 1]
  if (last && last.href === href) last.t += t
  else line.push(href ? { t, href } : { t })
}

/** 칸 수(한글 2칸)로 자른다. 대화 정리는 턴마다 한 줄 (SCREEN §11) */
function cutParts(text: string, cols: number): Piece[] {
  const line: Piece[] = []
  let used = 0
  for (const p of pieces(text)) {
    for (const ch of p.t) {
      const w = /[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe30-\ufe4f\uff00-\uff60\uffe0-\uffe6]/.test(ch) ? 2 : 1
      if (used + w > cols - 1) { push(line, '…'); return line }
      push(line, ch, p.href)
      used += w
    }
  }
  return line
}
function cut(text: string, cols: number): string {
  return flat(cutParts(text, cols))
}

/** 칸 수(한글 2칸)에 맞춰 여러 줄로 감싼다. 넘치면 마지막 줄 끝을 …로 (요구 이력 50) */
function wrapParts(text: string, cols: number, maxLines: number): Piece[][] {
  const wide = (ch: string) => /[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe30-\ufe4f\uff00-\uff60\uffe0-\uffe6\u2714]/.test(ch) ? 2 : 1
  const words: Piece[] = []   // 링크는 한 낱말 (빈칸이 없다)
  for (const p of pieces(text)) {
    if (p.href) words.push(p)
    else for (const w of p.t.split(/(\s+)/)) if (w) words.push({ t: w })
  }
  const lines: Piece[][] = []
  let cur: Piece[] = []
  let used = 0
  const blank = () => !flat(cur).trim()
  const close = () => {
    const last = cur[cur.length - 1]
    if (last && !last.href) last.t = last.t.trimEnd()
    lines.push(cur.filter(p => p.t)); cur = []; used = 0
  }
  for (const word of words) {
    const w = [...word.t].reduce((n, ch) => n + wide(ch), 0)
    if (used + w > cols && !blank()) {
      close()
      if (/^\s+$/.test(word.t)) continue
    }
    if (w > cols) {   // 한 낱말이 한 줄보다 길면 글자 단위로 자른다 (링크 조각은 같은 주소)
      for (const ch of word.t) {
        if (used + wide(ch) > cols) { lines.push(cur); cur = []; used = 0 }
        push(cur, ch, word.href)
        used += wide(ch)
      }
      continue
    }
    push(cur, word.t, word.href)
    used += w
  }
  if (!blank()) close()
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines)
    const last = kept[maxLines - 1] ?? []
    const room = cols - 2
    const trimmed: Piece[] = []
    let n = 0
    for (const p of last) for (const ch of p.t) {
      if (n + wide(ch) > room - 1) break
      push(trimmed, ch, p.href); n += wide(ch)
    }
    push(trimmed, ' …')
    kept[maxLines - 1] = trimmed
    return kept
  }
  return lines
}
function wrap(text: string, cols: number, maxLines: number): string[] {
  return wrapParts(text, cols, maxLines).map(flat)
}

function dots(tick: number, state = 'running'): string {
  return (state === 'queued' ? '분석 대기' : '분석 중') + ['.', '..', '...'][tick % 3]
}

async function openPane($: EngineInterface) {
  opened = true
  return $.ui.open({ id: PANE, title: '눈치' })
}

// 분석이 본 마지막 응답 뒤에 끝난 응답 수 (요구 이력 65). 훅이 모든 세션의 Stop을 events.jsonl에 남긴다.
// 한 턴 안에서 이어 끝난 응답도 센다(그것도 아직 분석에 없는 내용, 요구 이력 64).
// 파일에는 도구 기록도 쌓여 일하는 동안 매초 커지므로, 처음·이 세션 응답이 끝난 뒤 잠깐·분석 기준이 바뀔 때만 읽는다.
const RECOUNT_MS = 5000      // 응답이 끝난 뒤 훅이 Stop을 적을 때까지 기다리는 동안 다시 센다
let countedSince: string | null = null
let recountUntil = 0
let behindCount = 0
export function answerEnded(now: number) { recountUntil = now + RECOUNT_MS }
export async function answersAfter($: EngineInterface, dir: string, since: string): Promise<number> {
  const now = await $.clock.now()
  if (since === countedSince && now > recountUntil) return behindCount
  countedSince = since
  try {
    const stops = String(await $.fs.read(dir + '/events.jsonl')).split('\n').filter(l => l.includes('"Stop"')).map(l => {
      try { const e = JSON.parse(l); return e.event === 'Stop' ? String(e.ts ?? '') : '' } catch { return '' }
    })
    behindCount = since ? stops.filter(ts => ts && ts > since).length : 0
  } catch {
    behindCount = 0
  }
  return behindCount
}

async function refresh($: EngineInterface) {
  const dir = await sessionDir($)
  const home = await controlHome($)
  const [analysis, status, config, gloss, want, ctl] = await Promise.all([
    readJson($, dir + '/analysis.json'), readJson($, dir + '/analysis_status.json'),
    readJson($, home + '/config.json'), readJson($, dir + '/glossary.json'),
    readJson($, dir + '/want'), readJson($, home + '/control.json'),
  ])
  const ratio = Math.min(MAX_RATIO, Math.max(0.2, Number(config?.mod_width_ratio) || 0.4))
  const behind = await answersAfter($, dir, String(analysis?.source_ts ?? ''))
  await update($, view, old => ({ ...buildView(analysis, status, (old?.tick ?? 0) + 1, ratio, gloss, want !== null),
    control: !!ctl?.iterm_session_id, behind }))
  if (!opened && enabled(await read($, view))) void openPane($)   // 켠 세션이나 관제가 분석한 세션만 저절로 연다
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'nunchi', description: '눈치 켜기: 이 세션을 분석하고 패널을 연다' })
    await refresh($)
    $.clock.every(1000, () => { void refresh($) })   // 분석 파일이 바뀌면 다시 그린다. '분석 중' 점도 1초마다
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (!(e as any).agentId) answerEnded(await $.clock.now())   // 이 세션 응답이 끝남: 밀린 응답 수를 다시 센다 (하위 에이전트 끝은 빼고)
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
    return { text: '눈치를 켰습니다. 다음 응답이 끝나면 이 세션을 분석합니다.' + where }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button, Link } = $.ui.resolve(e)
    // 조각을 글자와 링크로 (요구 이력 60): 터미널은 OSC 8 링크로 그려 클릭하면 열린다
    const ln = (line: Piece[]) => line.map(p => p.href ? <Link href={p.href}>{p.t}</Link> : p.t)
    const v = await read($, view)
    const cols = Math.max(20, e.props.bodyColumns ?? 50)
    const toControl = async () => {
      const problem = await goControl($)
      if (problem) $.ui.toast(problem)
    }
    const tail = v.control
      ? <Box flexDirection="row"><Button key="control" hotkey="1" onPress={() => { void toControl() }}>관제로</Button><Text dimColor>  또는 ⌘숫자</Text></Box>
      : null   // 관제 화면을 지워(요구 이력 70) 켜라고 하지 않는다
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
          {v.behind > 0 && !busy ? <Text color="yellow"> · 응답 {v.behind}개 밀림</Text> : null}
          {rebuilding ? <Text color="yellow">  {v.basis <= 1 ? '흐름 처음부터 만드는 중' : '밀린 턴 반영 중'} #{v.latest}/#{v.total} {dots(v.tick)}</Text>
            : busy ? <Text color="yellow">  {dots(v.tick, v.state)}</Text>
            : v.state === 'failed' ? <Text color="red">  분석 실패 · {v.error}</Text>
            : !v.on ? <Text color="yellow">  자동 분석 꺼짐 · /nunchi로 켜기</Text> : null}
        </Text>
        <Text> </Text>
        <Text><Text bold>에이전트가 묻는 것 </Text><Text color={v.askCount ? 'yellow' : 'green'}>{v.askCount ? String(v.askCount) : '없음'}</Text></Text>
        {v.asks.map(a => (
          <Box flexDirection="column">
            <Text><Text color="yellow" bold> {a.n} </Text>{ln(cutParts(a.summary, cols - 12))}<Text dimColor> #{a.turn}{a.stale ? '부터 답 없음' : ''}{a.partial ? ' · 일부 답함' : ''}</Text></Text>
            <Text dimColor>   “{ln(cutParts(a.quote, cols - 6))}”</Text>
          </Box>
        ))}
        {v.askCount > v.asks.length ? <Text dimColor>   … {v.askCount - v.asks.length}개 더</Text> : null}
        {v.blanketClosed ? <Text dimColor>   통째 승인으로 닫은 것 {v.blanketClosed}</Text> : null}
        <Text> </Text>
        <Text bold>지금까지</Text>
        {v.digest ? <Text dimColor> 흐름  #1–#{v.digestTurn}</Text> : null}
        {v.digest ? wrapParts(v.digest, cols - 4, 3).map(line => <Text dimColor>   {ln(line)}</Text>) : null}
        <Text><Text dimColor>{v.digest ? ' 지금 목표' : ' 목표'}</Text><Text dimColor>{v.goalTurn ? `  #${v.goalTurn}부터` : ''}</Text></Text>
        {wrapParts(v.goal, cols - 4, 3).map(line => <Text>   {ln(line)}</Text>)}
        {v.decisions.length ? <Text dimColor> 정한 것</Text> : null}
        {v.decisions.map(d => wrapParts('✔ ' + d, cols - 9, 2).map((line, k) => <Text>   {k ? '  ' : ''}{ln(line)}</Text>))}
        {v.recent ? <Text dimColor> 방금</Text> : null}
        {v.recent ? wrapParts(v.recent, cols - 4, 3).map(line => <Text>   {ln(line)}</Text>) : null}
        <Text> </Text>
        <Text><Text bold>남은 것 </Text><Text color={v.leftCount ? 'yellow' : 'green'}>{v.leftCount ? String(v.leftCount) : '없음'}</Text><Text dimColor> 내 요청 중</Text></Text>
        {v.left.map(x => (
          <Text><Text color="yellow"> {x.mark} </Text>{ln(cutParts(x.summary + (x.note ? ' — ' + x.note : ''), cols - 8))}<Text dimColor> #{x.turn}</Text></Text>
        ))}
        {v.leftCount > v.left.length ? <Text dimColor>   … {v.leftCount - v.left.length}개 더</Text> : null}
        {v.terms.length ? <Text> </Text> : null}
        {v.terms.length ? <Text><Text bold>번호 풀이</Text><Text dimColor>  이번 응답 · 문서 원문</Text></Text> : null}
        {v.terms.map(x => (
          <Box flexDirection="column">
            <Text color="yellow"> {x.id}</Text>
            {(x.means.length ? x.means.slice(0, 2) : ['문서에 없음']).map((m, k) =>
              wrapParts((x.means.length > 1 ? '①②'[k] + ' ' : '') + m, cols - 4, 2).map(line =>
                <Text dimColor={!x.means.length}>   {ln(line)}</Text>))}
          </Box>
        ))}
        {v.termsMore ? <Text dimColor>   … {v.termsMore}개 더</Text> : null}
        <Text> </Text>
        {tail}
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
        {!busy && !v.on ? <Text color="yellow"> · 분석 꺼짐</Text> : null}
      </Text>
    )
  })
}
