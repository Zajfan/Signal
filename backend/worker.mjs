const MAX_BODY_BYTES = 32_000;
const MAX_LIMIT = 100;
const JOB_TTL_DAYS = 35;
const AI_PHRASES = [
  "artificial intelligence", "artificiell intelligens", "machine learning", "maskininlärning",
  "generative ai", "generativ ai", "large language model", "language model", "llm", "genai",
  "ai engineer", "ai developer", "ai software", "ai-assisted", "ai assisted", "ai-augmented",
  "ai augmented", "ai-native", "ai native", "vibe coding", "github copilot", "copilot",
  "cursor", "claude code", "coding agent", "agentic", "mlops", "model serving"
];

const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status,
  headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", "x-content-type-options": "nosniff" }
});
const nowIso = () => new Date().toISOString();
const uid = () => crypto.randomUUID();
const cleanText = (value, max) => String(value ?? "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim().slice(0, max);
const aiSignals = (text) => {
  const value = String(text ?? "").toLowerCase();
  return [...new Set(AI_PHRASES.filter((phrase) => value.includes(phrase)))];
};
const isHttpUrl = (value) => {
  try { return ["https:", "http:"].includes(new URL(value).protocol); }
  catch { return false; }
};

function identity(request) {
  const userId = request.headers.get("oai-authenticated-user-id")?.trim();
  const email = request.headers.get("oai-authenticated-user-email")?.trim();
  return userId && email ? { userId, email } : null;
}

async function readJson(request) {
  const raw = await request.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) throw new Error("Request body is too large");
  try { return JSON.parse(raw); } catch { throw new Error("Request body must be valid JSON"); }
}

function validateJob(input) {
  const job = {
    title: cleanText(input?.title, 180),
    companyName: cleanText(input?.company_name, 180),
    description: cleanText(input?.description, 12_000),
    applyUrl: String(input?.apply_url ?? "").trim(),
    location: cleanText(input?.location, 180),
    countryCode: String(input?.country_code ?? "").trim().toUpperCase(),
    workMode: String(input?.work_mode ?? "on-site").toLowerCase(),
    employmentType: cleanText(input?.employment_type ?? "full-time", 40).toLowerCase(),
    salaryMin: input?.salary_min == null ? null : Number(input.salary_min),
    salaryMax: input?.salary_max == null ? null : Number(input.salary_max),
    salaryCurrency: String(input?.salary_currency ?? "").trim().toUpperCase()
  };
  if (!job.title || !job.companyName || job.description.length < 40 || !job.location) throw new Error("Title, company, location, and a description of at least 40 characters are required");
  if (!isHttpUrl(job.applyUrl)) throw new Error("Apply URL must use HTTP or HTTPS");
  if (!/^[A-Z]{2}$/.test(job.countryCode)) throw new Error("Country code must be a two-letter ISO code");
  if (!["remote", "hybrid", "on-site"].includes(job.workMode)) throw new Error("Work mode must be remote, hybrid, or on-site");
  if (job.salaryMin != null && (!Number.isSafeInteger(job.salaryMin) || job.salaryMin < 0)) throw new Error("Minimum salary must be a non-negative integer");
  if (job.salaryMax != null && (!Number.isSafeInteger(job.salaryMax) || job.salaryMax < 0)) throw new Error("Maximum salary must be a non-negative integer");
  if (job.salaryMin != null && job.salaryMax != null && job.salaryMin > job.salaryMax) throw new Error("Minimum salary cannot exceed maximum salary");
  if (job.salaryCurrency && !/^[A-Z]{3}$/.test(job.salaryCurrency)) throw new Error("Salary currency must be a three-letter ISO code");
  return job;
}

async function ensureEmployer(db, user) {
  await db.prepare(`INSERT INTO employers (user_id, email) VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET email = excluded.email, updated_at = ?`)
    .bind(user.userId, user.email, nowIso()).run();
}

