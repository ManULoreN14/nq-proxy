export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }
  try {
    const { messages, max_tokens, model: requestedModel } = req.body;

    // Selección dinámica de modelo:
    // — Con imagen → Sonnet (visión), max 1500 tokens para caber en 10s Vercel free
    // — Solo texto → Haiku (2-3s), max 3000 tokens — informe completo sin cortes
    const tieneImagen = Array.isArray(messages) && messages.some(m =>
      Array.isArray(m.content) && m.content.some(c => c.type === 'image')
    );

    const model = requestedModel ||
      (tieneImagen ? 'claude-sonnet-4-6' : 'claude-haiku-4-5-20251001');

    const maxTok = max_tokens || (tieneImagen ? 1500 : 3000);

    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': process.env.ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01'
      },
      body: JSON.stringify({
        model,
        max_tokens: maxTok,
        messages
      })
    });

    if (!response.ok) {
      const errText = await response.text();
      return res.status(response.status).json({
        error: `Anthropic API error ${response.status}`,
        detail: errText.slice(0, 500)
      });
    }

    const data = await response.json();
    return res.status(200).json(data);
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
}
