import test from "node:test";
import assert from "node:assert/strict";
import worker, { aiSignals, normalizeImportedJob, validateJob, verifyStripeSignature } from "./worker.mjs";

test("AI signal matching preserves distinct product and engineering signals", () => {
  assert.deepEqual(aiSignals("Use Cursor and AI-assisted workflows with LLMs"), ["llm", "ai-assisted", "cursor"]);
});

test("JobTech data normalizes into a traceable, searchable record", () => {
  const job = normalizeImportedJob({ ats: "jobtech", source_id: "se-jobtech", provider: "JobTech", country_code: "SE" }, {
    id: "ad-42", headline: "AI Engineer", webpage_url: "https://jobs.example/ad-42",
    description: { text: "Build machine learning services for Swedish customers." },
    employer: { name: "Example AB" },
    workplace_address: { city: "Stockholm", country_code: "SE" },
    workplace_model: "Remote"
  });
  assert.equal(job.sourceId, "ad-42");
  assert.equal(job.company, "Example AB");
  assert.equal(job.country, "SE");
  assert.equal(job.mode, "remote");
  assert.deepEqual(job.ai, ["machine learning", "ai engineer"]);
});

test("employer job validation rejects unsafe apply URLs and malformed ranges", () => {
  const base = { title: "AI Engineer", company_name: "Example AB", description: "A role description long enough to satisfy the server's minimum content requirement.", location: "Stockholm", country_code: "SE", apply_url: "https://example.com/apply" };
  assert.equal(validateJob(base).workMode, "on-site");
  assert.throws(() => validateJob({ ...base, apply_url: "javascript:alert(1)" }), /HTTP or HTTPS/);
  assert.throws(() => validateJob({ ...base, salary_min: 160_000, salary_max: 100_000 }), /cannot exceed/);
});

test("Stripe signature checks accept a valid signature and reject a tampered body", async () => {
  const payload = JSON.stringify({ id: "evt_1", type: "checkout.session.completed" });
  const timestamp = Math.floor(Date.now() / 1000);
  const secret = "whsec_test_only";
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${timestamp}.${payload}`));
  const hex = [...new Uint8Array(signature)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  assert.equal(await verifyStripeSignature(payload, `t=${timestamp},v1=${hex}`, secret), true);
  assert.equal(await verifyStripeSignature(`${payload} `, `t=${timestamp},v1=${hex}`, secret), false);
});

test("employer draft creation requires a signed-in identity and persists an owned draft", async () => {
  const calls = [];
  const DB = { prepare(sql) {
    const statement = { sql, params: [], bind(...params) { this.params = params; return this; },
      async run() { calls.push({ sql, params: this.params }); return { meta: { changes: 1 } }; },
      async first() { return null; }, async all() { return { results: [] }; } };
    return statement;
  } };
  const env = { DB };
  const body = { title: "AI Engineer", company_name: "Example AB", description: "Build reliable AI services for teams and ship improvements through an AI assisted development process.", apply_url: "https://example.com/apply", location: "Stockholm", country_code: "SE" };
  const anonymous = await worker.fetch(new Request("https://signal.example/api/v1/employer/jobs", { method: "POST", body: JSON.stringify(body) }), env, {});
  assert.equal(anonymous.status, 401);
  assert.equal(calls.length, 0);
  const signedIn = await worker.fetch(new Request("https://signal.example/api/v1/employer/jobs", { method: "POST", headers: { "content-type": "application/json", "oai-authenticated-user-id": "user-42", "oai-authenticated-user-email": "employer@example.com" }, body: JSON.stringify(body) }), env, {});
  assert.equal(signedIn.status, 201);
  const response = await signedIn.json();
  assert.equal(response.job.status, "draft");
  assert.equal(calls.length, 2);
  assert.match(calls[1].sql, /INSERT INTO employer_jobs/);
  assert.equal(calls[1].params[1], "user-42");
});

test("checkout endpoint remains a payment route and is disabled until fixed server prices exist", async () => {
  const DB = { prepare(sql) { return { sql, bind() { return this; }, async run() { return { meta: { changes: 1 } }; } }; } };
  const response = await worker.fetch(new Request("https://signal.example/api/v1/employer/jobs/123e4567-e89b-12d3-a456-426614174000/checkout", {
    method: "POST", headers: { "content-type": "application/json", "oai-authenticated-user-id": "user-42", "oai-authenticated-user-email": "employer@example.com" }, body: JSON.stringify({ package_code: "standard" })
  }), { DB }, {});
  assert.equal(response.status, 503);
  assert.match((await response.json()).error, /not configured/);
});
