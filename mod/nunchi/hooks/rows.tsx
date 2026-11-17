// 패널 본문 줄 (요구 이력 75·77). 훅 모듈이 줄바꿈·자르기·링크 조각까지 끝낸 줄을 만들고, 그리기는 이것 하나로 한다.
export type Span = { t: string; href?: string; b?: 1; d?: 1; c?: string }
export type Row = { s: Span[] } | { more: string; label: string } | { btns: { k: string; label: string }[] }

export function buttonKey(k: string): string {
  return k === 'collapse' ? 'collapse' : 'more-' + k
}

export function drawRows(rows: Row[], el: any, press: (k: string) => void) {
  const { Box, Text, Button, Link } = el
  return (
    <Box flexDirection="column">
      {rows.map(r => 'btns' in r
        ? <Box flexDirection="row">{r.btns.map((b, i) => <Box flexDirection="row"><Text>{i ? ' · ' : ''}</Text><Button key={b.k} plain dimColor onPress={() => press(b.k)}>{b.label}</Button></Box>)}</Box>
        : 'more' in r
        ? <Box flexDirection="row"><Text>{r.more === 'collapse' ? '' : '   '}</Text><Button key={buttonKey(r.more)} plain dimColor onPress={() => press(r.more)}>{r.label}</Button></Box>
        : <Text>{r.s.map(x => x.href ? <Link href={x.href}>{x.t}</Link>
            : (x.b || x.d || x.c) ? <Text {...(x.b ? { bold: true } : {})} {...(x.d ? { dimColor: true } : {})} {...(x.c ? { color: x.c } : {})}>{x.t}</Text>
            : x.t)}</Text>)}
    </Box>
  )
}
