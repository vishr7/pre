// Server-only Gemini transport. API credentials never enter the browser bundle.
export async function structured_call({ prompt, schema, validate }, { fetchImpl = fetch, env = process.env } = {}) {
  const key = env.GEMINI_API_KEY;
  const model = env.GEMINI_MODEL?.replace(/^models\//, '');
  if (!key || !model) throw new Error('AI repair needs GEMINI_API_KEY and GEMINI_MODEL in .env. Restart the dev server after setting them.');
  let feedback = '';
  for (let attempt = 0; attempt < 3; attempt++) {
    const response = await fetchImpl(`https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'x-goog-api-key': key },
      body: JSON.stringify({ contents: [{ role: 'user', parts: [{ text: prompt + feedback }] }],
        generationConfig: { responseMimeType: 'application/json', responseJsonSchema: schema } }),
      signal: AbortSignal.timeout(30000),
    });
    if (!response.ok) throw new Error(`AI repair service returned HTTP ${response.status}. Check the configured Gemini model and API access.`);
    const result = await response.json();
    try {
      const text = result.candidates?.[0]?.content?.parts?.filter(part => !part.thought).map(part => part.text || '').join('');
      return validate(JSON.parse(text || '{}'));
    } catch (error) {
      if (attempt === 2) throw new Error(`AI could not produce a safe targeted fix: ${error.message}`);
      feedback = `\nYour previous response failed validation: ${error.message}. Try again using exact, unique source quotes and minimal changes.`;
    }
  }
}
