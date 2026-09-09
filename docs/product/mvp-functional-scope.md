# Product functional scope and MVP

Status: implemented fixed MVP plus broader product vision. The MVP sections describe the executable competitor -> creative -> opt-in mentor flow. Sections 1–6 distinguish its narrower capabilities from future generalized modules. This is not a statement of production deployment. See README and docs/development/marketing-mvp.md for runtime contracts and limits.

Product intent is reviewed together with code, tests and current development contracts; existing OpenSpec documents preserve useful reference/history.

## 1. Analytics and review module

The product is intended to replace part of the routine work of a senior marketer/analyst.

The fixed MVP already analyzes available text from one public competitor HTML page in the user's business context. Broader planned capabilities are:

- competitor analysis from a website or social link: extract positioning/USP, strengths, weaknesses, customer triggers, and opportunities for differentiation;
- advertising audit from ad-platform exports or creative screenshots, with diagnosis and concrete rewrite recommendations;
- customer journey mapping (CJM) from first awareness through repeat purchase.

Timing such as "one or two minutes" is an aspiration, not an MVP SLA. Access, parsing, model analysis, queue time, and response generation can take longer.

## 2. Learning and interaction module

The differentiator from a generic chat assistant is that the product should involve the marketer in reasoning, not only return finished output.

The fixed MVP already offers an explanation of saved creative decisions after explicit user opt-in. Broader learning capabilities are:

- **Reveal the logic**: after a strategy/creative decision, offer a short explanation of why that marketing principle was selected and why an alternative may perform worse;
- **Project defense**: simulate a difficult client/stakeholder, ask the marketer to defend a plan, and evaluate the answer;
- **Contextual hints**: explain metrics and marketing terms in-place and connect them to practical actions.

## 3. Generation and refinement module

The fixed MVP already generates a commercial hypothesis, trigger/offer, headline/CTA, banner and scene script from saved analysis. Broader planned capabilities are:

- trigger-hypothesis generator that connects pain -> mechanism -> offer rather than producing isolated copy;
- meaning/editorial rewrite that cleans rough text while preserving intent and can organize it using sales frameworks such as AIDA/PASCAL;
- later product storytelling can demonstrate longer-form creative collaboration such as helping create a book/project, rather than positioning the product as a simple ChatGPT wrapper.

## 4. Cross-channel AI analytics and autopilot

Longer-term capabilities:

- connect to advertising platforms (for example Yandex, VK, Telegram Ads) and CRM data where APIs, permissions, cost, and reliability make this realistic;
- identify which creatives/links contribute to business outcomes;
- provide scheduled recommendations and morning reports.

For the foreseeable scope, recommendations are preferred over automatic budget manipulation. Direct campaign/budget changes require separate feasibility, security, permissions, and cost analysis before they can enter a product spec.

## 5. CustDev / audience research

Planned capability: AI focus-group simulation.

The product can create several audience personas based on market context and ask them to critique an offer, especially explaining why they would *not* buy it. The mentor layer should then explain which audience need or objection caused the rejection.

## 6. Lead generation and trend monitoring

Longer-term capabilities:

- generate lead-magnet content such as guides/checklists and, only after feasibility work, potentially build lightweight landing experiences;
- monitor selected public sources for niche trends and adapt an emerging format/meme into a brand-specific idea, short-video script, and visual.

Generation speed is not guaranteed and platform access must be assessed independently for every source/integration.

# MVP

The MVP is a connected product flow rather than a collection of unrelated agents.

## MVP-1: Express competitor analysis and meaning generation

User input: a competitor website/link.

Implemented output, subject to available source evidence:

- competitor strengths;
- competitor weaknesses;
- observed positioning/USP;
- likely customer pains/triggers grounded in available evidence;
- opportunities for differentiation;
- a practical brief for the user's own USP/message direction.

Value: compress several hours of manual first-pass market research into an assisted workflow.

## MVP-2: Commercial creator — image + video script

Input: BrandProfile plus the competitor-analysis result and the user's current objective.

Implemented output:

- commercial angle/hypothesis;
- trigger and offer;
- headline and CTA;
- ready advertising image/banner using the existing image generation capability;
- timestamped or beat-by-beat Reels/Shorts script with attention-retention triggers.

The MVP generates the visual and script; the user still produces/edits the final video.

## MVP-3: Interactive hypothesis check / mentor explanation

After the creative package is saved, the assistant offers to explain the decision. Only an explicit user continuation starts the mentor executor; it consumes saved analysis and creative artifacts.

Example interaction intent:

> I used a scarcity trigger in this creative. Want to see why it is a better hypothesis for this audience than a generic discount?

If the user accepts, the mentor explains:

- which marketing principle was used;
- which evidence/pain/objection informed it;
- why the chosen hypothesis is stronger than a relevant alternative;
- when the tactic may fail;
- how the marketer can validate the hypothesis with data.

## MVP architecture implication

The MVP uses the implemented durable multi-step workflow:

`competitor analysis -> creative package -> mentor insight`

Existing single-task agents remain useful for standalone strategy/content/analytics/promo/trends requests. The separate MarketingWorkflowService owns this fixed flow, durable artifacts/evidence/lineage and asynchronous JobExecution leases, fencing and bounded retries. PostgreSQL is authoritative; Redis carries wakeups and PostgreSQL due scans recover work. Independent durable Telegram delivery can retry without generation. Workflow/API/media access is owner-scoped, and a workflow-specific Quality Gates adapter validates structured results before artifact persistence.

Module Registry `1.0.0` remains metadata-only with zero execution bindings. The generic deterministic Orchestrator remains `PLANNING_ONLY`. Fixed execution does not implement arbitrary 15-module execution, generic Orchestrator execution, autonomous replanning or generic synthesis. Campaign execution, CRM integrations, final video generation/editing and production deployment remain outside scope. External provider calls and Telegram sends do not have exactly-once guarantees.