async function listJobs(request, env) {
  const url = new URL(request.url);
  const q = cleanText(url.searchParams.get("q"), 100);
  const country = (url.searchParams.get("country") ?? "").toUpperCase();
  const mode = (url.searchParams.get("work_mode") ?? "").toLowerCase();
  const limit = Math.min(MAX_LIMIT, Math.max(1, Number(url.searchParams.get("limit")) || 30));
  const offset = Math.max(0, Number(url.searchParams.get("offset")) || 0);
  const clauses = ["status = 'published'", "(expires_at IS NULL OR expires_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"];
  const values = [];
  if (q) {
    clauses.push("(title LIKE ? OR company_name LIKE ? OR location LIKE ? OR description LIKE ?)");
    const needle = `%${q}%`;
    values.push(needle, needle, needle, needle);
  }
  if (/^[A-Z]{2}$/.test(country)) { clauses.push("country_code = ?"); values.push(country); }
  if (["remote", "hybrid", "on-site"].includes(mode)) { clauses.push("work_mode = ?"); values.push(mode); }
  const where = clauses.join(" AND ");
  const importedClauses = ["status = 'published'", "datetime(last_seen_at) >= datetime('now', ?)"];
  const importedValues = [`-${JOB_TTL_DAYS} days`];
  if (q) {
    importedClauses.push("(title LIKE ? OR company_name LIKE ? OR location LIKE ? OR description LIKE ?)");
    const needle = `%${q}%`;
    importedValues.push(needle, needle, needle, needle);
  }
  if (/^[A-Z]{2}$/.test(country)) { importedClauses.push("country_code = ?"); importedValues.push(country); }
  if (["remote", "hybrid", "on-site"].includes(mode)) { importedClauses.push("work_mode = ?"); importedValues.push(mode); }
  const result = await env.DB.prepare(`SELECT id, title, company, location, country_code, work_mode, employment_type, salary_min, salary_max, currency, description, apply_url, published_at, source, is_featured
    FROM (
      SELECT id, title, company_name AS company, location, country_code, work_mode, employment_type, salary_min, salary_max, salary_currency AS currency, description, apply_url, published_at, 'direct' AS source, is_featured FROM employer_jobs WHERE ${where}
      UNION ALL
      SELECT id, title, company_name AS company, location, country_code, work_mode, employment_type, salary_min, salary_max, salary_currency AS currency, description, apply_url, last_seen_at AS published_at, source_id AS source, 0 AS is_featured FROM imported_jobs WHERE ${importedClauses.join(" AND ")}
    ) ORDER BY is_featured DESC, published_at DESC LIMIT ? OFFSET ?`)
    .bind(...values, ...importedValues, limit, offset).all();
  return json({ jobs: result.results ?? [], limit, offset });
}

