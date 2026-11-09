// 양성: Next.js 공식 예시 형태의 searchParams 구조 분해 → fetch (SSRF), 인증 없음
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const res = await fetch(searchParams.get('url')!)
  return Response.json(await res.json())
}
