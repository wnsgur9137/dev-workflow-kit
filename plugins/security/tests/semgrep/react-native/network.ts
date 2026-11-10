import axios from 'axios'

export async function load(api: any, cache: any, id: string, base: string, url: string, map: any, params: any, storage: any, router: any, i18n: any, client: any, h: any) {
  // ruleid: insecure-http-url
  await fetch('http://api.example.com/v1/items')
  // ruleid: insecure-http-url
  await fetch("http://localhost.evil.com/x", { method: 'POST' })
  // ruleid: insecure-http-url
  await axios.get('http://10.0.2.20/x')
  // ruleid: insecure-http-url
  const client = axios.create({ timeout: 1000, baseURL: 'http://api.example.com' })
  // ruleid: insecure-http-url
  const ws = new WebSocket('ws://chat.example.com/socket')
  // ok: insecure-http-url
  await fetch('http://localhost:8081/status')
  // ok: insecure-http-url
  await fetch('http://10.0.2.2:3000/x')
  // ok: insecure-http-url
  await axios.post('https://api.example.com/v1', {})
  // ok: insecure-http-url
  const local = new WebSocket('ws://127.0.0.1:8080')
  // ruleid: insecure-http-url
  await fetch(`http://api.example.com/${id}`)
  // ruleid: insecure-http-url
  await axios({ method: 'get', url: 'http://api.example.com/x' })
  // ruleid: insecure-http-url
  await api.get('http://api.example.com/x')
  // ok: insecure-http-url
  await fetch(`http://localhost:8081/${id}`)
  // ok: insecure-http-url
  await fetch(`${base}/v1`)
  // ok: insecure-http-url
  await api.get(url)
  // ok: insecure-http-url
  await cache.set('http://api.example.com/x', 1)
  // 3차 리뷰 S3 — 같은 이름 메서드를 가진 Map·URLSearchParams·캐시·저장소·라우터 수신자는 제외
  // ok: insecure-http-url
  await cache.get('http://api.example.com')
  // ok: insecure-http-url
  map.delete('http://api.example.com/x')
  // ok: insecure-http-url
  params.get('http://api.example.com/x')
  // ok: insecure-http-url
  new URL(url).searchParams.get("http://api.example.com/x")
  // ok: insecure-http-url
  storage.delete('http://api.example.com/x')
  // ok: insecure-http-url
  i18n.get('http://api.example.com/x')
  // ok: insecure-http-url
  router.get('http://api.example.com/x', h)
  // ruleid: insecure-http-url
  await client.post('http://api.example.com/x', {})
  // ruleid: insecure-http-url
  await this.httpClient.get('http://api.example.com/x')
}