async function employerJobs(request, env, user, jobId) {
  if (!user) return json({ error: "Sign in is required for employer actions" }, 401);
  await ensureEmployer(env.DB, user);
  if (request.method === "GET" && !jobId) {
    const result = await env.DB.prepare(`SELECT id, title, company_name, location, country_code, work_mode, employment_type, status, package_code, expires_at, created_at FROM employer_jobs WHERE employer_user_id = ? ORDER BY created_at DESC LIMIT 100`)
      .bind(user.userId).all();
    return json({ jobs: result.results ?? [] });
  }
  if (request.method === "POST" && !jobId) {
    const job = validateJob(await readJson(request));
    const id = uid();
    await env.DB.prepare(`INSERT INTO employer_jobs (id, employer_user_id, title, company_name, description, apply_url, location, country_code, work_mode, employment_type, salary_min, salary_max, salary_currency)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
      .bind(id, user.userId, job.title, job.companyName, job.description, job.applyUrl, job.location, job.countryCode, job.workMode, job.employmentType, job.salaryMin, job.salaryMax, job.salaryCurrency || null).run();
    return json({ job: { id, ...job, status: "draft" } }, 201);
  }
  const match = /^\/api\/v1\/employer\/jobs\/([0-9a-f-]+)\/checkout$/i.exec(new URL(request.url).pathname);
  if (request.method === "POST" && match && !jobId) return startCheckout(request, env, user, match[1]);
  if (jobId && request.method === "GET") {
    const result = await env.DB.prepare(`SELECT id, title, company_name, description, apply_url, location, country_code, work_mode, employment_type, salary_min, salary_max, salary_currency, status, package_code, expires_at, created_at FROM employer_jobs WHERE id = ? AND employer_user_id = ?`)
      .bind(jobId, user.userId).first();
    return result ? json({ job: result }) : json({ error: "Job not found" }, 404);
  }
  return json({ error: "Route not found" }, 404);
}

async function startCheckout(request, env, user, jobId) {
  if (!env.STRIPE_SECRET_KEY || !env.STRIPE_PRICE_STANDARD || !env.STRIPE_PRICE_FEATURED) return json({ error: "Employer checkout is not configured yet" }, 503);
  const body = await readJson(request);
  const packageCode = body?.package_code;
  const priceId = packageCode === "standard" ? env.STRIPE_PRICE_STANDARD : packageCode === "featured" ? env.STRIPE_PRICE_FEATURED : null;
  if (!priceId) return json({ error: "Choose a valid posting package" }, 400);
  const job = await env.DB.prepare(`SELECT id, status FROM employer_jobs WHERE id = ? AND employer_user_id = ?`).bind(jobId, user.userId).first();
  if (!job) return json({ error: "Job not found" }, 404);
  if (!["draft", "awaiting_payment"].includes(job.status)) return json({ error: "This job cannot be checked out in its current state" }, 409);
  const existing = await env.DB.prepare(`SELECT checkout_url, checkout_expires_at, package_code FROM payments WHERE employer_job_id = ? AND employer_user_id = ? AND status = 'checkout_open' ORDER BY created_at DESC LIMIT 1`)
    .bind(jobId, user.userId).first();
  if (existing?.checkout_url && Date.parse(existing.checkout_expires_at ?? "") > Date.now()) {
    if (existing.package_code !== packageCode) return json({ error: "A different posting package already has an active checkout session" }, 409);
    return json({ checkout_url: existing.checkout_url, reused: true });
  }
  const idempotencyKey = uid();
  const paymentId = uid();
  const origin = new URL(request.url).origin;
  const checkoutExpiry = Math.floor(Date.now() / 1000) + 30 * 60;
  const form = new URLSearchParams({
    mode: "payment", "line_items[0][price]": priceId, "line_items[0][quantity]": "1",
    client_reference_id: jobId, "metadata[job_id]": jobId, "metadata[employer_user_id]": user.userId,
    "metadata[package_code]": packageCode, expires_at: String(checkoutExpiry), success_url: `${origin}/employer?checkout=success`,
    cancel_url: `${origin}/employer?checkout=cancelled`
  });
  await env.DB.prepare(`INSERT INTO payments (id, employer_job_id, employer_user_id, provider, idempotency_key, package_code, amount_minor, currency, status)
    VALUES (?, ?, ?, 'stripe', ?, ?, NULL, NULL, 'created')`)
    .bind(paymentId, jobId, user.userId, idempotencyKey, packageCode).run();
  const response = await fetch("https://api.stripe.com/v1/checkout/sessions", {
    method: "POST", headers: { authorization: `Bearer ${env.STRIPE_SECRET_KEY}`, "content-type": "application/x-www-form-urlencoded", "idempotency-key": idempotencyKey }, body: form
  });
  const session = await response.json();
  if (!response.ok || !session.id || !session.url) {
    await env.DB.prepare(`UPDATE payments SET status = 'failed', updated_at = ? WHERE id = ?`).bind(nowIso(), paymentId).run();
    return json({ error: "Could not create payment session" }, 502);
  }
  await env.DB.batch([
    env.DB.prepare(`UPDATE payments SET provider_session_id = ?, checkout_url = ?, checkout_expires_at = ?, amount_minor = ?, currency = ?, status = 'checkout_open', updated_at = ? WHERE id = ?`).bind(session.id, session.url, session.expires_at ? new Date(session.expires_at * 1000).toISOString() : new Date(checkoutExpiry * 1000).toISOString(), session.amount_total ?? null, session.currency?.toUpperCase() ?? null, nowIso(), paymentId),
    env.DB.prepare(`UPDATE employer_jobs SET status = 'awaiting_payment', package_code = ?, updated_at = ? WHERE id = ?`).bind(packageCode, nowIso(), jobId)
  ]);
  return json({ checkout_url: session.url });
}

async function verifyStripeSignature(payload, signatureHeader, secret) {
  const parts = String(signatureHeader ?? "").split(",").map((item) => item.split("=", 2));
  const timestamp = parts.find(([key]) => key === "t")?.[1];
  const signatures = parts.filter(([key]) => key === "v1").map(([, value]) => value);
  if (!timestamp || !/^\d+$/.test(timestamp) || Math.abs(Date.now() / 1000 - Number(timestamp)) > 300 || !signatures.length) return false;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${timestamp}.${payload}`));
  const expected = [...new Uint8Array(mac)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  return signatures.some((value) => value.length === expected.length && crypto.subtle.timingSafeEqual
    ? crypto.subtle.timingSafeEqual(hexToBytes(value), hexToBytes(expected))
    : constantTimeEqual(value, expected));
}
const hexToBytes = (hex) => Uint8Array.from(hex.match(/.{2}/g) ?? [], (byte) => parseInt(byte, 16));
function constantTimeEqual(a, b) {
  let difference = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) difference |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  return difference === 0;
}

