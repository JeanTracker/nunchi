// 패널 본문 줄 (요구 이력 75·77). 훅 모듈이 줄바꿈·자르기·링크 조각까지 끝낸 줄을 만들고, 그리기는 이것 하나로 한다.
export type Span = { t: string; href?: string; b?: 1; d?: 1; c?: string }
// btn: 덩어리 제목 줄 오른쪽의 흐린 버튼 (펼치기·줄이기, 요구 이력 88)
// btn.key·act가 없으면 글 펼치기(text-<k> · text:<k>). 프롬프트 복사는 key·act를 준다 (요구 이력 89)
export type Row = { s: Span[]; btn?: { k: string; label: string; key?: string; act?: string } } | { more: string; label: string }

export function buttonKey(k: string): string {
  return k === 'collapse' ? 'collapse' : 'more-' + k
}

function spans(s: Span[], Text: any, Link: any) {
  return s.map(x => x.href ? <Link href={x.href}>{x.t}</Link>
    : (x.b || x.d || x.c) ? <Text {...(x.b ? { bold: true } : {})} {...(x.d ? { dimColor: true } : {})} {...(x.c ? { color: x.c } : {})}>{x.t}</Text>
    : x.t)
}

export function drawRows(rows: Row[], el: any, press: (k: string, p?: any) => void) {
  const { Box, Text, Button, Link } = el
  return (
    <Box flexDirection="column">
      {rows.map(r => 'more' in r
        ? <Box flexDirection="row"><Text>{r.more === 'collapse' ? '' : '   '}</Text><Button key={buttonKey(r.more)} plain dimColor onPress={() => press(r.more)}>{r.label}</Button></Box>
        : r.btn
        ? <Box flexDirection="row" justifyContent="space-between"><Text>{spans(r.s, Text, Link)}</Text><Button key={r.btn.key ?? 'text-' + r.btn.k} plain dimColor onPress={(p: any) => press(r.btn!.act ?? 'text:' + r.btn!.k, p)}>{r.btn.label}</Button></Box>
        : <Text>{spans(r.s, Text, Link)}</Text>)}
    </Box>
  )
}
