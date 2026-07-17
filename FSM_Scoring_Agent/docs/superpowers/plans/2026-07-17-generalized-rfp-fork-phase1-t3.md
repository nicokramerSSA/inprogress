# Generalized RFP Evaluation Fork — Phase 1 Implementation Plan (T3 stack)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> This plan supersedes `2026-07-17-generalized-rfp-fork-phase1.md` (Flask version, kept for reference only — do not execute it).

**Goal:** A new private T3 repo where a consultant creates a project, uploads an Excel of requirements + categories, evaluates vendors against it (mock engine keyless, live models optional), and gets gated, weighted results stored in SQLite via Prisma.

**Architecture:** Ground-up build from the spec (`docs/superpowers/specs/2026-07-17-generalized-rfp-fork-design.md` in the parent repo). Nothing is copied wholesale from the parent; scoring semantics, gating rules, and prompt text are ported. Evidence (per-requirement LLM scores) is stored once; everything downstream of weights is a pure shared `rollup()` in TypeScript used by both server and (Phase 2) client.

**Tech Stack:** Next.js (App Router) + TypeScript + tRPC v11 + Prisma (SQLite) + Tailwind + Auth.js v5 (credentials) + Vitest. LLM SDKs: `@anthropic-ai/sdk`, `openai`. Excel: `exceljs`. Deployed later as a long-running Node server (`next start`) on Render — never serverless.

## Global Constraints

- New private GitHub repo `chagood8/rfp-eval-agent`. Nothing from the parent repo's git history.
- Every project-scoped tRPC procedure takes `projectId` as input. No global "active project" server state.
- API keys come from env at call time (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`), never disk/DB. Missing key = clear error string surfaced in results, never a crash.
- The offline mock engine must work end-to-end with zero keys and no network.
- Priority multipliers default Must 3.0 / Should 2.0 / Could 1.0; stored per project as JSON, editable.
- "Wont" requirements are stored but excluded from scoring, rollups, and gating.
- Gating is deterministic, computed from stored scores, never LLM-overridable. Default: unmet Must with response code GAP or ROADMAP disqualifies; CUSTOM does not.
- Response-code vocabulary: OOB, CONFIG, EXTENSION, CUSTOM, PARTNER, ROADMAP, GAP. Met values: Yes / Partial / No / N/A. Confidence: High / Medium / Low.
- Model registry lives in `src/server/engine/models.ts` with CURRENT model IDs: `claude-opus-4-8`, `claude-sonnet-5`, `claude-haiku-4-5`, `gpt-4o`, `gpt-4o-mini`, `mock`. Task defaults: scoring → `claude-sonnet-5`, vote → `claude-opus-4-8`, chat → `claude-haiku-4-5`. Never date-suffix the Claude IDs.
- Claude calls use adaptive thinking implicitly (no `thinking` param needed), NO `temperature`/`top_p`/`top_k` (400 on current models), and `output_config: {format: {type: "json_schema", ...}}` for structured JSON.
- Evaluations run as in-process background jobs (single instance). Job registry survives dev HMR via `globalThis`.
- All times SQLite defaults; DB file `prisma/dev.db` locally, `DATABASE_URL` env everywhere.
- `git push` and `rm` require user approval per the user's permissions policy — pause and ask at those steps.

## File structure (end of Phase 1)

```
prisma/schema.prisma
src/
  server/
    db.ts                    Prisma client singleton (t3 default)
    auth.ts                  Auth.js v5 config (credentials provider)
    api/
      trpc.ts  root.ts       t3 defaults (protectedProcedure added)
      routers/
        project.ts  vendor.ts  intake.ts  evaluation.ts  chat.ts
    engine/
      rollup.ts              pure rollup math (shared fixture-tested)
      persona.ts             neutral persona + contextBrief prompt builders
      models.ts              model registry + task defaults
      providers.ts           Anthropic / OpenAI / mock LLM abstraction
      retrieval.ts           term-overlap chunk index (ported)
      scoring.ts             batched scoring + deterministic mock scorer
      vote.ts                bands + narrative
      jobs.ts                in-process job registry + evaluation runner
      intake.ts              exceljs template + parse/validate/commit
  app/
    layout.tsx  page.tsx     shell + project picker
    login/page.tsx
    projects/[id]/page.tsx   tabs: Setup | Evaluate | Results | Chat
    api/template/route.ts    xlsx template download
    api/projects/[id]/intake/route.ts   multipart upload → parse preview
  components/                ProjectPicker, IntakeWizard, VendorPanel,
                             EvaluatePanel, ResultsDashboard, VendorDetail, ChatPanel
src/server/engine/__tests__/ rollup.test.ts, intake.test.ts, scoring.test.ts, vote.test.ts
src/server/api/__tests__/    project.test.ts, evaluation.test.ts
src/server/engine/__tests__/fixtures/rollup_fixture.json
config/persona.json
CLAUDE.md  README.md  vitest.config.ts
```

---

### Task 1: Scaffold the T3 app and private repo

**Files:**
- Create: `~/workspace/projects/rfp-eval-agent/` via create-t3-app

**Interfaces:**
- Produces: a pushed `main` with Next.js App Router + tRPC + Prisma(SQLite) + Tailwind, Vitest wired, `npm run dev` and `npx vitest run` both working.

- [ ] **Step 1: Scaffold**

```bash
cd ~/workspace/projects
npm create t3-app@latest rfp-eval-agent -- --CI --trpc --prisma --tailwind --appRouter --dbProvider sqlite
cd rfp-eval-agent
```

If the CLI flags have drifted, run interactively and pick: TypeScript, Tailwind, tRPC, Prisma, App Router, SQLite, no NextAuth (added manually in Task 13), ESLint+Prettier.

- [ ] **Step 2: Add deps + Vitest**

```bash
npm install exceljs @anthropic-ai/sdk openai
npm install -D vitest
```

`vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  test: { environment: "node", include: ["src/**/__tests__/**/*.test.ts"] },
  resolve: { alias: { "~": path.resolve(__dirname, "src") } },
});
```

Add to `package.json` scripts: `"test": "vitest run"`.

- [ ] **Step 3: Smoke check**

Run: `npm run dev` → http://localhost:3000 renders the t3 starter page. `npx vitest run` → "no test files found" exits 0 (or add a trivial placeholder test).

- [ ] **Step 4: Create the private repo and push (ASK USER before the push)**

```bash
git add -A && git commit -m "chore: t3 scaffold (nextjs, trpc, prisma/sqlite, tailwind, vitest)"
gh repo create chagood8/rfp-eval-agent --private --source . --push
```

Expected: private repo visible at github.com/chagood8/rfp-eval-agent.

---

### Task 2: Prisma schema

**Files:**
- Modify: `prisma/schema.prisma`
- Create: `src/server/engine/defaults.ts`, `src/server/engine/__tests__/schema.test.ts`

**Interfaces:**
- Produces: models `Project, Category, Requirement, WeightProfile, Vendor, Evaluation, RequirementScore, Scenario, User`; `defaults.ts` exporting `DEFAULT_GATING`, `DEFAULT_MULTIPLIERS`, `GatingConfig` and `PriorityMultipliers` types, and `parseGating(json: string)` / `parseMultipliers(json: string)` helpers.

- [ ] **Step 1: Write the schema** (replace the t3 example model; keep the generator/datasource blocks)

```prisma
model Project {
  id                  Int      @id @default(autoincrement())
  name                String
  client              String   @default("")
  status              String   @default("active")
  contextBrief        String   @default("")
  gatingConfig        String   // JSON GatingConfig
  priorityMultipliers String   // JSON {Must,Should,Could}
  createdAt           DateTime @default(now())
  categories          Category[]
  requirements        Requirement[]
  weightProfiles      WeightProfile[]
  vendors             Vendor[]
  evaluations         Evaluation[]
  scenarios           Scenario[]
}

model Category {
  id            Int     @id @default(autoincrement())
  projectId     Int
  project       Project @relation(fields: [projectId], references: [id], onDelete: Cascade)
  name          String
  description   String  @default("")
  defaultWeight Float
  sortOrder     Int     @default(0)
  requirements  Requirement[]
}

model Requirement {
  id           Int      @id @default(autoincrement())
  projectId    Int
  project      Project  @relation(fields: [projectId], references: [id], onDelete: Cascade)
  extId        String
  text         String
  categoryId   Int
  category     Category @relation(fields: [categoryId], references: [id], onDelete: Cascade)
  priority     String   // Must | Should | Could | Wont
  sectionLabel String   @default("")
  notes        String   @default("")
  scores       RequirementScore[]
  @@unique([projectId, extId])
}