async function stripeWebhook(request, env) {
  if (!env.STRIPE_WEBHOOK_SECRET) return json({ error: "Webhook is not configured" }, 503);
  const payload = await request.text();
  if (new TextEncoder().encode(payload).byteLength > 256_000) return json({ error: "Payload is too large" }, 413);
  if (!await verifyStripeSignature(payload, request.headers.get("stripe-signature"), env.STRIPE_WEBHOOK_SECRET)) return json({ error: "Invalid webhook signature" }, 400);
  let event;
  try { event = JSON.parse(payload); } catch { return json({ error: "Invalid event JSON" }, 400); }
  if (!["checkout.session.completed", "checkout.session.async_payment_succeeded"].includes(event.type)) return json({ received: true });
  const session = event.data?.object;
  if (!session?.id || session.payment_status !== "paid") return json({ received: true });
  if (!event.id) return json({ error: "Missing event ID" }, 400);
  const occurredAt = nowIso();
  await env.DB.batch([
    env.DB.prepare(`INSERT OR IGNORE INTO payment_webhook_events (provider_event_id) VALUES (?)`).bind(event.id),
    env.DB.prepare(`UPDATE payments SET status = 'paid', provider_payment_id = ?, updated_at = ? WHERE provider_session_id = ?`)
      .bind(session.payment_intent ?? null, occurredAt, session.id),
    env.DB.prepare(`UPDATE employer_jobs SET status = 'pending_review', updated_at = ? WHERE id = (SELECT employer_job_id FROM payments WHERE provider_session_id = ?) AND status = 'awaiting_payment'`)
      .bind(occurredAt, session.id)
  ]);
  return json({ received: true });
}

async function moderateJob(request, env, user, jobId) {
  const moderators = new Set(String(env.MODERATOR_USER_IDS ?? "").split(",").map((id) => id.trim()).filter(Boolean));
  if (!user || !moderators.has(user.userId)) return json({ error: "Moderator access is required" }, 403);
  const input = await readJson(request);
  const action = String(input?.action ?? "");
  const note = cleanText(input?.note, 1000) || null;
  if (!["approve", "reject"].includes(action)) return json({ error: "Action must be approve or reject" }, 400);
  const job = await env.DB.prepare(`SELECT id, status, package_code FROM employer_jobs WHERE id = ?`).bind(jobId).first();
  if (!job) return json({ error: "Job not found" }, 404);
  if (job.status !== "pending_review") return json({ error: "Only paid jobs awaiting review can be moderated" }, 409);
  const status = action === "approve" ? "published" : "rejected";
  const publishedAt = action === "approve" ? nowIso() : null;
  const expiresAt = action === "approve" ? new Date(Date.now() + 30 * 86400_000).toISOString() : null;
  const eventId = uid();
  await env.DB.batch([
    env.DB.prepare(`UPDATE employer_jobs SET status = ?, published_at = ?, expires_at = ?, is_featured = CASE WHEN ? = 'featured' THEN 1 ELSE 0 END, updated_at = ? WHERE id = ? AND status = 'pending_review'`)
      .bind(status, publishedAt, expiresAt, job.package_code ?? "standard", nowIso(), jobId),
    env.DB.prepare(`INSERT INTO moderation_events (id, employer_job_id, moderator_user_id, action, note) VALUES (?, ?, ?, ?, ?)`)
      .bind(eventId, jobId, user.userId, action, note)
  ]);
  return json({ job_id: jobId, status, expires_at: expiresAt });
}

