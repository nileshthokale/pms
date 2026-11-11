// Scratch script to test Neon AI Gateway models and inference
const baseUrl = process.env.NEON_AI_GATEWAY_BASE_URL;
const token = process.env.NEON_AI_GATEWAY_TOKEN;

if (!baseUrl || !token) {
  console.error("Missing NEON_AI_GATEWAY_BASE_URL or NEON_AI_GATEWAY_TOKEN");
  process.exit(1);
}

async function run() {
  console.log("Querying branch models from:", baseUrl + "/v1/models");
  try {
    const res = await fetch(`${baseUrl}/v1/models`, {
      headers: {
        Authorization: `Bearer ${token}`
      }
    });

    console.log("Status:", res.status, res.statusText);
    const json = await res.json();
    if (!res.ok) {
      console.log("Response payload:", JSON.stringify(json, null, 2));
      return;
    }

    const models = json.data || [];
    console.log(`Found ${models.length} models.`);
    const enabledModels = models.filter(m => m.enabled !== false);
    console.log(`Enabled models (${enabledModels.length}):`, enabledModels.map(m => m.id));

    if (enabledModels.length === 0) {
      console.log("Sample catalog models (first 10):", models.slice(0, 10).map(m => ({ id: m.id, enabled: m.enabled, unavailable_reason: m.unavailable_reason })));
    }
  } catch (err) {
    console.error("Error fetching models:", err.message);
  }
}

run();
