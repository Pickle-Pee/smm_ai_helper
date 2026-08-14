# Product functional scope and MVP

Status: product vision / planning source, not a description of currently deployed behavior.

This document converts the agreed functional draft into repository Markdown so product intent can be reviewed together with OpenSpec changes and code.

## 1. Analytics and review module

The product is intended to replace part of the routine work of a senior marketer/analyst.

Planned capabilities:

- competitor analysis from a website or social link: extract positioning/USP, strengths, weaknesses, customer triggers, and opportunities for differentiation;
- advertising audit from ad-platform exports or creative screenshots, with diagnosis and concrete rewrite recommendations;
- customer journey mapping (CJM) from first awareness through repeat purchase.

Timing such as "one or two minutes" is an aspiration, not an MVP SLA. Access, parsing, model analysis, queue time, and response generation can take longer.

## 2. Learning and interaction module

The differentiator from a generic chat assistant is that the product should involve the marketer in reasoning, not only return finished output.

Planned capabilities:

- **Reveal the logic**: after a strategy/creative decision, offer a short explanation of why that marketing principle was selected and why an alternative may perform worse;
- **Project defense**: simulate a difficult client/stakeholder, ask the marketer to defend a plan, and evaluate the answer;
- **Contextual hints**: explain metrics and marketing terms in-place and connect them to practical actions.

## 3. Generation and refinement module

Planned capabilities:

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

Expected product output:

- competitor strengths;
- competitor weaknesses;
- observed positioning/USP;
- likely customer pains/triggers grounded in available evidence;
- opportunities for differentiation;
- a practical brief for the user's own USP/message direction.

Value: compress several hours of manual first-pass market research into an assisted workflow.

## MVP-2: Commercial creator — image + video script

Input: BrandProfile plus the competitor-analysis result and the user's current objective.

Expected output:

- commercial angle/hypothesis;
- trigger and offer;
- headline and CTA;
- ready advertising image/banner using the existing image generation capability;
- timestamped or beat-by-beat Reels/Shorts script with attention-retention triggers.

The MVP generates the visual and script; the user still produces/edits the final video.

## MVP-3: Interactive hypothesis check / mentor explanation

After the creative package is produced, the assistant should offer to explain the decision instead of ending the flow.

Example interaction intent:

> I used a scarcity trigger in this creative. Want to see why it is a better hypothesis for this audience than a generic discount?

If the user accepts, the product should explain:

- which marketing principle was used;
- which evidence/pain/objection informed it;
- why the chosen hypothesis is stronger than a relevant alternative;
- when the tactic may fail;
- how the marketer can validate the hypothesis with data.

## MVP architecture implication

The MVP therefore needs a durable multi-step workflow:

`competitor analysis -> creative package -> mentor insight`

Existing single-task agents remain useful for standalone strategy/content/analytics/promo/trends requests, but the MVP flow should be orchestrated by a separate workflow layer with durable artifacts and asynchronous job execution.