model WeightProfile {
  id        Int      @id @default(autoincrement())
  projectId Int
  project   Project  @relation(fields: [projectId], references: [id], onDelete: Cascade)
  name      String
  weights   String   // JSON {categoryId(string): weight 0..100}
  isActive  Boolean  @default(false)
  createdAt DateTime @default(now())
}

model Vendor {
  id          Int     @id @default(autoincrement())
  projectId   Int
  project     Project @relation(fields: [projectId], references: [id], onDelete: Cascade)
  name        String
  dossierText String  @default("")
  evaluations Evaluation[]
  @@unique([projectId, name])
}

model Evaluation {
  id            Int      @id @default(autoincrement())
  projectId     Int
  project       Project  @relation(fields: [projectId], references: [id], onDelete: Cascade)
  vendorId      Int
  vendor        Vendor   @relation(fields: [vendorId], references: [id], onDelete: Cascade)
  status        String   @default("running") // running|done|failed|cancelled
  scoringModel  String
  voteModel     String
  vote          String?  // JSON Vote
  engineWarning String   @default("")
  isDemo        Boolean  @default(false)
  proposalText  String   @default("")
  createdAt     DateTime @default(now())
  scores        RequirementScore[]
}

model RequirementScore {
  evaluationId  Int
  evaluation    Evaluation  @relation(fields: [evaluationId], references: [id], onDelete: Cascade)
  requirementId Int
  requirement   Requirement @relation(fields: [requirementId], references: [id], onDelete: Cascade)
  met           String
  quality       Int
  responseCode  String
  confidence    String
  rationale     String @default("")
  evidenceGap   String @default("")
  scoredLive    Boolean @default(false)
  @@id([evaluationId, requirementId])
}

model Scenario {
  id         Int      @id @default(autoincrement())
  projectId  Int
  project    Project  @relation(fields: [projectId], references: [id], onDelete: Cascade)
  name       String
  weights    String
  archetypes String   @default("[]")
  notes      String   @default("")
  createdAt  DateTime @default(now())
}

model User {
  id           Int    @id @default(autoincrement())
  email        String @unique
  name         String @default("")
  passwordHash String // bcrypt
  mustChange   Boolean @default(true)
}
```

- [ ] **Step 2: `src/server/engine/defaults.ts`**

```ts
export type GatingConfig = {
  gatePriorities: string[];
  gatingCodes: string[];
  unmetMetValues: string[];
  verdict: "Disqualified" | "Reject";
};
export type PriorityMultipliers = Record<string, number>;

export const DEFAULT_GATING: GatingConfig = {
  gatePriorities: ["Must"],
  gatingCodes: ["GAP", "ROADMAP"],
  unmetMetValues: ["No"],
  verdict: "Disqualified",
};
export const DEFAULT_MULTIPLIERS: PriorityMultipliers = { Must: 3, Should: 2, Could: 1 };

export const parseGating = (s: string): GatingConfig =>
  ({ ...DEFAULT_GATING, ...(JSON.parse(s) as Partial<GatingConfig>) });
export const parseMultipliers = (s: string): PriorityMultipliers =>
  ({ ...DEFAULT_MULTIPLIERS, ...(JSON.parse(s) as PriorityMultipliers) });
```

- [ ] **Step 3: Test DB helper + failing test**

`src/server/engine/__tests__/testDb.ts`:

```ts
import { execSync } from "child_process";
import { PrismaClient } from "@prisma/client";
import { mkdtempSync } from "fs";
import { tmpdir } from "os";
import path from "path";
import { DEFAULT_GATING, DEFAULT_MULTIPLIERS } from "../defaults";

export function makeTestDb() {
  const dir = mkdtempSync(path.join(tmpdir(), "rfp-test-"));
  const url = `file:${path.join(dir, "test.db")}`;
  execSync("npx prisma db push --skip-generate", {
    env: { ...process.env, DATABASE_URL: url },
    stdio: "ignore",
  });
  return new PrismaClient({ datasources: { db: { url } } });
}

export async function makeProject(db: PrismaClient, name = "P", brief = "") {
  return db.project.create({
    data: {
      name, contextBrief: brief,
      gatingConfig: JSON.stringify(DEFAULT_GATING),
      priorityMultipliers: JSON.stringify(DEFAULT_MULTIPLIERS),
    },
  });
}
```

`src/server/engine/__tests__/schema.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { makeTestDb, makeProject } from "./testDb";
import { parseGating } from "../defaults";

describe("schema", () => {
  it("round-trips a project with defaults", async () => {
    const db = makeTestDb();
    const p = await makeProject(db, "ERP RFP");
    expect(parseGating(p.gatingConfig).gatePriorities).toEqual(["Must"]);
    await db.$disconnect();
  });

  it("enforces unique extId per project", async () => {
    const db = makeTestDb();
    const p = await makeProject(db);
    const cat = await db.category.create({
      data: { projectId: p.id, name: "Functional", defaultWeight: 100 },
    });
    const mk = () => db.requirement.create({
      data: { projectId: p.id, extId: "R-1", text: "x", categoryId: cat.id, priority: "Must" },
    });
    await mk();
    await expect(mk()).rejects.toThrow();
    await db.$disconnect();
  });
});
```

- [ ] **Step 4: Run** `npx prisma db push && npx vitest run src/server/engine/__tests__/schema.test.ts` — expect FAIL before schema edit, PASS after.

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: prisma schema, defaults, test db helper"`

---

### Task 3: Pure rollup engine + shared fixture

**Files:**
- Create: `src/server/engine/rollup.ts`, `src/server/engine/__tests__/rollup.test.ts`, `src/server/engine/__tests__/fixtures/rollup_fixture.json`

**Interfaces:**
- Produces (all pure, JSON-in/JSON-out, importable client-side in Phase 2):

```ts
export type ScoreInput = {
  requirementId: number; categoryId: number; priority: string;
  met: string; quality: number; responseCode: string; confidence: string;
};
export type RollupResult = {
  categoryScores: { id: number; name: string; weight: number; raw15: number;
                    weightedPoints: number; nScored: number }[];
  weightedTotal: number;
  gating: { disqualified: boolean; verdict: string | null;
            unmetGating: { requirementId: number; priority: string;
                           responseCode: string; met: string }[];
            summary: string };
};
export function rollup(scores, categories: {id:number;name:string}[],
  weights: Record<string, number>, multipliers: PriorityMultipliers,
  gating: GatingConfig): RollupResult;
export function rankVendors(rollups: Record<string, RollupResult>): string[];
```

- [ ] **Step 1: Fixture** — `fixtures/rollup_fixture.json`. Hand math: category 1 = (3·5 + 2·3 + 1·1)/6 = 3.67; category 2 has only requirement 4 (req 5 is N/A, excluded) = 4.0; total = 60·(3.67/5) + 40·(4.0/5) = 44.04 + 32.0 = 76.04. Req 3 is Could+GAP (Could doesn't gate); req 4 is Must+CUSTOM met=Yes (CUSTOM doesn't gate) → not disqualified.

```json
{
  "categories": [{"id": 1, "name": "Functional"}, {"id": 2, "name": "Technical"}],
  "weights": {"1": 60, "2": 40},
  "multipliers": {"Must": 3, "Should": 2, "Could": 1},
  "gating": {"gatePriorities": ["Must"], "gatingCodes": ["GAP", "ROADMAP"],
             "unmetMetValues": ["No"], "verdict": "Disqualified"},
  "scores": [
    {"requirementId": 1, "categoryId": 1, "priority": "Must",   "met": "Yes",     "quality": 5, "responseCode": "OOB",    "confidence": "High"},
    {"requirementId": 2, "categoryId": 1, "priority": "Should", "met": "Partial", "quality": 3, "responseCode": "CONFIG", "confidence": "Medium"},
    {"requirementId": 3, "categoryId": 1, "priority": "Could",  "met": "No",      "quality": 1, "responseCode": "GAP",    "confidence": "High"},
    {"requirementId": 4, "categoryId": 2, "priority": "Must",   "met": "Yes",     "quality": 4, "responseCode": "CUSTOM", "confidence": "Medium"},
    {"requirementId": 5, "categoryId": 2, "priority": "Must",   "met": "N/A",     "quality": 0, "responseCode": "GAP",    "confidence": "Low"}
  ],
  "expected": {"categoryRaw": {"1": 3.67, "2": 4.0}, "weightedTotal": 76.04, "disqualified": false}
}
```

