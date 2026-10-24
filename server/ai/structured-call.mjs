// Server-only Gemini transport. API credentials never enter the browser bundle.
// Optional `thinking` (e.g. {thinkingLevel:'low'}) speeds up small, well-specified tasks; omitted by default.
// Optional `timeoutMs` per attempt (default 30s) lets long tasks such as full-paper review finish instead of retrying.
export async function structured_call({ prompt, schema, validate, images = [], thinking, timeoutMs = 30000 }, { fetchImpl = fetch, env = process.env, sleep = ms => new Promise(resolve => setTimeout(resolve, ms)) } = {}) {
  const key = env.GEMINI_API_KEY;
  const model = env.GEMINI_MODEL?.replace(/^models\//, '');
  if (!key || !model) throw new Error('AI generation needs GEMINI_API_KEY and GEMINI_MODEL in .env. Restart the dev server after setting them.');
  let feedback = '';
  for (let attempt = 0; attempt < 3; attempt++) {
    let response;
    try { response = await fetchImpl(`https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'x-goog-api-key': key },
      body: JSON.stringify({ contents: [{ role: 'user', parts: [{ text: prompt + feedback }, ...images.map(image => ({inlineData: image}))] }],
        generationConfig: { responseMimeType: 'application/json', responseJsonSchema: schema, ...(thinking ? { thinkingConfig: thinking } : {}) } }),
      signal: AbortSignal.timeout(timeoutMs),
    });
    } catch {
      if (attempt === 2) throw new Error('Could not reach Gemini after 3 attempts. Check your connection and try again. Your cell is unchanged.');
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
