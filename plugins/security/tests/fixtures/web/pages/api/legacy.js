export default async function handler(req, res) {
  const upstream = await fetch(req.query.target)
  res.status(200).json(await upstream.json())
}
