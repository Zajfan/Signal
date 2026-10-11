import test from "node:test";
import assert from "node:assert/strict";
import worker, { aiSignals, normalizeImportedJob, runIngestion, validateJob, verifyStripeSignature } from "./worker.mjs";

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

test("listing search uses bounded pagination and filters published jobs", async () => {
  let captured;
  const DB = { prepare(sql) { return { sql, params: [], bind(...params) { this.params = params; return this; }, async all() { captured = this; return { results: [{ id: "job-1", title: "AI Engineer" }] }; } }; } };
  const response = await worker.fetch(new Request("https://signal.example/api/v1/jobs?q=engineer&country=SE&work_mode=remote&limit=2&offset=1"), { DB }, {});
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).jobs.map((job) => job.id), ["job-1"]);
  assert.match(captured.sql, /UNION ALL/);
  assert.match(captured.sql, /status = 'published'/);
  assert.match(captured.sql, /LIMIT \? OFFSET \?/);
  assert.deepEqual(captured.params.slice(-2), [2, 1]);
});

test("checkout charges a configured server-side Stripe price and persists provider amount", async () => {
  const calls = [];
  const ID = "123e4567-e89b-12d3-a456-426614174000";
  const DB = {
    prepare(sql) {
      return { sql, params: [], bind(...params) { this.params = params; return this; },
        async run() { calls.push({ sql, params: this.params }); return { meta: { changes: 1 } }; },
        async first() {
          if (sql.includes("FROM employer_jobs j JOIN employers")) return { id: ID, status: "draft", company_name: "Example AB", verified_company_name: "Example AB", verification_status: "verified" };
          return null;
        }
      };
    },
    async batch(statements) { calls.push(...statements.map((statement) => ({ sql: statement.sql, params: statement.params }))); }
  };
  const oldFetch = globalThis.fetch;
  let stripeForm;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "https://api.stripe.com/v1/checkout/sessions");
    stripeForm = new URLSearchParams(options.body);
    return new Response(JSON.stringify({ id: "cs_test_1", url: "https://checkout.stripe.com/session", amount_total: 19_900, currency: "sek", expires_at: Math.floor(Date.now() / 1000) + 1800 }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const response = await worker.fetch(new Request(`https://signal.example/api/v1/employer/jobs/${ID}/checkout`, {
      method: "POST", headers: { "content-type": "application/json", "oai-authenticated-user-id": "user-42", "oai-authenticated-user-email": "employer@example.com" }, body: JSON.stringify({ package_code: "standard", amount: 1 })
    }), { DB, STRIPE_SECRET_KEY: "sk_test_placeholder", STRIPE_PRICE_STANDARD: "price_standard_fixed", STRIPE_PRICE_FEATURED: "price_featured_fixed" }, {});
    assert.equal(response.status, 200);
    assert.equal((await response.json()).checkout_url, "https://checkout.stripe.com/session");
    assert.equal(stripeForm.get("line_items[0][price]"), "price_standard_fixed");
    assert.equal(stripeForm.has("amount"), false);
    assert.ok(calls.some((call) => call.sql.includes("UPDATE payments") && call.params.includes(19_900) && call.params.includes("SEK")));
  } finally {
    globalThis.fetch = oldFetch;
  }
});

test("moderation requires an allowlisted moderator and exposes the featured state after approval", async () => {
  const statements = [];
  const DB = {
    prepare(sql) { return { sql, params: [], bind(...params) { this.params = params; return this; }, async first() { return { id: "job-1", status: "pending_review", package_code: "featured", company_name: "Example AB", verified_company_name: "Example AB", verification_status: "verified" }; } }; },
    async batch(items) { statements.push(...items.map((item) => ({ sql: item.sql, params: item.params }))); }
  };
  const url = "https://signal.example/api/v1/admin/jobs/123e4567-e89b-12d3-a456-426614174000/moderate";
  const body = JSON.stringify({ action: "approve" });
  const denied = await worker.fetch(new Request(url, { method: "POST", headers: { "content-type": "application/json", "oai-authenticated-user-id": "user-42", "oai-authenticated-user-email": "user@example.com" }, body }), { DB }, {});
  assert.equal(denied.status, 403);
  const approved = await worker.fetch(new Request(url, { method: "POST", headers: { "content-type": "application/json", "oai-authenticated-user-id": "admin-1", "oai-authenticated-user-email": "admin@example.com" }, body }), { DB, MODERATOR_USER_IDS: "admin-1" }, {});
  assert.equal(approved.status, 200);
  assert.equal((await approved.json()).status, "published");
  assert.ok(statements.some((statement) => statement.sql.includes("is_featured = CASE") && statement.params.includes("featured")));
});