function normalizeImportedJob(source, raw) {
  let title = "", company = source.provider ?? source.source_id, description = "", applyUrl = "", sourceUrl = "", location = "", country = source.country_code ?? null, mode = "on-site", type = "full-time", salaryMin = null, salaryMax = null, currency = null, sourceId = "";
  if (source.ats === "jobtech") {
    const employer = raw.employer ?? {}; const address = raw.workplace_address ?? {}; const desc = raw.description ?? {};
    title = raw.headline; company = employer.name || company; description = desc.text || desc.text_formatted || ""; applyUrl = raw.webpage_url; sourceUrl = applyUrl;
    location = [address.city, address.municipality, address.region].filter(Boolean).join(", "); country = address.country_code || country;
    if (!/^[A-Z]{2}$/.test(String(country ?? "").toUpperCase())) country = /sweden|sverige/i.test(String(address.country ?? "")) ? "SE" : null;
    mode = /remote|distans/i.test(`${raw.workplace_model} ${description}`) ? "remote" : /hybrid/i.test(`${raw.workplace_model} ${description}`) ? "hybrid" : "on-site";
    type = raw.employment_type?.label || type; sourceId = raw.id;
  } else if (source.ats === "greenhouse") {
    title = raw.title; company = source.company || company; description = raw.content || ""; applyUrl = raw.absolute_url; sourceUrl = applyUrl; location = raw.location?.name || ""; sourceId = raw.id;
  } else if (source.ats === "lever") {
    title = raw.text; company = source.company || company; description = [raw.descriptionPlain, raw.additional].filter(Boolean).join(" "); applyUrl = raw.hostedUrl; sourceUrl = applyUrl;
    location = raw.categories?.location || ""; type = raw.categories?.commitment || type; sourceId = raw.id;
  } else if (source.ats === "ashby") {
    title = raw.title; company = source.company || company; description = raw.descriptionPlain || raw.descriptionHtml || ""; applyUrl = raw.jobUrl; sourceUrl = applyUrl;
    location = raw.location || ""; mode = String(raw.workplaceType).toLowerCase() === "remote" ? "remote" : String(raw.workplaceType).toLowerCase() === "hybrid" ? "hybrid" : mode;
    salaryMin = raw.compensation?.minValue ?? null; salaryMax = raw.compensation?.maxValue ?? null; currency = raw.compensation?.currency ?? null; sourceId = raw.id;
  } else if (source.ats === "usajobs") {
    const detail = raw.MatchedObjectDescriptor ?? {}; const desc = detail.UserArea?.Details ?? {};
    title = detail.PositionTitle; company = detail.OrganizationName || detail.DepartmentName || company;
    description = [desc.JobSummary, desc.MajorDuties, detail.QualificationSummary].filter(Boolean).join(" ");
    applyUrl = detail.PositionURI || detail.ApplyURI?.[0] || ""; sourceUrl = detail.PositionURI || applyUrl;
    location = detail.PositionLocationDisplay || ""; currency = "USD"; sourceId = raw.MatchedObjectId;
    const pay = detail.PositionRemuneration?.[0]; salaryMin = pay?.MinimumRange ? Number(pay.MinimumRange) : null; salaryMax = pay?.MaximumRange ? Number(pay.MaximumRange) : null;
  }
  const ai = aiSignals(`${title} ${description}`);
  if (!sourceId || !title || !isHttpUrl(applyUrl) || !ai.length) return null;
  return { sourceId: String(sourceId), title: cleanText(title, 180), company: cleanText(company, 180), description: cleanText(description, 5000), applyUrl, sourceUrl, location: cleanText(location, 180), country, mode, type: cleanText(type, 40), salaryMin, salaryMax, currency, ai };
}

