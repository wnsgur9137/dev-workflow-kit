import { NextRequest } from 'next/server'

export async function GET(request: NextRequest) {
  const target = request.nextUrl.searchParams.get('url')
  const res = await fetch(target!)
  return Response.json(await res.json())
}