- [ ] **Step 2: Failing tests** — `rollup.test.ts`: fixture category raws match; fixture weightedTotal matches; not disqualified; Must+No+GAP disqualifies with verdict "Disqualified" and the requirementId listed; Must+No+CUSTOM does NOT disqualify; adding a Wont+No+GAP row changes nothing; a category with no scores gets raw15 0; `rankVendors` puts a disqualified vendor last even with a higher total. (Same eight cases as the fixture's semantics — write them out as individual `it()` blocks asserting exact numbers.)

- [ ] **Step 3: Implement `rollup.ts`**

```ts
import type { GatingConfig, PriorityMultipliers } from "./defaults";

// (ScoreInput / RollupResult types exactly as in Interfaces above)

const round2 = (n: number) => Math.round(n * 100) / 100;

export function rollup(
  scores: ScoreInput[],
  categories: { id: number; name: string }[],
  weights: Record<string, number>,
  multipliers: PriorityMultipliers,
  gating: GatingConfig,
): RollupResult {
  const scorable = scores.filter((s) => s.priority !== "Wont" && s.met !== "N/A");

  let total = 0;
  const categoryScores = categories.map((cat) => {
    const subset = scorable.filter((s) => s.categoryId === cat.id);
    let num = 0, den = 0;
    for (const s of subset) {
      const w = multipliers[s.priority] ?? 1;
      num += w * s.quality;
      den += w;
    }
    const raw15 = den ? round2(num / den) : 0;
    const weight = weights[String(cat.id)] ?? 0;
    const weightedPoints = round2(weight * (raw15 / 5));
    total += weightedPoints;
    return { id: cat.id, name: cat.name, weight, raw15, weightedPoints, nScored: subset.length };
  });

  const unmetGating = scorable
    .filter((s) => gating.gatePriorities.includes(s.priority)
      && gating.unmetMetValues.includes(s.met)
      && gating.gatingCodes.includes(s.responseCode))
    .map(({ requirementId, priority, responseCode, met }) =>
      ({ requirementId, priority, responseCode, met }));

  const disqualified = unmetGating.length > 0;
  return {
    categoryScores,
    weightedTotal: round2(total),
    gating: {
      disqualified,
      verdict: disqualified ? gating.verdict : null,
      unmetGating,
      summary: disqualified
        ? `${unmetGating.length} unmet gating requirement(s)`
        : "All gating requirements satisfied",
    },
  };
}

export function rankVendors(rollups: Record<string, RollupResult>): string[] {
  return Object.keys(rollups).sort((a, b) => {
    const A = rollups[a]!, B = rollups[b]!;
    if (A.gating.disqualified !== B.gating.disqualified)
      return A.gating.disqualified ? 1 : -1;
    return B.weightedTotal - A.weightedTotal;
  });
}
```

- [ ] **Step 4: Run** `npx vitest run src/server/engine/__tests__/rollup.test.ts` → all pass.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: pure rollup engine with gating and shared fixture"`

---

### Task 4: Neutral persona + prompt builders

**Files:**
- Create: `config/persona.json`, `src/server/engine/persona.ts`, `src/server/engine/__tests__/persona.test.ts`

**Interfaces:**
- Produces: `buildPersonaPrompt(contextBrief: string): string` (persona + client context, injected as the system prompt on every LLM call) and `buildScoringContext(gating: GatingConfig): string` (quality scale, met values, response codes, MoSCoW, gating statement).

- [ ] **Step 1: `config/persona.json`** — domain-neutral evidence-first evaluator; same structure/content as the Flask plan's Task 4 persona (display_name "the RFP evaluation panel", decision_style, priorities_ranked, red_flags, weighting_doctrine, voice). Copy that JSON verbatim from `2026-07-17-generalized-rfp-fork-phase1.md` Task 4 Step 1.

- [ ] **Step 2: Failing tests** — prompt contains the context brief text and the word "evidence"; contains none of "HVAC", "OpCo", "Service Logic"; scoring context lists all seven response codes and states the gating rule with the project's actual gate priorities.

- [ ] **Step 3: Implement `persona.ts`**

```ts
import personaJson from "../../../config/persona.json";
import type { GatingConfig } from "./defaults";

export const QUALITY_SCALE: Record<string, string> = {
  "5": "Fully demonstrated, out-of-box or configured, with specifics",
  "4": "Demonstrated with minor caveats or light configuration",
  "3": "Partially demonstrated; material caveats or partner/extension needed",
  "2": "Claimed but unproven, custom build, or thin description",
  "1": "Roadmap, vague, or contradicted elsewhere in the response",
};
export const MET_VALUES = ["Yes", "Partial", "No", "N/A"] as const;
export const RESPONSE_CODES = ["OOB", "CONFIG", "EXTENSION", "CUSTOM", "PARTNER", "ROADMAP", "GAP"] as const;
export const CONFIDENCES = ["High", "Medium", "Low"] as const;

export function buildPersonaPrompt(contextBrief: string): string {
  const p = personaJson;
  const lines = [
    `You are ${p.display_name}.`, p.one_line,
    `\nDECISION STYLE: ${p.decision_style.summary}`,
    "\nPRIORITIES (ranked):",
    ...p.priorities_ranked.map((r) => `  ${r.rank}. ${r.name} — ${r.why}`),
    "\nRED FLAGS you actively penalize:",
    ...p.red_flags.map((f) => `  - ${f.flag}: ${f.trigger} (${f.penalty})`),
    `\nWEIGHTING DOCTRINE: ${p.weighting_doctrine.principle}`,
    `\nVOICE: ${p.voice.register}`,
    `ALWAYS: ${p.voice.do.join(" ")}`,
    `NEVER: ${p.voice.dont.join(" ")}`,
  ];
  if (contextBrief.trim())
    lines.push(`\nCLIENT CONTEXT (weigh every judgment against this):\n${contextBrief.trim()}`);
  lines.push(
    "\nGround every judgment in evidence from the response text. Reward proven " +
    "OOB/CONFIG over CUSTOM/ROADMAP. Never infer capabilities the response does not describe.",
  );
  return lines.join("\n");
}

export function buildScoringContext(g: GatingConfig): string {
  return [
    "RFP SCORING RULES:",
    "Quality scale (1-5): " + Object.entries(QUALITY_SCALE).map(([k, v]) => `${k}=${v}`).join("; "),
    "Met values: Yes | Partial | No | N/A",
    "Response codes: " + RESPONSE_CODES.join(", "),
    "MoSCoW: Must=mandatory; Should=important; Could=desirable; Wont=stored, never scored",
    `GATING (deterministic, not yours to decide): a requirement with priority in ` +
    `[${g.gatePriorities.join(", ")}] answered met in [${g.unmetMetValues.join(", ")}] ` +
    `with code in [${g.gatingCodes.join(", ")}] leads to ${g.verdict}.`,
  ].join("\n");
}
```

(Enable `resolveJsonModule` in tsconfig if not already on — t3 default has it.)

- [ ] **Step 4: Run tests** → pass. **Step 5: Commit** `feat: neutral persona and prompt builders`

---

### Task 5: Project & vendor tRPC routers

**Files:**
- Create: `src/server/api/routers/project.ts`, `src/server/api/routers/vendor.ts`, `src/server/api/__tests__/project.test.ts`
- Modify: `src/server/api/root.ts`

**Interfaces:**
- Produces procedures (all `publicProcedure` until Task 13 swaps in `protectedProcedure`):
  - `project.list` → projects with `_count` of requirements/vendors
  - `project.create({name, client?, contextBrief?})` → project (gating/multiplier defaults applied)
  - `project.get({projectId})` → `{project, categories, nRequirements, activeWeights}` — throws TRPCError NOT_FOUND
  - `project.update({projectId, name?, client?, contextBrief?, status?, gatingConfig?, priorityMultipliers?})`
  - `vendor.list({projectId})`, `vendor.create({projectId, name, dossierText?})` (CONFLICT on dup), `vendor.delete({projectId, vendorId})`
- Also produces the helper used everywhere: `activeWeights(db, projectId)` in `src/server/engine/weights.ts` — active WeightProfile's weights, else category defaultWeights.

- [ ] **Step 1: `src/server/engine/weights.ts`**

```ts
import type { PrismaClient } from "@prisma/client";

export async function activeWeights(db: PrismaClient, projectId: number) {
  const profile = await db.weightProfile.findFirst({
    where: { projectId, isActive: true }, orderBy: { id: "desc" },
  });
  if (profile) return JSON.parse(profile.weights) as Record<string, number>;
  const cats = await db.category.findMany({ where: { projectId } });
  return Object.fromEntries(cats.map((c) => [String(c.id), c.defaultWeight]));
}
```

- [ ] **Step 2: Failing tests** — `project.test.ts` uses `createCallerFactory` with a test context whose `db` is `makeTestDb()`:

```ts
import { describe, it, expect } from "vitest";
import { appRouter } from "~/server/api/root";
import { createCallerFactory } from "~/server/api/trpc";
import { makeTestDb } from "~/server/engine/__tests__/testDb";

const caller = () => createCallerFactory(appRouter)({ db: makeTestDb(), session: null, headers: new Headers() });

describe("project router", () => {
  it("creates and lists", async () => {
    const c = caller();
    const p = await c.project.create({ name: "ERP RFP", client: "Acme" });
    const list = await c.project.list();
    expect(list.some((x) => x.id === p.id)).toBe(true);
  });
  it("get 404s on missing", async () => {
    await expect(caller().project.get({ projectId: 999 })).rejects.toMatchObject({ code: "NOT_FOUND" });
  });
  it("update patches contextBrief and gatingConfig", async () => {
    const c = caller();
    const p = await c.project.create({ name: "X" });
    const u = await c.project.update({
      projectId: p.id, contextBrief: "New brief",
      gatingConfig: { gatePriorities: ["Must", "Should"], gatingCodes: ["GAP"], unmetMetValues: ["No"], verdict: "Reject" },
    });
    expect(u.contextBrief).toBe("New brief");
    expect(JSON.parse(u.gatingConfig).verdict).toBe("Reject");
  });
  it("vendor CRUD with duplicate conflict", async () => {
    const c = caller();
    const p = await c.project.create({ name: "X" });
    await c.vendor.create({ projectId: p.id, name: "VendorA" });
    await expect(c.vendor.create({ projectId: p.id, name: "VendorA" }))
      .rejects.toMatchObject({ code: "CONFLICT" });
    const v = (await c.vendor.list({ projectId: p.id }))[0]!;
    await c.vendor.delete({ projectId: p.id, vendorId: v.id });
    expect(await c.vendor.list({ projectId: p.id })).toHaveLength(0);
  });
});
```

Adjust the context object to match the t3 scaffold's `createTRPCContext` return shape (check `src/server/api/trpc.ts` — pass whatever fields it defines, with `db` overridden).

- [ ] **Step 3: Implement routers** — `project.ts`:

```ts
import { z } from "zod";
import { TRPCError } from "@trpc/server";
import { createTRPCRouter, publicProcedure } from "~/server/api/trpc";
import { DEFAULT_GATING, DEFAULT_MULTIPLIERS } from "~/server/engine/defaults";
import { activeWeights } from "~/server/engine/weights";

const gatingSchema = z.object({
  gatePriorities: z.array(z.string()),
  gatingCodes: z.array(z.string()),
  unmetMetValues: z.array(z.string()),
  verdict: z.enum(["Disqualified", "Reject"]),
});

export const projectRouter = createTRPCRouter({
  list: publicProcedure.query(({ ctx }) =>
    ctx.db.project.findMany({
      orderBy: { createdAt: "desc" },
      include: { _count: { select: { requirements: true, vendors: true } } },
    })),

  create: publicProcedure
    .input(z.object({ name: z.string().min(1), client: z.string().default(""), contextBrief: z.string().default("") }))
    .mutation(({ ctx, input }) =>
      ctx.db.project.create({ data: {
        ...input,
        gatingConfig: JSON.stringify(DEFAULT_GATING),
        priorityMultipliers: JSON.stringify(DEFAULT_MULTIPLIERS),
      }})),

  get: publicProcedure.input(z.object({ projectId: z.number() }))
    .query(async ({ ctx, input }) => {
      const project = await ctx.db.project.findUnique({
        where: { id: input.projectId },
        include: { categories: { orderBy: { sortOrder: "asc" } } },
      });
      if (!project) throw new TRPCError({ code: "NOT_FOUND", message: "project not found" });
      const nRequirements = await ctx.db.requirement.count({ where: { projectId: project.id } });
      return { project, categories: project.categories, nRequirements,
               activeWeights: await activeWeights(ctx.db, project.id) };
    }),

  update: publicProcedure
    .input(z.object({
      projectId: z.number(),
      name: z.string().min(1).optional(), client: z.string().optional(),
      contextBrief: z.string().optional(), status: z.string().optional(),
      gatingConfig: gatingSchema.optional(),
      priorityMultipliers: z.record(z.string(), z.number()).optional(),
    }))
    .mutation(async ({ ctx, input }) => {
      const { projectId, gatingConfig, priorityMultipliers, ...rest } = input;
      try {
        return await ctx.db.project.update({
          where: { id: projectId },
          data: { ...rest,
            ...(gatingConfig && { gatingConfig: JSON.stringify(gatingConfig) }),
            ...(priorityMultipliers && { priorityMultipliers: JSON.stringify(priorityMultipliers) }),
          },
        });
      } catch { throw new TRPCError({ code: "NOT_FOUND", message: "project not found" }); }
    }),
});
```

`vendor.ts` follows the same shape (create catches Prisma `P2002` → `CONFLICT`). Wire both into `root.ts`.

- [ ] **Step 4: Run** `npx vitest run src/server/api/__tests__/project.test.ts` → pass.
- [ ] **Step 5: Commit** `feat: project and vendor routers with weights helper`

---

### Task 6: Excel template (exceljs) + download route

**Files:**
- Create: `src/server/engine/intake.ts` (template half), `src/app/api/template/route.ts`, `src/server/engine/__tests__/intake.test.ts`

**Interfaces:**
- Produces: `buildTemplate(): Promise<Buffer>` — workbook with "Categories" (`Category | Description | Weight`), "Requirements" (`ID | Requirement | Category | Priority | Section | Notes`), and "How to fill this in" sheets, styled header rows, two example rows each; route `GET /api/template` streaming it as `rfp_requirements_template.xlsx`.

- [ ] **Step 1: Failing test** — load `await buildTemplate()` back with exceljs, assert sheet names and header rows exactly.

- [ ] **Step 2: Implement**

```ts
import ExcelJS from "exceljs";

const HEADER_FILL: ExcelJS.Fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FF1F3B57" } };

function addHeader(ws: ExcelJS.Worksheet, cols: string[]) {
  const row = ws.addRow(cols);
  row.eachCell((c) => { c.fill = HEADER_FILL; c.font = { color: { argb: "FFFFFFFF" }, bold: true }; });
}

export async function buildTemplate(): Promise<Buffer> {
  const wb = new ExcelJS.Workbook();
  const cats = wb.addWorksheet("Categories");
  addHeader(cats, ["Category", "Description", "Weight"]);
  cats.addRow(["Functional fit", "Coverage of day-to-day operational needs", 60]);
  cats.addRow(["Technical & architecture", "Integration, security, scalability", 40]);

  const reqs = wb.addWorksheet("Requirements");
  addHeader(reqs, ["ID", "Requirement", "Category", "Priority", "Section", "Notes"]);
  reqs.addRow(["R-001", "Support multi-entity general ledger", "Functional fit", "Must", "Finance", ""]);
  reqs.addRow(["", "Provide REST APIs for all core objects", "Technical & architecture", "Should", "Integration", "ID auto-generated when blank"]);

  const guide = wb.addWorksheet("How to fill this in");
  [
    "Categories sheet: one row per scoring category. Weights must sum to 100.",
    "Requirements sheet: one row per requirement.",
    "Category must exactly match a row on the Categories sheet.",
    "Priority must be one of: Must, Should, Could, Won't.",
    "Won't rows are stored for completeness but never scored.",
    "ID is optional; blank IDs are auto-generated (R-001, R-002, ...).",
  ].forEach((l) => guide.addRow([l]));

  return Buffer.from(await wb.xlsx.writeBuffer());
}
```

`src/app/api/template/route.ts`:

```ts
import { buildTemplate } from "~/server/engine/intake";

export async function GET() {
  const buf = await buildTemplate();
  return new Response(new Uint8Array(buf), { headers: {
    "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "Content-Disposition": "attachment; filename=rfp_requirements_template.xlsx",
  }});
}
```

- [ ] **Step 3: Run tests** → pass. Manually hit http://localhost:3000/api/template once, open the file.
- [ ] **Step 4: Commit** `feat: excel requirements template and download route`

---

### Task 7: Intake — parse, validate, preview, confirm

**Files:**
- Modify: `src/server/engine/intake.ts`; Create: `src/server/api/routers/intake.ts`, `src/app/api/projects/[id]/intake/route.ts`; extend `src/server/engine/__tests__/intake.test.ts`

**Interfaces:**
- `parseWorkbook(buf: Buffer): Promise<ParsedIntake>` where `ParsedIntake = { categories: {name;description;weight}[]; requirements: {extId;text;category;priority;sectionLabel;notes}[]; errors: string[]; warnings: string[]; summary: {nRequirements;nCategories;byPriority:Record<string,number>;weightSum:number} }`. Never throws on bad content. Priority normalization `won't/wont → Wont` (case-insensitive Must/Should/Could too). Blank IDs auto-generate `R-001…` skipping used ones. Errors (exact substrings the tests assert): `weights sum to {n}, must sum to 100`, `missing requirement text`, `unknown category '{name}'`, `invalid priority '{p}'`, `duplicate ID '{id}'`, `missing sheet '{name}'`, `could not read file as .xlsx`.
- `commitIntake(db, projectId, parsed): Promise<{nCategories;nRequirements;weightProfileId}>` — one `db.$transaction`; first weight profile named "Uploaded defaults", `isActive: true`; throws if `parsed.errors.length` or project already has requirements.
- Route `POST /api/projects/[id]/intake` — multipart `file` field; 400 on missing/empty (message names the OneDrive-placeholder cause) or >10 MB; returns the `ParsedIntake` JSON. tRPC `intake.confirm({projectId, parsed, replace?})` — CONFLICT when requirements exist and `replace` is false; with `replace: true` deletes evaluations/weightProfiles/requirements/categories first.

- [ ] **Step 1: Failing tests** — build workbooks in-test with exceljs (helper `wbBytes(cats, reqs)`); port the seven Flask-plan intake cases: parse-good (auto-ID `R-001`, `Wont` normalized, weightSum 100), parse-flags-all-five-problems, garbage bytes → error not throw, commit writes rows + active "Uploaded defaults" profile with weights {60,40}, commit refuses second upload, confirm CONFLICT then replace succeeds (confirm tests via `createCallerFactory` like Task 5).

- [ ] **Step 2: Implement `parseWorkbook`/`commitIntake`** — straight port of the Flask plan's Task 7 logic to exceljs (`wb.xlsx.load(buf)`; iterate `ws.eachRow` skipping row 1; `cell.text` for values). Keep the error strings exactly as listed in Interfaces.

- [ ] **Step 3: Route handler**

```ts
import { NextRequest } from "next/server";
import { db } from "~/server/db";
import { parseWorkbook } from "~/server/engine/intake";

export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const project = await db.project.findUnique({ where: { id: Number(id) } });
  if (!project) return Response.json({ error: "project not found" }, { status: 404 });
  const form = await req.formData();
  const file = form.get("file");
  if (!(file instanceof File)) return Response.json({ error: "file is required" }, { status: 400 });
  if (file.size === 0)
    return Response.json({ error: "file is empty (OneDrive online-only placeholder? copy it locally first)" }, { status: 400 });
  if (file.size > 10 * 1024 * 1024)
    return Response.json({ error: "file exceeds 10 MB limit" }, { status: 400 });
  return Response.json(await parseWorkbook(Buffer.from(await file.arrayBuffer())));
}
```

- [ ] **Step 4: Run all intake tests** → pass. **Step 5: Commit** `feat: excel intake with validate/preview/confirm and replace guard`

---

### Task 8: LLM provider layer + model registry

**Files:**
- Create: `src/server/engine/models.ts`, `src/server/engine/providers.ts`, `src/server/engine/__tests__/providers.test.ts`

**Interfaces:**
- `models.ts`: `MODELS: ModelInfo[]` (`{id, label, provider: "anthropic"|"openai"|"mock", envKey?}`), `TASK_DEFAULTS = {scoring: "claude-sonnet-5", vote: "claude-opus-4-8", chat: "claude-haiku-4-5"}`, `availableModels(): (ModelInfo & {available: boolean})[]` (available = mock, or env key present), `isMock(id)`.
- `providers.ts`: `generateJson(opts: {system: string; user: string; modelId: string; schema: object; maxTokens?: number}): Promise<unknown>` — returns parsed JSON matching the schema, or **throws `ProviderError`** with a clear message (missing key, SDK error, refusal). Never called for mock (callers branch on `isMock` first).

- [ ] **Step 1: `models.ts`**

```ts
export type ModelInfo = { id: string; label: string; provider: "anthropic" | "openai" | "mock"; envKey?: string };

export const MODELS: ModelInfo[] = [
  { id: "mock", label: "Offline mock engine", provider: "mock" },
  { id: "claude-opus-4-8", label: "Claude Opus 4.8", provider: "anthropic", envKey: "ANTHROPIC_API_KEY" },
  { id: "claude-sonnet-5", label: "Claude Sonnet 5", provider: "anthropic", envKey: "ANTHROPIC_API_KEY" },
  { id: "claude-haiku-4-5", label: "Claude Haiku 4.5", provider: "anthropic", envKey: "ANTHROPIC_API_KEY" },
  { id: "gpt-4o", label: "GPT-4o", provider: "openai", envKey: "OPENAI_API_KEY" },
  { id: "gpt-4o-mini", label: "GPT-4o mini", provider: "openai", envKey: "OPENAI_API_KEY" },
];
export const TASK_DEFAULTS = { scoring: "claude-sonnet-5", vote: "claude-opus-4-8", chat: "claude-haiku-4-5" };
export const isMock = (id: string) => id === "mock";
export const availableModels = () =>
  MODELS.map((m) => ({ ...m, available: !m.envKey || Boolean(process.env[m.envKey]) }));
```

- [ ] **Step 2: `providers.ts`**

```ts
import Anthropic from "@anthropic-ai/sdk";
import OpenAI from "openai";
import { MODELS } from "./models";

export class ProviderError extends Error {}

export async function generateJson(opts: {
  system: string; user: string; modelId: string; schema: Record<string, unknown>; maxTokens?: number;
}): Promise<unknown> {
  const model = MODELS.find((m) => m.id === opts.modelId);
  if (!model || model.provider === "mock")
    throw new ProviderError(`not a live model: ${opts.modelId}`);
  if (model.envKey && !process.env[model.envKey])
    throw new ProviderError(`${model.envKey} is not set — add it to the environment to use ${model.label}`);
  const maxTokens = opts.maxTokens ?? 8192;

  if (model.provider === "anthropic") {
    const client = new Anthropic();
    const response = await client.messages.create({
      model: model.id,
      max_tokens: maxTokens,
      system: opts.system,
      output_config: { format: { type: "json_schema", schema: opts.schema } },
      messages: [{ role: "user", content: opts.user }],
    });
    if (response.stop_reason === "refusal")
      throw new ProviderError("model declined the request");
    const text = response.content.find((b) => b.type === "text");
    if (!text) throw new ProviderError("no text block in response");
    return JSON.parse(text.text);
  }

  // openai
  const client = new OpenAI();
  const completion = await client.chat.completions.create({
    model: model.id,
    max_tokens: maxTokens,
    response_format: { type: "json_object" },
    messages: [
      { role: "system", content: opts.system + "\nRespond with a single JSON object." },
      { role: "user", content: opts.user },
    ],
  });
  const content = completion.choices[0]?.message?.content;
  if (!content) throw new ProviderError("empty completion");
  return JSON.parse(content);
}
```

- [ ] **Step 3: Tests** (no network): `availableModels()` marks mock available always and Claude models unavailable when `ANTHROPIC_API_KEY` unset; `generateJson` with an unset key rejects with a ProviderError whose message names the env var; `isMock("mock")` true.

- [ ] **Step 4: Run tests** → pass. **Step 5: Commit** `feat: model registry and anthropic/openai provider layer`

---

### Task 9: Retrieval + batched scoring engine

**Files:**
- Create: `src/server/engine/retrieval.ts`, `src/server/engine/scoring.ts`, `src/server/engine/__tests__/scoring.test.ts`

**Interfaces:**
- `retrieval.ts`: `buildIndex(text: string, targetChars = 1200): Chunk[]` (paragraph-merge chunking) and `relevantPassages(chunks, query, k): string[]` (term-overlap ranking; terms = lowercase words len > 3). Port of the parent's `ingest.py` logic, no deps.
- `scoring.ts`:

```ts
export type ReqRow = { id: number; extId: string; categoryId: number; priority: string; text: string };
export type ScoreRow = {
  requirementId: number; extId: string; categoryId: number; priority: string;
  met: string; quality: number; responseCode: string; confidence: string;
  rationale: string; evidenceGap: string; scoredLive: boolean;
};
export async function scoreRequirements(opts: {
  requirements: ReqRow[];            // caller pre-filters Wont
  vendorName: string;
  proposalText: string;
  modelId: string;
  system: string;                    // buildPersonaPrompt + buildScoringContext, joined
  onBatch: (batch: ScoreRow[]) => Promise<void>;   // persistence hook — resumability
  isCancelled?: () => boolean;
}): Promise<{ scores: ScoreRow[]; live: number; fallback: number }>;
export function mockScore(req: ReqRow, proposalText: string): ScoreRow;  // exported for tests
```

Batches of 12. Live batches call `generateJson` with a strict schema; any provider error falls the batch back to `mockScore` and counts `fallback`. Mock model: never counts live or fallback.

- [ ] **Step 1: Failing tests** — mock scoring covers all rows, deterministic (two runs deep-equal), rewards overlap (proposal echoing a requirement's words scores met Yes/Partial, quality ≥ 3; unrelated text scores GAP/No), `onBatch` called with batches summing to the row count, `isCancelled` stops between batches (fewer scores than rows), all outputs within the allowed enums.

- [ ] **Step 2: Implement.** `mockScore` — deterministic term-overlap heuristic, direct port of the Flask plan's `_mock_score` (overlap = hits/terms; stable jitter from a SHA-1 of `extId|proposalText.slice(0,64)` via `node:crypto`; thresholds 0.55/0.35/0.2 → OOB-Yes / CONFIG-Partial / CUSTOM-Partial / GAP-No; confidence from overlap 0.5/0.25). `scoreRequirements` — loop batches; live path builds the user prompt (top-8 relevant passages for the batch's combined text, capped 8000 chars, plus `id | extId | priority | text` lines) and this response schema:

```ts
const BATCH_SCHEMA = {
  type: "object", additionalProperties: false, required: ["rows"],
  properties: { rows: { type: "array", items: {
    type: "object", additionalProperties: false,
    required: ["internalId", "met", "quality", "responseCode", "confidence", "rationale", "evidenceGap"],
    properties: {
      internalId: { type: "integer" },
      met: { type: "string", enum: ["Yes", "Partial", "No", "N/A"] },
      quality: { type: "integer", enum: [1, 2, 3, 4, 5] },
      responseCode: { type: "string", enum: ["OOB", "CONFIG", "EXTENSION", "CUSTOM", "PARTNER", "ROADMAP", "GAP"] },
      confidence: { type: "string", enum: ["High", "Medium", "Low"] },
      rationale: { type: "string" },
      evidenceGap: { type: "string" },
    },
  }}},
} as const;
```

User prompt ends: `Score ONLY from the excerpts. A requirement the excerpts never address is GAP / No.` Rows are matched back by `internalId`; any requirement the model skipped gets `mockScore`. Clamp/validate every field defensively even though the schema is strict.

- [ ] **Step 3: Run tests** → pass. **Step 4: Commit** `feat: retrieval index and batched scoring with deterministic mock engine`

---

### Task 10: Vote — deterministic bands + narrative

**Files:**
- Create: `src/server/engine/vote.ts`, `src/server/engine/__tests__/vote.test.ts`

**Interfaces:**
- `band(total: number): "Recommend" | "Shortlist" | "Reject"` — ≥70 / ≥55 / else.
- `synthesizeVote(opts: {vendorName; roll: RollupResult; scores: ScoreRow[]; modelId: string; system: string}): Promise<Vote>` where `Vote = {recommendation; confidence; narrative; dissent; topRisks: string[]; evidenceToClose: string[]}`. Gating verdict always wins over the band. Mock (or any provider failure): template narrative built from the numbers. LLM path: findings JSON + instruction that the recommendation is fixed; schema `{narrative, dissent, topRisks}`.

- [ ] **Step 1: Failing tests** — band boundaries (70→Recommend, 55→Shortlist, 54.99→Reject); disqualified roll with weightedTotal 90 → recommendation "Disqualified"; mock vote has non-empty narrative + dissent and topRisks array; provider failure (unset key, live model id) falls back to the mock narrative rather than throwing.

- [ ] **Step 2: Implement** — port of the Flask plan's Task 9 `vote.py` to TS: findings = `{vendorName, recommendation, reason, weightedTotal, weakestCategories (2 lowest raw15), unmetGating, sampleEvidenceGaps (first 5)}`; `_mock` narrative template; LLM call via `generateJson` wrapped in try/catch → mock fallback. `evidenceToClose` = first 3 evidence gaps.

- [ ] **Step 3: Run tests** → pass. **Step 4: Commit** `feat: vote with deterministic bands and LLM narrative fallback`

---

### Task 11: Evaluation jobs + evaluation router (resumable, weight-aware results)

**Files:**
- Create: `src/server/engine/jobs.ts`, `src/server/api/routers/evaluation.ts`, `src/server/api/__tests__/evaluation.test.ts`
- Modify: `src/server/api/root.ts`

**Interfaces:**
- `jobs.ts`: `startEvaluation(db, opts: {projectId; vendorId; proposalText; scoringModel; voteModel}): string` (returns jobId; runs async), `getJob(jobId): JobState | undefined` (`{status: "running"|"done"|"failed"|"cancelled"; progress: number; message: string; evaluationId?: number}`), `cancelJob(jobId)`. Registry: `const jobs = (globalThis.__rfpJobs ??= new Map())`.
- Runner semantics (the resumability contract):
  1. Reuse the vendor's latest `failed`/`cancelled` evaluation row (set back to running) else create one (`isDemo` = scoringModel === "mock").
  2. Load existing `RequirementScore` rows for that evaluation; score only the non-Wont requirements not already scored.
  3. `onBatch` upserts each score row (`db.requirementScore.upsert`) and bumps progress.
  4. After scoring: rollup from ALL stored scores + `activeWeights` + project gating/multipliers → `synthesizeVote` → save vote JSON, status "done" → delete the vendor's OTHER `done` evaluations (re-eval replaces on completion).
  5. Any throw → status "failed" on both job and row; fallback count > 0 on a live model → `engineWarning`.
- `evaluation.ts` router: `evaluation.start({projectId, vendorId, proposalText, scoringModel, voteModel})` → `{jobId}` (BAD_REQUEST if vendor not in project or project has no requirements); `evaluation.status({jobId})`; `evaluation.cancel({jobId})`; `evaluation.results({projectId})` → `{results: [{evaluationId, vendor, weightedTotal, categoryScores, gating, vote, requirementScores, nScores, isDemo, engineWarning, createdAt}], ranking: string[]}` — **rollup computed on read** from stored scores and the CURRENT active weight profile, so results always reflect current weights.

- [ ] **Step 1: Failing tests** — seed a project via `commitIntake` (reuse the intake test workbook helper: 2 categories 60/40, 3 requirements incl. one Wont), add a vendor, then: (a) mock evaluation end-to-end — poll `getJob` until done (test helper with 10s timeout), results show 1 vendor, nScores 2 (Wont excluded), vote recommendation within the enum, ranking = [vendor]; (b) results reflect weights — insert a new active WeightProfile flipping to {cat2: 100} and assert `weightedTotal` changes without re-evaluating; (c) start with bad vendorId → BAD_REQUEST; (d) resume — mark the evaluation failed, delete one score row, start again for the same vendor: same evaluationId reused and the missing row restored.

- [ ] **Step 2: Implement `jobs.ts`**

```ts
import type { PrismaClient } from "@prisma/client";
import { randomUUID } from "crypto";
import { rollup } from "./rollup";
import { scoreRequirements, type ScoreRow } from "./scoring";
import { synthesizeVote } from "./vote";
import { buildPersonaPrompt, buildScoringContext } from "./persona";
import { parseGating, parseMultipliers } from "./defaults";
import { activeWeights } from "./weights";
import { isMock } from "./models";

export type JobState = { status: "running" | "done" | "failed" | "cancelled";
  progress: number; message: string; evaluationId?: number; cancelled: boolean };

const jobs: Map<string, JobState> =
  ((globalThis as Record<string, unknown>).__rfpJobs as Map<string, JobState>) ??
  ((globalThis as Record<string, unknown>).__rfpJobs = new Map());

export const getJob = (id: string) => jobs.get(id);
export const cancelJob = (id: string) => { const j = jobs.get(id); if (j) j.cancelled = true; };

export function startEvaluation(db: PrismaClient, opts: {
  projectId: number; vendorId: number; proposalText: string;
  scoringModel: string; voteModel: string;
}): string {
  const jobId = randomUUID().slice(0, 12);
  const job: JobState = { status: "running", progress: 0, message: "", cancelled: false };
  jobs.set(jobId, job);
  void run(db, opts, job).catch((e: unknown) => {
    job.status = "failed";
    job.message = e instanceof Error ? e.message : String(e);
  });
  return jobId;
}

async function run(db: PrismaClient, opts: Parameters<typeof startEvaluation>[1], job: JobState) {
  const project = await db.project.findUniqueOrThrow({
    where: { id: opts.projectId }, include: { categories: true } });
  const vendor = await db.vendor.findUniqueOrThrow({ where: { id: opts.vendorId } });
  const gating = parseGating(project.gatingConfig);
  const multipliers = parseMultipliers(project.priorityMultipliers);

  let evaluation = await db.evaluation.findFirst({
    where: { projectId: project.id, vendorId: vendor.id, status: { in: ["failed", "cancelled"] } },
    orderBy: { id: "desc" },
  });
  if (evaluation) {
    evaluation = await db.evaluation.update({ where: { id: evaluation.id }, data: { status: "running" } });
  } else {
    evaluation = await db.evaluation.create({ data: {
      projectId: project.id, vendorId: vendor.id, status: "running",
      scoringModel: opts.scoringModel, voteModel: opts.voteModel,
      isDemo: isMock(opts.scoringModel), proposalText: opts.proposalText.slice(0, 200_000),
    }});
  }
  job.evaluationId = evaluation.id;

  const already = new Set((await db.requirementScore.findMany({
    where: { evaluationId: evaluation.id }, select: { requirementId: true },
  })).map((r) => r.requirementId));
  const allReqs = await db.requirement.findMany({
    where: { projectId: project.id, priority: { not: "Wont" } } });
  const pending = allReqs.filter((r) => !already.has(r.id));
  const system = buildPersonaPrompt(project.contextBrief) + "\n\n" + buildScoringContext(gating);

  const { fallback } = await scoreRequirements({
    requirements: pending.map((r) => ({ id: r.id, extId: r.extId, categoryId: r.categoryId,
      priority: r.priority, text: r.text })),
    vendorName: vendor.name, proposalText: opts.proposalText,
    modelId: opts.scoringModel, system,
    isCancelled: () => job.cancelled,
    onBatch: async (batch: ScoreRow[]) => {
      for (const s of batch) {
        await db.requirementScore.upsert({
          where: { evaluationId_requirementId: { evaluationId: evaluation.id, requirementId: s.requirementId } },
          create: { evaluationId: evaluation.id, requirementId: s.requirementId, met: s.met,
            quality: s.quality, responseCode: s.responseCode, confidence: s.confidence,
            rationale: s.rationale, evidenceGap: s.evidenceGap, scoredLive: s.scoredLive },
          update: { met: s.met, quality: s.quality, responseCode: s.responseCode,
            confidence: s.confidence, rationale: s.rationale, evidenceGap: s.evidenceGap,
            scoredLive: s.scoredLive },
        });
      }
      job.progress = Math.min(0.9, job.progress + (0.9 * batch.length) / Math.max(1, allReqs.length));
    },
  });

  if (job.cancelled) {
    await db.evaluation.update({ where: { id: evaluation.id }, data: { status: "cancelled" } });
    job.status = "cancelled"; return;
  }
  if (fallback > 0 && !isMock(opts.scoringModel)) {
    await db.evaluation.update({ where: { id: evaluation.id },
      data: { engineWarning: `${fallback} requirement(s) fell back to the offline engine` } });
  }

  const stored = await db.requirementScore.findMany({
    where: { evaluationId: evaluation.id }, include: { requirement: true } });
  const roll = rollup(
    stored.map((s) => ({ requirementId: s.requirementId, categoryId: s.requirement.categoryId,
      priority: s.requirement.priority, met: s.met, quality: s.quality,
      responseCode: s.responseCode, confidence: s.confidence })),
    project.categories, await activeWeights(db, project.id), multipliers, gating,
  );
  const vote = await synthesizeVote({
    vendorName: vendor.name, roll,
    scores: stored.map((s) => ({ requirementId: s.requirementId, extId: s.requirement.extId,
      categoryId: s.requirement.categoryId, priority: s.requirement.priority, met: s.met,
      quality: s.quality, responseCode: s.responseCode, confidence: s.confidence,
      rationale: s.rationale, evidenceGap: s.evidenceGap, scoredLive: s.scoredLive })),
    modelId: opts.voteModel, system: buildPersonaPrompt(project.contextBrief),
  });

  await db.evaluation.update({ where: { id: evaluation.id },
    data: { status: "done", vote: JSON.stringify(vote) } });
  await db.evaluation.deleteMany({ where: {
    projectId: project.id, vendorId: vendor.id, status: "done", id: { not: evaluation.id } } });
  job.status = "done"; job.progress = 1;
}
```

- [ ] **Step 3: Implement the router** — thin wrappers over jobs.ts plus `results` (query all `done` evaluations with vendor + scores + requirement, compute rollup per vendor with current `activeWeights`, `rankVendors` for the ranking). Validation errors as TRPCError BAD_REQUEST. Wire into `root.ts`.

- [ ] **Step 4: Run** `npx vitest run` (full suite) → all pass. **Step 5: Commit** `feat: resumable evaluation jobs and weight-aware results`

---

### Task 12: Chat router

**Files:**
- Create: `src/server/api/routers/chat.ts`, `src/server/api/__tests__/chat.test.ts`; Modify: `root.ts`

**Interfaces:**
- `chat.ask({projectId, question, modelId})` → `{answer: string}`. Context assembled server-side: context brief + top-10 requirements matching the question (reuse `buildIndex`/`relevantPassages` over `extId: text` lines) + per-vendor result lines (`{name}: {weightedTotal}/100, {vote.recommendation}` + gating summary) from the same rollup-on-read logic as `evaluation.results`. Mock model: deterministic answer echoing the retrieved context ("Based on the current evaluations: ..."); live models: `generateJson` with schema `{answer: string}`, provider failure → mock answer.

- [ ] **Step 1: Test** — seed project + mock evaluation (reuse Task 11 helpers), `chat.ask` with model "mock" returns an answer containing the vendor name. Run → fail.
- [ ] **Step 2: Implement + wire.** Run → pass.
- [ ] **Step 3: Commit** `feat: project-scoped retrieval chat`

---

### Task 13: Auth.js credentials login

**Files:**
- Create: `src/server/auth.ts`, `src/app/login/page.tsx`, `src/app/api/auth/[...nextauth]/route.ts`, `scripts/create-user.ts`, `src/middleware.ts`
- Modify: `src/server/api/trpc.ts` (add `protectedProcedure`), all routers (swap `publicProcedure` → `protectedProcedure`), route handlers (session check)

**Interfaces:**
- Auth.js v5 (`next-auth@beta`) credentials provider validating against the `User` table with bcrypt (`npm i next-auth@beta bcryptjs && npm i -D @types/bcryptjs`). JWT session strategy (no adapter needed). `scripts/create-user.ts` — `npx tsx scripts/create-user.ts email password [name]` upserts a user (bcrypt, 12 rounds).
- `src/middleware.ts` redirects unauthenticated page requests to `/login` (matcher excludes `/login`, `/api/auth`, `_next`, favicon). `protectedProcedure` throws UNAUTHORIZED without a session. The intake/template route handlers call `auth()` and 401 without a session.
- Test-mode: `AUTH_DISABLED=1` env makes `protectedProcedure` and the route handlers skip the check — used by the existing Vitest suites (set in `vitest.config.ts` `test.env`).

- [ ] **Step 1:** Set `AUTH_DISABLED: "1"` in vitest config env, add the guard first, and confirm the full existing suite still passes after the `protectedProcedure` swap.
- [ ] **Step 2:** Implement `src/server/auth.ts`:

```ts
import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import bcrypt from "bcryptjs";
import { db } from "~/server/db";

export const { handlers, auth, signIn, signOut } = NextAuth({
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  providers: [
    Credentials({
      credentials: { email: {}, password: {} },
      authorize: async (creds) => {
        const email = String(creds?.email ?? "").toLowerCase().trim();
        const user = await db.user.findUnique({ where: { email } });
        if (!user) return null;
        const ok = await bcrypt.compare(String(creds?.password ?? ""), user.passwordHash);
        return ok ? { id: String(user.id), email: user.email, name: user.name } : null;
      },
    }),
  ],
});
```

Route handler re-exports `handlers`; login page is a simple email/password form calling `signIn("credentials", ...)`; middleware uses `auth` as documented for Auth.js v5. Verify exact v5 wiring against the installed `next-auth@beta` version's docs (Context7/`next-auth` docs) before writing — v5 APIs have shifted between betas.

- [ ] **Step 3:** Manual check — `npx tsx scripts/create-user.ts me@example.com temp123`, `npm run dev`, hitting `/` redirects to `/login`, logging in lands on the picker. Full test suite green.
- [ ] **Step 4: Commit** `feat: credentials auth with protected procedures and routes`

---

### Task 14: UI — project screens (Tailwind + tRPC hooks)

No component test runner in Phase 1 — verification is the E2E script in Task 15 plus manual clicks. Keep components small; one file each under `src/components/`.

**Files:**
- Modify: `src/app/layout.tsx`, `src/app/page.tsx`
- Create: `src/app/projects/[id]/page.tsx`, `src/components/ProjectPicker.tsx`, `src/components/IntakeWizard.tsx`, `src/components/VendorPanel.tsx`, `src/components/EvaluatePanel.tsx`, `src/components/ResultsDashboard.tsx`, `src/components/VendorDetail.tsx`, `src/components/ChatPanel.tsx`

**Interfaces:**
- Consumes every router from Tasks 5–13 via the t3 `api` React hooks (`~/trpc/react`).
- Routing IS the project selection: `/` = picker, `/projects/[id]` = workspace with four tabs (Setup | Evaluate | Results | Chat) driven by a `useState` tab. No global active-project state anywhere.

- [ ] **Step 1: `ProjectPicker`** (used by `src/app/page.tsx`) — `api.project.list.useQuery()`; card per project (name, client, counts) linking to `/projects/{id}`; "New project" form (name, client, context brief textarea) calling `api.project.create.useMutation` then `router.push`.

- [ ] **Step 2: `IntakeWizard`** — the one component with non-obvious flow, so the shape is specified here:

```tsx
"use client";
import { useState } from "react";
import { api } from "~/trpc/react";

type Parsed = {
  categories: unknown[]; requirements: unknown[]; errors: string[];
  summary: { nRequirements: number; nCategories: number; byPriority: Record<string, number>; weightSum: number };
};

export function IntakeWizard({ projectId, onDone }: { projectId: number; onDone: () => void }) {
  const [parsed, setParsed] = useState<Parsed | null>(null);
  const [error, setError] = useState("");
  const confirm = api.intake.confirm.useMutation({
    onSuccess: onDone,
    onError: (e) => {
      if (e.data?.code === "CONFLICT") {
        if (window.confirm("This project already has requirements. Replace EVERYTHING, including existing evaluations?"))
          confirm.mutate({ projectId, parsed: parsed!, replace: true });
      } else setError(e.message);
    },
  });

  async function pick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size === 0) { setError("That file is empty — if it lives in OneDrive, copy it locally first."); return; }
    setError("");
    const fd = new FormData();
    fd.append("file", f);
    const res = await fetch(`/api/projects/${projectId}/intake`, { method: "POST", body: fd });
    const data = (await res.json()) as Parsed & { error?: string };
    if (!res.ok) { setError(data.error ?? "upload failed"); return; }
    setParsed(data);
  }

  return (
    <div className="space-y-4">
      <p><a className="underline" href="/api/template">Download the Excel template</a>, fill it in, upload it here.</p>
      <input type="file" accept=".xlsx" onChange={pick} />
      {error && <p className="text-red-600">{error}</p>}
      {parsed && (
        <div className="rounded border p-4">
          <p>{parsed.summary.nRequirements} requirements in {parsed.summary.nCategories} categories.
             Priorities: {Object.entries(parsed.summary.byPriority).map(([k, v]) => `${k} ${v}`).join(", ")}.
             Weights sum to {parsed.summary.weightSum}.</p>
          {parsed.errors.length > 0 ? (
            <ul className="list-disc pl-6 text-red-600">
              {parsed.errors.map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          ) : (
            <button className="mt-2 rounded bg-slate-800 px-4 py-2 text-white"
                    onClick={() => confirm.mutate({ projectId, parsed })}
                    disabled={confirm.isPending}>
              Confirm and load
            </button>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Remaining components** — mechanical hook wiring, standard Tailwind:
  - `VendorPanel`: list/add/delete vendors (`api.vendor.*`), dossier textarea on add.
  - `EvaluatePanel`: vendor select, proposal textarea plus a "load from file" input accepting `.txt`/`.md` (read client-side with `file.text()` into the textarea — no server parsing; zero-byte files get the OneDrive-placeholder error message), scoring/vote model selects populated from a small `evaluation.models` query (add it: returns `availableModels()` + `TASK_DEFAULTS`; greyed-out options when `!available`), Run button → `evaluation.start`, then poll `evaluation.status` every 1.5s (`refetchInterval`) rendering a progress bar until done/failed; cancel button.
  - `ResultsDashboard`: `evaluation.results` query; ranking strip; per-vendor card (weighted total, verdict badge — red when disqualified with gating summary, category bars from `categoryScores`); click opens `VendorDetail`.
  - `VendorDetail`: vote narrative/dissent/topRisks/evidenceToClose; requirements table (extId, text, priority, met, quality, responseCode, confidence, rationale) with a priority filter; `engineWarning` banner when present.
  - `ChatPanel`: question input + history list calling `chat.ask` (model select defaulting to chat task default).
  - `src/app/projects/[id]/page.tsx`: fetch `project.get`; header (name, client, switch-project link to `/`); Setup tab = project fields form (`project.update`) + IntakeWizard + VendorPanel; other tabs as above. Empty states: no requirements → Setup tab forced with a hint; no evaluations → Results shows "run an evaluation first".

- [ ] **Step 4: Manual smoke** — `npm run dev`, walk: create project → download template → upload → confirm → add vendor → evaluate (mock) → watch progress → results render → detail → chat answers. Fix what breaks.

- [ ] **Step 5: Commit** `feat: project workspace UI (picker, intake, evaluate, results, chat)`

---

### Task 15: E2E verification, README, CLAUDE.md

**Files:**
- Create: `README.md`, `CLAUDE.md`, `scripts/e2e-mock.ts`

**Interfaces:**
- `scripts/e2e-mock.ts` (run with `npx tsx`): against a fresh `DATABASE_URL`, drives the full pipeline through the actual modules (no HTTP): create project → `commitIntake(parseWorkbook(buildTemplate()))` (the template's own example rows are valid) → create vendor → `startEvaluation` with mock models → poll `getJob` → assert results: one vendor, weightedTotal in (0,100], vote recommendation set, gating computed. Then disconnect, reconnect a NEW PrismaClient on the same file, and assert the evaluation is still there — the restart-survival check.

- [ ] **Step 1:** Full suite: `npx vitest run` → all green; `npx tsc --noEmit` → clean; `npm run build` → succeeds (catches server/client component mistakes).
- [ ] **Step 2:** Write and run `scripts/e2e-mock.ts` → prints PASS lines for each assertion.
- [ ] **Step 3:** `README.md` — what this is (three sentences), quickstart (`npm i`, `npx prisma db push`, `npx tsx scripts/create-user.ts ...`, `npm run dev`), env vars (`DATABASE_URL`, `AUTH_SECRET`, `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` optional, `AUTH_DISABLED` dev/test only), the template→upload→evaluate→results flow, and a deployment note: **Render Node service (`npm run build` / `npm run start`), persistent disk mounted for the SQLite file, never serverless (in-process evaluation jobs).**
  `CLAUDE.md` — conventions: rollup.ts is pure and fixture-tested (the fixture is the Phase 2 client-side contract — never change math without updating it); projectId on every procedure; gating deterministic and never LLM-overridable; keys from env only; mock engine must always work keyless; tests must pass (`npx vitest run`) before any commit; Phase 2 = weight studio (sliders/archetypes/sensitivity/scenarios), Phase 3 = mapping wizard/snapshot/matrix per the spec.
- [ ] **Step 4:** Commit and push (ASK USER before the push): `git add -A && git commit -m "docs: readme, claude.md, e2e mock verification" && git push`.

---

## Plan self-review notes (already applied)

- Fixture math verified by hand in Task 3 Step 1 (3.67 / 4.0 / 76.04); it is the permanent ground truth for the Phase 2 client-side rollup port.
- Task 5's test context must mirror the scaffold's actual `createTRPCContext` shape — noted in the task; the implementer adapts the object literal, not the assertion.
- Auth.js v5 beta APIs drift — Task 13 explicitly requires verifying wiring against the installed version's docs before writing.
- `next.config.js` must NOT set `output: "export"` or anything serverless-flavored; default server output is required for in-process jobs.
- Phase 1 deliberately omits: weight-studio UI/sliders/scenarios/archetypes/sensitivity (Phase 2); mapping wizard, static snapshot export, vendor-response-matrix upload, PDF/DOCX proposal ingest (Phase 3 / follow-up — the spec's document-parsing risk applies when that lands).
- Phase 1 proposal input is pasted text plus client-side `.txt`/`.md` file reads (Task 14 EvaluatePanel), matching the spec's Phase 1 ingest scope. The only server-side parsing dependency is exceljs, which narrows the JS document-parsing risk called out in the spec.