async function fetchSource(source, env) {
  const query = encodeURIComponent(source.query ?? "AI engineer");
  if (source.ats === "jobtech") {
    const limit = Math.min(100, Math.max(1, Number(source.limit) || 50));
    const pages = Math.min(10, Math.max(1, Number(source.max_pages) || 1));
    const hits = [];
    for (let page = 0; page < pages; page++) {
      const result = await fetch(`https://jobsearch.api.jobtechdev.se/search?q=${query}&limit=${limit}&offset=${page * limit}`);
      if (!result.ok) throw new Error(`JobTech returned ${result.status}`);
      const next = (await result.json()).hits ?? [];
      hits.push(...next);
      if (next.length < limit) break;
    }
    return hits;
  }
  if (source.ats === "greenhouse") {
    const result = await fetch(`https://boards-api.greenhouse.io/v1/boards/${encodeURIComponent(source.board)}/jobs?content=true`);
    if (!result.ok) throw new Error(`Greenhouse returned ${result.status}`);
    return (await result.json()).jobs ?? [];
  }
  if (source.ats === "lever") {
    const result = await fetch(`https://api.lever.co/v0/postings/${encodeURIComponent(source.board)}?mode=json`);
    if (!result.ok) throw new Error(`Lever returned ${result.status}`);
    return await result.json();
  }
  if (source.ats === "ashby") {
    const result = await fetch(`https://api.ashbyhq.com/posting-api/job-board/${encodeURIComponent(source.board)}?includeCompensation=true`);
    if (!result.ok) throw new Error(`Ashby returned ${result.status}`);
    return (await result.json()).jobs ?? [];
  }
  if (source.ats === "usajobs") {
    if (!env.USAJOBS_API_KEY || !env.USAJOBS_USER_AGENT) throw new Error("USAJOBS credentials are missing");
    const params = new URLSearchParams({ Keyword: source.query ?? "AI engineer", ResultsPerPage: String(Math.min(500, Math.max(1, Number(source.limit) || 100))), Fields: "Full" });
    const response = await fetch(`https://data.usajobs.gov/api/Search?${params}`, { headers: { Host: "data.usajobs.gov", "User-Agent": env.USAJOBS_USER_AGENT, "Authorization-Key": env.USAJOBS_API_KEY } });
    if (!response.ok) throw new Error(`USAJOBS returned ${response.status}`);
    return (await response.json()).SearchResult?.SearchResultItems ?? [];
  }
  throw new Error(`Unsupported adapter: ${source.ats}`);
}

