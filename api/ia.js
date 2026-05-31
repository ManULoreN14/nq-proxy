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
    // — Si el cliente pide un modelo concreto, respetarlo
    // — Si el mensaje contiene imágenes → Sonnet (capacidad visual, ~8s)
    // — Solo texto → Haiku (muy rápido, ~2s, cabe en los 10s de Vercel free)
    const tieneImagen = Array.isArray(messages) && messages.some(m =>
      Array.isArray(m.content) && m.content.some(c => c.type === 'image')
    );

    const model = requestedModel ||
      (tieneImagen ? 'claude-sonnet-4-6' : 'claude-haiku-4-5-20251001');

    // max_tokens: límite según modelo para no exceder el timeout
    // Haiku: hasta 2000 tokens de sobra en <3s
    // Sonnet con imagen: 1500 máx para intentar caber en 10s
    const maxTok = max_tokens || (tieneImagen ? 1500 : 2000);

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

    // Si Anthropic devuelve error HTTP, capturarlo como JSON legible
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
