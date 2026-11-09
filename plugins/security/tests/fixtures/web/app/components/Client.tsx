'use client'
// 음성 사례: 클라이언트 컴포넌트의 fetch 는 SSRF 가 아니다
import { useRouter } from 'next/router'

export function Client() {
  const router = useRouter()
  fetch('/api/items/' + router.query.id)
  return null
}
