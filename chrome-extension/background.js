chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "extractPeople") {
    handleExtractPeople(request.data).then(sendResponse).catch(err => {
      sendResponse({ error: err.message });
    });
    return true;
  }

  if (request.action === "submitToSupabase") {
    handleSubmitToSupabase(request.data).then(sendResponse).catch(err => {
      sendResponse({ error: err.message });
    });
    return true;
  }
});

async function handleExtractPeople({ text, url, title }) {
  const { apiKey } = await chrome.storage.sync.get("apiKey");
  if (!apiKey) {
    throw new Error("Anthropic API key not configured. Open extension settings.");
  }

  const prompt = `Analyze the following web page content and extract all people mentioned. For each person, provide their name, title/role (if mentioned), organization (if mentioned), email address (if found on the page), LinkedIn profile URL (if found on the page), and a personalization-ready context.

The "context" field is the most important part of this extraction — it will be used to write personalized outreach messages to these individuals. Follow these rules for context:

1. BEST: If the person is quoted or paraphrased on the page (something they said, a viewpoint they shared, a topic they presented on), use that. Include the actual quote or a close paraphrase. This is the most valuable context for personalization.
2. FALLBACK: If there is no quote or statement from the person, describe the event or setting where they appear — include the conference/event name, date, location, and their role (e.g. "Speaker at TechCrunch Disrupt 2025, San Francisco, Oct 14-16" or "Panelist on 'AI in Healthcare' at HIMSS 2025, Chicago").
3. Be specific and detailed. Generic context like "mentioned on the page" is useless. Always extract the most concrete, personalizable detail available.

Return ONLY a valid JSON array with no additional text. Each element should have these fields:
- "name": the person's full name
- "title": their title or role (empty string if unknown)
- "organization": their organization (empty string if unknown)
- "email": their email address if explicitly present on the page (empty string if not found)
- "linkedin": their LinkedIn profile URL if explicitly present on the page (empty string if not found)
- "context": the personalization-ready context as described above

Only include email and LinkedIn if they are actually present on the page. Do not guess or fabricate them.

If no people are found, return an empty array [].

Page title: ${title}
Page URL: ${url}

Page content:
${text}`;

  const response = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
      "anthropic-dangerous-direct-browser-access": "true"
    },
    body: JSON.stringify({
      model: "claude-sonnet-4-5-20250929",
      max_tokens: 16384,
      messages: [
        { role: "user", content: prompt }
      ]
    })
  });

  if (!response.ok) {
    const errBody = await response.text();
    throw new Error(`Claude API error (${response.status}): ${errBody}`);
  }

  const result = await response.json();
  const content = result.content[0].text;
  const stopReason = result.stop_reason;

  // Extract JSON from the response (handle markdown code blocks and surrounding text)
  let jsonStr = content.trim();

  // Strip opening code fence
  jsonStr = jsonStr.replace(/^```(?:json)?\s*/, "");
  // Strip closing code fence if present
  jsonStr = jsonStr.replace(/```\s*$/, "");
  jsonStr = jsonStr.trim();

  // Find the start of the JSON array
  const arrayStart = jsonStr.indexOf("[");
  if (arrayStart !== -1) {
    jsonStr = jsonStr.substring(arrayStart);
  }

  // If response was truncated (hit max_tokens), repair the JSON
  if (stopReason === "max_tokens" || !jsonStr.endsWith("]")) {
    // Remove any trailing incomplete object
    const lastComplete = jsonStr.lastIndexOf("}");
    if (lastComplete !== -1) {
      jsonStr = jsonStr.substring(0, lastComplete + 1) + "]";
    }
  }

  const people = JSON.parse(jsonStr);
  return { people };
}

async function handleSubmitToSupabase({ people, sourceUrl, forValue }) {
  const { supabaseUrl, supabaseAnonKey } = await chrome.storage.sync.get(["supabaseUrl", "supabaseAnonKey"]);
  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error("Supabase not configured. Open extension settings.");
  }

  const endpoint = `${supabaseUrl}/rest/v1/people`;
  let insertedRows = 0;
  let skippedRows = 0;

  for (const p of people) {
    const row = {
      name: p.name,
      title: p.title || "",
      organization: p.organization || "",
      email: p.email || "",
      linkedin: p.linkedin || "",
      context: p.context || "",
      source_url: sourceUrl,
      for_tag: forValue || "other",
      status: "discovered"
    };

    const resp = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "apikey": supabaseAnonKey,
        "Authorization": `Bearer ${supabaseAnonKey}`,
        "Prefer": "return=minimal"
      },
      body: JSON.stringify(row)
    });

    if (resp.ok) {
      insertedRows++;
    } else if (resp.status === 409) {
      // Duplicate — expected for name_normalized + org_normalized unique constraint
      skippedRows++;
    } else {
      const errBody = await resp.text();
      throw new Error(`Supabase error (${resp.status}): ${errBody}`);
    }
  }

  return { success: true, insertedRows, skippedRows };
}
