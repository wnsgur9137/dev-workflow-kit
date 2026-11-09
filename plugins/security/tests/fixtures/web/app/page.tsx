export default function Page({ html }) {
  const key = process.env.NEXT_PUBLIC_API_SECRET
  return <div data-k={key} dangerouslySetInnerHTML={{ __html: html }} />
}
