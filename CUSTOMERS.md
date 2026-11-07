# GridWise: Users & Customers

Who GridWise is for, what they do with it day to day, and how it could grow from a free consumer tool into a business.

> **Core promise:** *Know tomorrow's stressful grid hours in advance, and get a simple plan to avoid them.*

---

## 1. The problem from the user's side

Texans hear "conserve power" alerts from ERCOT, usually the same afternoon, with no specifics. What people actually want to know:

- *"Is tomorrow going to be one of those days?"*
- *"Which hours, exactly?"*
- *"What should I do about it, and will it save me money?"*

ERCOT's dashboards show what is happening **now**, in megawatts. GridWise shows what is likely **tomorrow**, in plain English, with a plan.

---

## 2. Consumer personas

### 🏠 Maria: homeowner on a time-of-use plan (Houston)
- **Situation:** pays more for power from 4–8 pm; family of four; runs laundry and the dishwasher most evenings.
- **Goal:** lower her bill without thinking about it every day.
- **How she uses GridWise:**
  1. Checks the **strain timeline** each morning; tomorrow shows 5–8 pm in red.
  2. Reads the **Gemini advice**: *"Pre-cool to 72° before 3 pm, then let it drift to 76°. Run laundry after 9 pm."*
  3. Hovers over the red bar to see **"Why Red?"**: *"A DFW heat wave is pushing AC demand up as solar fades and wind dies down."*
- **Value:** fewer expensive peak hours on her bill, and she understands *why*.

### 🚗 Jordan: EV owner (Austin)
- **Situation:** charges a car nightly; on a variable-rate plan.
- **Goal:** charge at the cheapest, lowest-stress time without babysitting the app.
- **How Jordan uses GridWise:**
  1. Asks the **chat box**: *"I need 40 kWh by 7 am tomorrow. When should I charge?"*
  2. Gets back: *"Plug in after 11 pm; the cheapest window is 1–5 am (spike risk under 5%)."*
  3. Glances at the **best hours card** before setting the car's charging schedule.
- **Value:** lower charging cost, and charging when the grid has the most spare capacity.

### 🌱 Sam: climate-conscious renter (DFW)
- **Situation:** small apartment, fixed-rate plan, so the bill doesn't change, but cares about outages and emissions.
- **Goal:** do their part on bad days.
- **How Sam uses GridWise:**
  1. Opens the **Ripple simulator**: drags participation to 5% and sees tomorrow's red zone turn yellow.
  2. Shares that screenshot with friends: *"If 5% of us shift our laundry, Texas needs ~4 fewer gas peaker plants tomorrow."*
- **Value:** a concrete, visual sense that small personal actions add up.

### 👵 The Nguyens: medically vulnerable household (San Antonio)
- **Situation:** a family member relies on powered medical equipment.
- **Goal:** early warning so they can prepare (charge backup batteries, plan to stay elsewhere) before an emergency.
- **How they use GridWise:** check the 48-hour outlook and the **confidence band**; a red day with a narrow band means "take this seriously."
- **Value:** a day or two of warning instead of a same-day alert.

---

## 3. A typical day with GridWise

```text
 7:00 am   Open gridwise.tech → tomorrow: 🟢 until 3 pm, 🔴 5–8 pm, spike risk 70% at 6 pm
 7:01 am   Gemini plan: "Pre-cool before 3 pm · laundry after 9 pm · EV 1–5 am"
 7:02 am   Tap the 6 pm red bar → Why Red?: heat in DFW + low wind + solar fade
 3:00 pm   (Next day) Thermostat pre-cooled; laundry queued for 9 pm
 Next am   Report card: "Yesterday's forecast was within 3% · caught 2 of 2 spike hours"
```

---

## 4. Business customers (B2B)

GridWise's forecasts, strain index and spike probabilities are useful well beyond one household. The same Gold tables and API serve these customers:

| Customer | Their problem | How they'd use GridWise | Value to them |
|---|---|---|---|
| **Retail electricity providers** (Texas has many) | Wholesale spikes erode margins on fixed-price customers | Send GridWise-powered "shift your usage tomorrow" nudges to customers; brand the advice in their app | Lower wholesale exposure, better customer engagement |
| **EV fleet operators** (delivery vans, ride-share depots, school buses) | Charging dozens of vehicles at the wrong hour is expensive and strains local circuits | Use `/forecast` and spike probabilities to schedule depot charging | Lower charging costs, predictable operations |
| **Smart-home & thermostat companies** | Need a trusted signal for *when* to pre-cool or delay appliances | Pull hourly strain levels via the API to automate pre-cooling | Better product, energy-savings claims backed by data |
| **Demand-response aggregators & Virtual Power Plants** | Need to know which hours to call events and how much load to target | Use the forecast + **Ripple** to size events ("we need X MW off at 6 pm") | Better event targeting, measurable impact |
| **Commercial & industrial sites** (cold storage, manufacturing, data centers) | Large flexible loads; demand charges | Shift flexible processes away from red hours | Lower demand charges and spike exposure |
| **Cities, universities & campuses** (e.g. Texas A&M) | Facilities managers want to cut peak usage and support grid reliability | Building-level pre-cooling schedules; public sustainability dashboards | Cost savings, sustainability reporting |
| **Newsrooms & community groups** | Want clear, shareable grid outlooks for the public | Embed the strain timeline; quote Genie answers about grid history | Trustworthy, explainable public information |

---

## 5. How customers access GridWise

| Channel | Who | What they get |
|---|---|---|
| **Web dashboard** (gridwise.tech) | Everyone | Strain timeline, spike risk, best hours, Gemini advice, Ripple, report card |
| **Chat box** | Consumers | Personal questions answered by Gemini using the live forecast |
| **REST API** (`/forecast`, `/advice`, `/simulate`, `/history`, `/report-card`) | Businesses, developers | Machine-readable hourly forecasts and scenarios |
| **Genie space** | Analysts, journalists, researchers | Natural-language questions over the full grid history |

---

## 6. Possible business model (post-hackathon)

| Tier | Price idea | Includes |
|---|---|---|
| **Free** | $0 | Dashboard, daily Gemini advice, chat, Ripple |
| **Pro (households)** | ~$3/month | Personal appliance profiles, alert notifications, calendar export of best hours |
| **API / Business** | Usage-based | Forecast + spike API, higher refresh rate, zone-level forecasts, SLA |
| **Enterprise / white-label** | Contract | Branded advice for retail providers' customers, custom models, demand-response event sizing |

*Pricing is illustrative, for discussion only.*

---

## 7. Why customers would trust it

- **Explainable:** every red hour comes with its top drivers ("Why Red?"), not a black box.
- **Honest about uncertainty:** P10–P90 confidence bands; low-confidence hours are flagged.
- **Accountable:** a public **report card** grades yesterday's forecast against what actually happened.
- **Built on public data:** ERCOT, U.S. EIA and Open-Meteo, with a reproducible pipeline.

---

## 8. Today vs. future

| Today (hackathon scope) | Future roadmap |
|---|---|
| System-wide ERCOT forecast | Load-zone forecasts (Houston, North, South, West) |
| Dashboard + chat | SMS / push alerts the evening before a red day |
| Generic appliance advice | Personal appliance profiles and bill-savings estimates |
| Manual action by users | Smart-thermostat and EV-charger integrations that act automatically |
| — | Demand-response rewards for shifting usage (Solana stretch idea) |

See [PROJECT_SCOPE.md](PROJECT_SCOPE.md) for what's deliberately out of scope for the hackathon.
