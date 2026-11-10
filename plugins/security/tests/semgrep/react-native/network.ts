import axios from 'axios'

export async function load() {
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
}
