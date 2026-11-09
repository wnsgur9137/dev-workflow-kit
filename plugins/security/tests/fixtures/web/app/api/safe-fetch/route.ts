// 음성 사례: SSRF·공개 변수로 잡히면 안 되는 형태 (PR #24 리뷰)
import axios from 'axios'
import { auth } from '@/auth'

const config = new Map([['upstream', 'https://upstream.example.com/']])

export async function GET(request: Request) {
  const session = await auth()
  if (!session) return new Response(null, { status: 401 })
  const id = new URL(request.url).searchParams.get('id')
  const fixed = await axios.get('https://fixed.example.com/')
  const upstream = await fetch(config.get('upstream')!)
  const item = await fetch(`https://api.example.com/items/${id}`)
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  return Response.json({ fixed: fixed.data, up: await upstream.json(), item: await item.json(), key })
}