test("employer company verification requires HTTPS and records a pending review", async () => {
  const statements = [];
  const DB = { prepare(sql) { return { sql, params: [], bind(...params) { this.params = params; return this; }, async run() { statements.push({ sql, params: this.params }); return { meta: { changes: 1 } }; } }; } };
  const headers = { "content-type": "application/json", "oai-authenticated-user-id": "user-42", "oai-authenticated-user-email": "employer@example.com" };
  const bad = await worker.fetch(new Request("https://signal.example/api/v1/employer/company-verification", { method: "POST", headers, body: JSON.stringify({ company_name: "Example AB", website_url: "http://example.com" }) }), { DB }, {});
  assert.equal(bad.status, 400);
  const good = await worker.fetch(new Request("https://signal.example/api/v1/employer/company-verification", { method: "POST", headers, body: JSON.stringify({ company_name: "Example AB", website_url: "https://example.com" }) }), { DB }, {});
  assert.equal(good.status, 202);
  assert.equal((await good.json()).verification_status, "pending");
  assert.ok(statements.some((statement) => statement.sql.includes("verification_status = 'pending'")));
});

test("employer verification is independently moderator-gated", async () => {
  const DB = { prepare(sql) { return { sql, params: [], bind(...params) { this.params = params; return this; }, async first() { return { user_id: "employer-7" }; }, async run() { return { meta: { changes: 1 } }; } }; } };
  const response = await worker.fetch(new Request("https://signal.example/api/v1/admin/employers/employer-7/verify", {
    method: "POST", headers: { "content-type": "application/json", "oai-authenticated-user-id": "admin-1", "oai-authenticated-user-email": "admin@example.com" }, body: JSON.stringify({ action: "approve" })
  }), { DB, MODERATOR_USER_IDS: "admin-1" }, {});
  assert.equal(response.status, 200);
  assert.equal((await response.json()).verification_status, "verified");
});

test("scheduled source ingestion records source permission, normalizes, and upserts public jobs", async () => {
  const calls = [];
  const DB = { prepare(sql) { return { sql, params: [], bind(...params) { this.params = params; return this; }, async run() { calls.push({ sql, params: this.params }); return { meta: { changes: 1 } }; } }; } };
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    assert.match(String(url), /^https:\/\/jobsearch\.api\.jobtechdev\.se\/search\?/);
    return Response.json({ hits: [{ id: "ad-77", headline: "AI Engineer", webpage_url: "https://jobs.example/ad-77", publication_date: "2026-10-10", employer: { name: "Example AB" }, workplace_address: { city: "Stockholm", country_code: "SE" }, description: { text: "Build machine learning software for local organizations." }, workplace_model: "Remote" }] });
  };
  try {
    await runIngestion({ DB, INGEST_SOURCES: JSON.stringify([{ enabled: true, source_id: "se-jobtech-ai", ats: "jobtech", label: "JobTech", country_code: "SE", query: "AI", limit: 10, max_pages: 1, permission_basis: "CC0", terms_url: "https://data.arbetsformedlingen.se/" }]) });
    const jobWrite = calls.find((call) => call.sql.includes("INSERT INTO imported_jobs"));
    assert.ok(jobWrite);
    assert.match(jobWrite.sql, /ON CONFLICT\(source_id, source_job_id\) DO UPDATE/);
    assert.ok(calls.some((call) => call.sql.includes("INSERT INTO ingest_sources") && call.params.includes("CC0")));
    assert.ok(calls.some((call) => call.sql.includes("SET status = 'expired'")));
  } finally {
    globalThis.fetch = oldFetch;
  }
});
