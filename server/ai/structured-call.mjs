// Server-only Gemini transport. API credentials never enter the browser bundle.
export async function structured_call({ prompt, schema, validate, images = [] }, { fetchImpl = fetch, env = process.env, sleep = ms => new Promise(resolve => setTimeout(resolve, ms)) } = {}) {
  const key = env.GEMINI_API_KEY;
  const model = env.GEMINI_MODEL?.replace(/^models\//, '');
  if (!key || !model) throw new Error('AI generation needs GEMINI_API_KEY and GEMINI_MODEL in .env. Restart the dev server after setting them.');
  let feedback = '';
  const deadline = Date.now() + 105000;
  for (let attempt = 0; attempt < 3; attempt++) {
    const remaining = deadline - Date.now();
    if (remaining < 1000) throw new Error('Gemini took too long to respond. Try a smaller edit or one section at a time. Your source is unchanged.');
    let response;
    try { response = await fetchImpl(`https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'x-goog-api-key': key },
      body: JSON.stringify({ contents: [{ role: 'user', parts: [{ text: prompt + feedback }, ...images.map(image => ({inlineData: image}))] }],
        generationConfig: { responseMimeType: 'application/json', responseJsonSchema: schema } }),
      signal: AbortSignal.timeout(Math.min(90000, remaining)),
    });
    } catch (error) {
      const timedOut = error?.name === 'TimeoutError' || error?.name === 'AbortError';
      if (timedOut) throw new Error('Gemini took too long to generate this response. Try one section at a time or a smaller edit. Your source is unchanged.');
      if (attempt === 2) throw new Error('The server could not connect to Gemini after 3 attempts. Check the server network connection and try again. Your source is unchanged.');
      await sleep(1000 * 2 ** attempt);
      continue;
    }
    if (!response.ok) {
      const transient = [429, 500, 502, 503, 504].includes(response.status);
      if (transient && attempt < 2) {
        const retryAfter = response.headers?.get('retry-after');
        const seconds = Number(retryAfter);
        const requestedDelay = retryAfter ? (Number.isFinite(seconds) ? seconds * 1000 : Date.parse(retryAfter) - Date.now()) : 0;
        await sleep(Math.min(5000, Math.max(1000 * 2 ** attempt, Number.isFinite(requestedDelay) ? requestedDelay : 0)));
        continue;
      }
      if (transient) throw new Error(response.status === 429
        ? 'Gemini is rate-limited or out of quota. Please wait and try again; if it persists, check your Gemini quota. Your cell is unchanged.'
        : `Gemini is temporarily unavailable (HTTP ${response.status}) after 3 attempts. Please try again shortly. Your cell is unchanged.`);
      if ([401, 403].includes(response.status)) throw new Error('Gemini rejected API access. Check the server-side API key and model permissions.');
      throw new Error(`Gemini rejected the request (HTTP ${response.status}). Check the configured model and API configuration.`);
    }
    const result = await response.json();
    try {
      const text = result.candidates?.[0]?.content?.parts?.filter(part => !part.thought).map(part => part.text || '').join('');
      return validate(JSON.parse(text || '{}'));
    } catch (error) {
      if (attempt === 2) throw new Error(`AI could not produce a valid LaTeX suggestion: ${error.message}`);
      feedback = `\nYour previous response failed validation: ${error.message}. Try again using exact, unique source quotes and minimal changes.`;
    }
  }
}