async function runIngestion(env) {
  if (!env.DB) return;
  let sources = [];
  try { if (env.INGEST_SOURCES) sources = JSON.parse(env.INGEST_SOURCES); } catch { throw new Error("INGEST_SOURCES must be valid JSON"); }
  if (!Array.isArray(sources) || sources.length > 50) throw new Error("INGEST_SOURCES must be an array of at most 50 sources");
  for (const source of sources) {
    if (!source.enabled) continue;
    if (!source.source_id || !source.ats || !source.permission_basis) continue;
    try {
      await env.DB.prepare(`INSERT INTO ingest_sources (source_id, provider, label, country_code, permission_basis, terms_url, enabled, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?) ON CONFLICT(source_id) DO UPDATE SET enabled=1, updated_at=excluded.updated_at`)
        .bind(source.source_id, source.ats, source.label ?? source.provider ?? source.source_id, source.country_code ?? null, source.permission_basis, source.terms_url ?? null, nowIso()).run();
      const items = await fetchSource(source, env);
      for (const raw of items) {
        const job = normalizeImportedJob(source, raw);
        if (!job) continue;
        await env.DB.prepare(`INSERT INTO imported_jobs (id, source_id, source_job_id, title, company_name, description, source_url, apply_url, location, country_code, work_mode, employment_type, salary_min, salary_max, salary_currency, ai_signals, source_updated_at, first_seen_at, last_seen_at, status)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'published')
          ON CONFLICT(source_id, source_job_id) DO UPDATE SET title=excluded.title, company_name=excluded.company_name, description=excluded.description, source_url=excluded.source_url, apply_url=excluded.apply_url, location=excluded.location, country_code=excluded.country_code, work_mode=excluded.work_mode, employment_type=excluded.employment_type, salary_min=excluded.salary_min, salary_max=excluded.salary_max, salary_currency=excluded.salary_currency, ai_signals=excluded.ai_signals, source_updated_at=excluded.source_updated_at, last_seen_at=excluded.last_seen_at, status='published'`)
          .bind(uid(), source.source_id, job.sourceId, job.title, job.company, job.description, job.sourceUrl, job.applyUrl, job.location, job.country, job.mode, job.type, job.salaryMin, job.salaryMax, job.currency, JSON.stringify(job.ai), raw.updated_at ?? raw.publication_date ?? raw.publishedAt ?? null, nowIso(), nowIso()).run();
      }
      await env.DB.prepare(`INSERT INTO ingest_sources (source_id, provider, label, country_code, permission_basis, terms_url, enabled, last_success_at, last_error, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, NULL, ?) ON CONFLICT(source_id) DO UPDATE SET last_success_at=excluded.last_success_at, last_error=NULL, updated_at=excluded.updated_at`)
        .bind(source.source_id, source.ats, source.label ?? source.provider ?? source.source_id, source.country_code ?? null, source.permission_basis, source.terms_url ?? null, nowIso(), nowIso()).run();
    } catch (error) {
      await env.DB.prepare(`INSERT INTO ingest_sources (source_id, provider, label, country_code, permission_basis, terms_url, enabled, last_error, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?) ON CONFLICT(source_id) DO UPDATE SET last_error=excluded.last_error, updated_at=excluded.updated_at`)
        .bind(source.source_id, source.ats, source.label ?? source.provider ?? source.source_id, source.country_code ?? null, source.permission_basis, source.terms_url ?? null, cleanText(error.message, 500), nowIso()).run();
    }
  }
  await env.DB.prepare(`UPDATE imported_jobs SET status = 'expired' WHERE status = 'published' AND datetime(last_seen_at) < datetime('now', ?)`) 
    .bind(`-${JOB_TTL_DAYS} days`).run();
  await env.DB.prepare(`UPDATE employer_jobs SET status = 'expired', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE status = 'published' AND expires_at IS NOT NULL AND expires_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`).run();
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    try {
      if (url.pathname === "/api/v1/health" && request.method === "GET") return json({ ok: true });
      if (!env.DB) return json({ error: "Database is not configured" }, 503);
      if (url.pathname === "/api/v1/jobs" && request.method === "GET") return await listJobs(request, env);
      if (url.pathname === "/api/v1/payments/stripe/webhook" && request.method === "POST") return await stripeWebhook(request, env);
      const moderation = /^\/api\/v1\/admin\/jobs\/([0-9a-f-]+)\/moderate$/i.exec(url.pathname);
      if (moderation && request.method === "POST") return await moderateJob(request, env, identity(request), moderation[1]);
      if (url.pathname === "/api/v1/employer/jobs" || url.pathname.startsWith("/api/v1/employer/jobs/")) {
        const user = identity(request);
        const pathId = /^\/api\/v1\/employer\/jobs\/([0-9a-f-]+)$/i.exec(url.pathname)?.[1];
        return await employerJobs(request, env, user, pathId);
      }
      return json({ error: "Route not found" }, 404);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unexpected server error";
      const clientError = /Request body|Title,|Apply URL|Country code|Work mode|salary|Minimum salary|Maximum salary|Choose a valid posting package|Action must/.test(message);
      return json({ error: clientError ? message : "Internal server error" }, clientError ? 400 : 500);
    }
  },
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(runIngestion(env));
  }
};

export { aiSignals, normalizeImportedJob, validateJob, verifyStripeSignature };
