"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { GoogleMapPicker, PickedLocation } from "./components/GoogleMapPicker";

type RecordValue = Record<string, unknown>;
type Location = {
  lat: number;
  lon: number;
  source: "live_location" | "google_maps";
  label?: string;
};
type Intake = {
  session_id: string;
  assistant_message: string;
  next_field: string | null;
  answer_options: IntakeOption[];
  facts: string[];
  missing: string[];
  recognized: RecordValue;
  plan_input: RecordValue;
  retrieval: RecordValue[];
  mode: string;
};
type IntakeOption = {
  id: string;
  label: string;
  action: "message" | "custom" | "live_location" | "google_maps";
  message?: string;
};
type Plan = {
  status: "partial";
  session_id: string;
  trace_ids: string[];
  location: RecordValue;
  weather_snapshot?: RecordValue | null;
  assessments: RecordValue[];
  season_events: { status: string; events: RecordValue[]; by_crop?: RecordValue[] };
  financials: RecordValue;
  missing: RecordValue[];
  unassessed: RecordValue[];
  warnings: string[];
};
type Weather = {
  source_id: string;
  timezone?: string;
  request_url?: string;
  daily_units?: RecordValue;
  daily?: RecordValue;
};
type TraceRecord = {
  id: string;
  step: string;
  tool: string;
  status: string;
  trace_type?: string;
  params_json: RecordValue;
  display_output_json: RecordValue;
};
type RankedCrop = {
  rank: number;
  crop_id: string;
  composite_score: number;
  soil_suitability_class: string;
  water_class: string;
  rough_profit_bdt: number;
  risk_level: string;
  risk_flags: string[];
  total_cost_bdt?: number | null;
  fits_budget?: boolean | null;
  score_components?: RecordValue;
};
type Ranking = {
  session_id: string;
  trace_ids: string[];
  status: string;
  policy: string;
  chosen_crop_id: string | null;
  budget_bdt?: number | null;
  target_season: string;
  season_crop_ids: string[];
  ranked: RankedCrop[];
  excluded: RecordValue[];
  evidence: Record<string, RecordValue>;
  weather_summary?: RecordValue | null;
  chosen_plan?:
    | (RecordValue & {
        crop_id?: string;
        events?: RecordValue[];
        grounding?: RecordValue;
      })
    | null;
  profile_used?: RecordValue;
  from_conversation_session?: string;
  weather_warning?: string | null;
};
type ChatEntry = {
  id: string;
  role: "assistant" | "user";
  content: string;
};

const cropNames: Record<string, string> = {
  boro_rice: "Boro rice",
  maize: "Maize",
  lentil: "Lentil",
  wheat: "Wheat",
};
const cropNamesBn: Record<string, string> = {
  boro_rice: "বোরো ধান",
  maize: "ভুট্টা",
  lentil: "মসুর",
  wheat: "গম",
};
const capabilityNames = [
  ["Conversational intake", "Farm context"],
  ["Live weather", "Real forecast"],
  ["Crop recommendation", "Rabi candidates"],
  ["Season plan", "Dated operations"],
  ["Financial projection", "Cost & profit"],
  ["Explained reasoning", "Inputs & limits"],
  ["Knowledge base + RAG", "Cited retrieval"],
  ["Visible agent trace", "Tool evidence"],
] as const;
const initialLocationOptions: IntakeOption[] = [
  { id: "location_live", label: "◎ Live location", action: "live_location" },
  { id: "location_map", label: "⌖ Choose on map", action: "google_maps" },
];

const text = (value: unknown) => (value == null || value === "" ? "—" : String(value));
const record = (value: unknown): RecordValue =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as RecordValue)
    : {};
const rows = (value: unknown): RecordValue[] =>
  Array.isArray(value) ? (value as RecordValue[]) : [];
const label = (value: unknown) =>
  text(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
const money = (value: unknown) =>
  value == null ? "—" : `৳${Number(value).toLocaleString("en-BD", { maximumFractionDigits: 0 })}`;
const entry = (role: ChatEntry["role"], content: string): ChatEntry => ({
  id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
  role,
  content,
});

function Notice({
  children,
  tone = "warning",
}: {
  children: React.ReactNode;
  tone?: "warning" | "danger" | "info";
}) {
  return <div className={`notice ${tone}`}>{children}</div>;
}

function SourceLine({ item }: { item: RecordValue }) {
  if (!item.source_id) return null;
  return (
    <p className="source-line">
      <span>Source</span>
      <strong>{text(item.source_id)}</strong>
      {item.source_locator ? <> · {text(item.source_locator)}</> : null}
    </p>
  );
}

function Metric({
  name,
  value,
  hint,
}: {
  name: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="metric">
      <span>{name}</span>
      <strong>{value}</strong>
      {hint ? <small>{hint}</small> : null}
    </div>
  );
}

export default function Home() {
  const [activeCapability, setActiveCapability] = useState(1);
  const [message, setMessage] = useState("");
  const [location, setLocation] = useState<Location | null>(null);
  const [intake, setIntake] = useState<Intake | null>(null);
  const [intakeSessionId, setIntakeSessionId] = useState<string | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [ranking, setRanking] = useState<Ranking | null>(null);
  const [irrigationPerDay, setIrrigationPerDay] = useState("0");
  const [startingDepletion, setStartingDepletion] = useState("40");
  const [weather, setWeather] = useState<Weather | null>(null);
  const [weatherError, setWeatherError] = useState<string | null>(null);
  const [traces, setTraces] = useState<TraceRecord[]>([]);
  const [selectedCrop, setSelectedCrop] = useState("maize");
  const [includeFinance, setIncludeFinance] = useState(false);
  const [sowingDate, setSowingDate] = useState("");
  const [soilTestClass, setSoilTestClass] = useState("");
  const [loading, setLoading] = useState<
    "location" | "chat" | "plan" | "reload" | null
  >(null);
  const [weatherLoading, setWeatherLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mapOpen, setMapOpen] = useState(false);
  const [chat, setChat] = useState<ChatEntry[]>([
    entry(
      "assistant",
      "শুরু করি—খামারের লোকেশন শেয়ার করুন, অথবা এক বাক্যে আপনার খামার ও লক্ষ্য সম্পর্কে বলুন।",
    ),
  ]);
  const composerRef = useRef<HTMLTextAreaElement>(null);

  async function json(response: Response) {
    const body = (await response.json().catch(() => ({}))) as RecordValue;
    if (!response.ok) {
      throw new Error(text(body.detail) || `Request failed (${response.status})`);
    }
    return body;
  }

  useEffect(() => {
    if (!location) return;
    let cancelled = false;
    setWeatherLoading(true);
    setWeatherError(null);
    fetch(
      `/api/weather/forecast?lat=${encodeURIComponent(location.lat)}&lon=${encodeURIComponent(location.lon)}&days=7`,
    )
      .then(json)
      .then((body) => {
        if (!cancelled) setWeather(body as Weather);
      })
      .catch((cause) => {
        if (!cancelled) {
          setWeather(null);
          setWeatherError(cause instanceof Error ? cause.message : "Weather unavailable");
        }
      })
      .finally(() => {
        if (!cancelled) setWeatherLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [location]);

  async function runIntake(
    latestMessage: string,
    chosenLocation: Location | null,
    event: "message" | "location_selected" = "message",
  ) {
    const nextIntake = (await json(
      await fetch("/api/intake/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          message: latestMessage,
          location: chosenLocation,
          session_id: intakeSessionId,
          event,
        }),
      }),
    )) as Intake;
    setIntake(nextIntake);
    setIntakeSessionId(nextIntake.session_id);
    const cropIds = Array.isArray(nextIntake.recognized.crop_ids)
      ? (nextIntake.recognized.crop_ids as string[])
      : [];
    if (cropIds[0]) setSelectedCrop(cropIds[0]);
    return nextIntake;
  }

  async function chooseLocation(chosenLocation: Location) {
    setLocation(chosenLocation);
    setMapOpen(false);
    setError(null);
    setLoading("chat");
    try {
      const nextIntake = await runIntake(
        "I selected my farm location.",
        chosenLocation,
        "location_selected",
      );
      setChat((current) => [
        ...current,
        entry("user", `📍 ${chosenLocation.label ?? "Farm location selected"}`),
        entry("assistant", nextIntake.assistant_message),
      ]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Location could not be applied.");
    } finally {
      setLoading(null);
    }
  }

  function useLiveLocation() {
    if (!navigator.geolocation) {
      setError("Live location is unavailable in this browser. Choose the farm on Google Maps.");
      return;
    }
    setLoading("location");
    setError(null);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        void chooseLocation({
            lat: position.coords.latitude,
            lon: position.coords.longitude,
            source: "live_location",
            label: "Live browser location",
          })
          .finally(() => setLoading(null));
      },
      (positionError) => {
        const detail =
          positionError.code === positionError.PERMISSION_DENIED
            ? "Location permission was denied. Allow location access for this site in your browser settings, then try again."
            : positionError.code === positionError.TIMEOUT
              ? "The browser could not get a location in time. Try again near a window, or choose the farm on Google Maps."
              : "The device could not determine a live location. Check Location Services, or choose the farm on Google Maps.";
        setError(detail);
        setLoading(null);
      },
      { enableHighAccuracy: false, timeout: 20000, maximumAge: 300000 },
    );
  }

  async function submitText(outgoing: string) {
    if (!outgoing) return;
    const userEntry = entry("user", outgoing);
    setChat((current) => [...current, userEntry]);
    setMessage("");
    setLoading("chat");
    setError(null);
    setPlan(null);
    setRanking(null);
    setTraces([]);
    try {
      const nextIntake = await runIntake(outgoing, location);
      setChat((current) => [
        ...current,
        entry("assistant", nextIntake.assistant_message),
      ]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to understand the message.");
    } finally {
      setLoading(null);
    }
  }

  async function sendChat(event: FormEvent) {
    event.preventDefault();
    await submitText(message.trim());
  }

  function chooseAnswer(option: IntakeOption) {
    if (loading) return;
    if (option.action === "live_location") {
      useLiveLocation();
      return;
    }
    if (option.action === "google_maps") {
      setMapOpen(true);
      return;
    }
    if (option.action === "custom") {
      setMessage(option.message ?? "");
      window.setTimeout(() => composerRef.current?.focus(), 0);
      return;
    }
    void submitText(option.message ?? option.label);
  }

  async function loadTraces(sessionId: string) {
    const body = await json(
      await fetch(`/api/plan/preview/${encodeURIComponent(sessionId)}/traces`),
    );
    setTraces(rows(body.traces) as unknown as TraceRecord[]);
  }

  async function createPlan() {
    if (!intake) return;
    const input = intake.plan_input;
    if (input.lat == null || input.lon == null || input.soil_class == null) {
      setError("Complete the farm context and choose a location first.");
      return;
    }
    setLoading("plan");
    setError(null);
    try {
      const nextPlan = (await json(
        await fetch("/api/plan/preview", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            lat: input.lat,
            lon: input.lon,
            soil_class: input.soil_class,
            drainage_condition: input.drainage_condition,
            water_availability: input.water_availability,
            target_season: input.target_season,
            crop_ids: input.crop_ids,
            area_acres: input.area_acres,
            sowing_date: sowingDate || input.sowing_date || null,
            variety_id: input.variety_id,
            soil_test_class: soilTestClass || input.soil_test_class || null,
            allow_assumptions: includeFinance,
          }),
        }),
      )) as Plan;
      setPlan(nextPlan);
      await loadTraces(nextPlan.session_id);

      // The single conversational path: rank + choose + date + cost + ground.
      if (intakeSessionId) {
        try {
          const nextRanking = (await json(
            await fetch("/api/plan/from-conversation", {
              method: "POST",
              headers: { "content-type": "application/json" },
              body: JSON.stringify({
                session_id: intakeSessionId,
                lat: input.lat,
                lon: input.lon,
                starting_depletion_mm: Number(startingDepletion) || 0,
                irrigation_mm_per_day: Number(irrigationPerDay) || 0,
                soil_test_class: soilTestClass || null,
              }),
            }),
          )) as Ranking;
          setRanking(nextRanking);
          if (nextRanking.chosen_crop_id) setSelectedCrop(nextRanking.chosen_crop_id);
          if (nextRanking.trace_ids?.length) await loadTraces(nextRanking.session_id);
        } catch {
          setRanking(null);
        }
      }
      setActiveCapability(2);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to create plan.");
    } finally {
      setLoading(null);
    }
  }

  async function reloadPlan() {
    if (!plan) return;
    setLoading("reload");
    setError(null);
    try {
      const nextPlan = (await json(
        await fetch(`/api/plan/preview/${encodeURIComponent(plan.session_id)}`),
      )) as Plan;
      setPlan(nextPlan);
      await loadTraces(nextPlan.session_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to reload plan.");
    } finally {
      setLoading(null);
    }
  }

  const recognized = intake?.recognized ?? {};
  const planAdmin = record(plan?.location?.admin);
  const adm3 = record(planAdmin.adm3);
  const aezCandidates = rows(plan?.location?.aez_candidates);
  const completion = [
    Boolean(intake),
    Boolean(weather),
    Boolean(plan?.assessments.length),
    Boolean(plan?.season_events.events.length),
    plan?.financials.status === "included_provisional_assumptions",
    Boolean(plan),
    Boolean(intake?.retrieval.length),
    Boolean(traces.length),
  ];
  const completedCount = completion.filter(Boolean).length;
  const canPlan = Boolean(intake && intake.missing.length === 0);
  const answerOptions = intake?.answer_options ?? initialLocationOptions;
  const selectedAssessment = plan?.assessments.find(
    (item) => item.crop_id === selectedCrop,
  );
  const selectedFinancial = rows(plan?.financials.by_crop).find(
    (item) => item.crop_id === selectedCrop,
  );
  const selectedEvents = (plan?.season_events.events ?? []).filter(
    (item) => item.crop_id === selectedCrop,
  );
  const daily = weather?.daily ?? {};
  const dates = Array.isArray(daily.time) ? (daily.time as string[]) : [];
  const valuesAt = (key: string, index: number) => {
    const values = daily[key];
    return Array.isArray(values) ? values[index] : null;
  };

  function renderCapability() {
    if (activeCapability === 1) {
      return (
        <section className="workspace-panel intake-workspace">
          <div className="panel-heading">
            <div>
              <span className="step-kicker">01 · CONVERSATIONAL INTAKE</span>
              <h1>Tell me about your farm</h1>
              <p>
                বাংলায় বা English-এ লিখুন। I’ll keep asking only for information
                that is still missing.
              </p>
            </div>
            <span className="mode-badge">Grounded intake</span>
          </div>

          <div className="chat-window" aria-live="polite">
            {chat.map((item) => (
              <div className={`message-row ${item.role}`} key={item.id}>
                <div className="avatar">{item.role === "assistant" ? "A" : "You"}</div>
                <div className="message-bubble">{item.content}</div>
              </div>
            ))}
            {loading === "chat" ? (
              <div className="message-row assistant">
                <div className="avatar">A</div>
                <div className="message-bubble thinking">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            ) : null}
          </div>

          {answerOptions.length ? (
            <div className="answer-options" aria-label="Suggested answers">
              {answerOptions.map((option) => (
                <button
                  type="button"
                  key={option.id}
                  onClick={() => chooseAnswer(option)}
                  disabled={Boolean(loading)}
                >
                  {option.label}
                </button>
              ))}
              <span>or type your own answer below</span>
            </div>
          ) : intake ? (
            <div className="context-complete">
              <span>✓</span>
              <div>
                <strong>Farm context complete</strong>
                <small>Review the profile and generate the grounded plan.</small>
              </div>
            </div>
          ) : null}

          <form className="composer" onSubmit={sendChat}>
            <textarea
              ref={composerRef}
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder="যেমন: রবি মৌসুমে আমার ১ একর দোআঁশ জমিতে ভুট্টা লাগাতে চাই। সেচ আছে, বাজেট ৩০,০০০ টাকা।"
              rows={3}
              aria-label="Message to AgriSense"
              required
            />
            <button type="submit" disabled={loading === "chat"} aria-label="Send message">
              Send
            </button>
          </form>

          {error ? <Notice tone="danger">{error}</Notice> : null}

          {location ? (
            <div className="location-confirmation">
              <span>✓ {location.label ?? "Farm location selected"}</span>
              <button type="button" onClick={() => setMapOpen(true)}>Change on map</button>
            </div>
          ) : null}

          {intake ? (
            <div className="intake-actions">
              <div className="assessment-details">
                <label>
                  <span>Expected sowing/transplanting date</span>
                  <input
                    type="date"
                    value={sowingDate}
                    onChange={(event) => setSowingDate(event.target.value)}
                  />
                  <small>Optional; enables dated operations.</small>
                </label>
                <label>
                  <span>Laboratory soil-test class</span>
                  <select
                    value={soilTestClass}
                    onChange={(event) => setSoilTestClass(event.target.value)}
                  >
                    <option value="">Unknown / no test</option>
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                  <small>Do not guess from soil texture.</small>
                </label>
                <label>
                  <span>Planned irrigation (mm/day)</span>
                  <input
                    type="number"
                    min="0"
                    step="0.5"
                    value={irrigationPerDay}
                    onChange={(event) => setIrrigationPerDay(event.target.value)}
                  />
                  <small>Net infiltrated water; feeds the FAO-56 water balance.</small>
                </label>
                <label>
                  <span>Starting soil moisture deficit (mm)</span>
                  <input
                    type="number"
                    min="0"
                    step="5"
                    value={startingDepletion}
                    onChange={(event) => setStartingDepletion(event.target.value)}
                  />
                  <small>Root-zone depletion at season start; enables water ranking.</small>
                </label>
              </div>
              <label className="assumption-toggle">
                <input
                  type="checkbox"
                  checked={includeFinance}
                  onChange={(event) => setIncludeFinance(event.target.checked)}
                />
                <span>
                  <strong>Include editable finance assumptions</strong>
                  <small>Required to show cost, ROI and break-even.</small>
                </span>
              </label>
              <button
                type="button"
                className="primary-button"
                onClick={createPlan}
                disabled={!canPlan || loading === "plan"}
              >
                {loading === "plan" ? "Building plan…" : "Generate grounded plan →"}
              </button>
            </div>
          ) : null}
        </section>
      );
    }

    if (activeCapability === 2) {
      return (
        <section className="workspace-panel">
          <div className="panel-heading">
            <div>
              <span className="step-kicker">02 · LIVE WEATHER GROUNDING</span>
              <h1>Real 7-day farm forecast</h1>
              <p>Returned directly from Open-Meteo for the selected farm location.</p>
            </div>
            <span className="live-badge"><i /> LIVE API</span>
          </div>
          {weatherLoading ? <div className="skeleton-block">Loading farm forecast…</div> : null}
          {weatherError ? <Notice tone="danger">{weatherError}</Notice> : null}
          {!weather && !weatherLoading && !weatherError ? (
            <Notice>Select the farm location in conversational intake to load live weather.</Notice>
          ) : null}
          {weather ? (
            <>
              <div className="weather-summary">
                <Metric
                  name="Today"
                  value={`${text(valuesAt("temperature_2m_max", 0))}°`}
                  hint={`${text(valuesAt("temperature_2m_min", 0))}° minimum`}
                />
                <Metric
                  name="Rainfall"
                  value={`${text(valuesAt("precipitation_sum", 0))} mm`}
                  hint="actual API value"
                />
                <Metric
                  name="FAO ET₀"
                  value={`${text(valuesAt("et0_fao_evapotranspiration", 0))} mm`}
                  hint="reference evapotranspiration"
                />
              </div>
              <div className="forecast-strip">
                {dates.map((date, index) => (
                  <div className="forecast-day" key={date}>
                    <strong>
                      {new Date(`${date}T00:00:00`).toLocaleDateString("en-BD", {
                        weekday: "short",
                      })}
                    </strong>
                    <span>{date.slice(5)}</span>
                    <b>{text(valuesAt("temperature_2m_max", index))}°</b>
                    <small>↓ {text(valuesAt("precipitation_sum", index))} mm rain</small>
                  </div>
                ))}
              </div>
              <SourceLine item={{ source_id: weather.source_id, source_locator: weather.timezone }} />
              <Notice tone={ranking?.ranked?.length ? "info" : "warning"}>
                {ranking?.ranked?.length
                  ? "These live rainfall and ET0 values feed the FAO-56 daily water balance that produces each crop's water class in the ranking. The water-class thresholds are an inspectable provisional policy, not yet locally calibrated."
                  : "This live snapshot feeds the FAO-56 water balance once you supply the planned irrigation and starting soil-moisture inputs. The water-class thresholds are an inspectable provisional policy, not yet locally calibrated."}
              </Notice>
            </>
          ) : null}
        </section>
      );
    }

    if (activeCapability === 3) {
      return (
        <section className="workspace-panel">
          <div className="panel-heading">
            <div>
              <span className="step-kicker">03 · CROP RECOMMENDATION</span>
              <h1>
                {(plan?.assessments.length ?? 0) === 0
                  ? "This season is not yet supported by the reviewed demo corpus"
                  : `${plan?.assessments.length} transparent crop ${
                      plan?.assessments.length === 1 ? "candidate" : "candidates"
                    }`}
              </h1>
              <p>
                {(plan?.assessments.length ?? 0) === 0
                  ? "Supported now: the Rabi season (maize, lentil, wheat). Pick a supported season/crop to see assessments."
                  : "Compare soil fit, water status, calendar evidence and provisional economics."}
              </p>
            </div>
            <span className="count-badge">{plan?.assessments.length ?? 0} assessed</span>
          </div>
          {ranking?.ranked?.length ? (
            <div className="ranked-list">
              <div className="ranked-head">
                <strong>Deterministic ranking · {label(ranking.status)}</strong>
                {ranking.chosen_crop_id ? (
                  <span>
                    Chosen: {cropNames[ranking.chosen_crop_id] ?? label(ranking.chosen_crop_id)}
                  </span>
                ) : null}
              </div>
              {ranking.ranked.map((row) => (
                <button
                  type="button"
                  key={row.crop_id}
                  className={`ranked-row ${row.crop_id === selectedCrop ? "selected" : ""}`}
                  onClick={() => setSelectedCrop(row.crop_id)}
                >
                  <span className="ranked-rank">#{row.rank}</span>
                  <span className="ranked-name">
                    {cropNames[row.crop_id] ?? label(row.crop_id)}
                  </span>
                  <span className="ranked-metric">Soil {text(row.soil_suitability_class)}</span>
                  <span className="ranked-metric">Water {text(row.water_class)}</span>
                  <span className="ranked-metric">Risk {label(row.risk_level)}</span>
                  <span className="ranked-metric strong">{money(row.rough_profit_bdt)}</span>
                  {row.fits_budget != null ? (
                    <span className={`budget-pill ${row.fits_budget ? "ok" : "over"}`}>
                      {row.fits_budget ? "Within budget" : "Over budget"}
                    </span>
                  ) : null}
                </button>
              ))}
              <p className="ranked-policy">{text(ranking.policy)}</p>
            </div>
          ) : null}
          <div className="crop-grid">
            {plan?.assessments.map((item, index) => {
              const isSelected = item.crop_id === selectedCrop;
              return (
                <button
                  type="button"
                  className={`crop-card ${isSelected ? "selected" : ""}`}
                  key={text(item.crop_id)}
                  onClick={() => setSelectedCrop(text(item.crop_id))}
                >
                  <div className="crop-card-top">
                    <span className="candidate-number">0{index + 1}</span>
                    <span className={`fit-pill ${item.soil_class === "unassessed" ? "pending" : ""}`}>
                      {label(item.soil_class)}
                    </span>
                  </div>
                  <h2>{cropNames[text(item.crop_id)] ?? label(item.crop_id)}</h2>
                  <p>{cropNamesBn[text(item.crop_id)]}</p>
                  <dl>
                    <div><dt>Soil fit</dt><dd>{label(item.soil_class)}</dd></div>
                    <div><dt>Water</dt><dd>{label(item.water_class)}</dd></div>
                    <div><dt>Ranking</dt><dd>Pending complete inputs</dd></div>
                  </dl>
                  <SourceLine item={record(item.soil_evidence)} />
                </button>
              );
            })}
          </div>
          <Notice tone={ranking?.ranked?.length ? "info" : "warning"}>
            {ranking?.ranked?.length
              ? "Ranking uses real weather via the FAO-56 water balance, curated soil suitability and rough profit. Paddy rice and any crop missing a factor stay excluded."
              : "The backend deliberately does not fabricate a winner: ranking remains paused until every crop has comparable soil, weather and irrigation factors."}
          </Notice>
        </section>
      );
    }

    if (activeCapability === 4) {
      const chosenPlan = record(ranking?.chosen_plan);
      const usingChosenPlan =
        ranking?.chosen_plan != null && text(chosenPlan.crop_id) === selectedCrop;
      const timelineEvents = usingChosenPlan ? rows(chosenPlan.events) : selectedEvents;
      return (
        <section className="workspace-panel">
          <div className="panel-heading">
            <div>
              <span className="step-kicker">04 · SEASON PLAN</span>
              <h1>{cropNames[selectedCrop]} season timeline</h1>
              <p>
                {usingChosenPlan
                  ? "Land preparation to harvest for the chosen crop, dated from the sowing anchor and CROPWAT stages."
                  : "Cited operations use exact dates only when the farmer supplied a sowing date."}
              </p>
            </div>
            <CropSelector value={selectedCrop} onChange={setSelectedCrop} />
          </div>
          <div className="timeline">
            {timelineEvents.map((item, index) => {
              const range = item.date_start
                ? `${text(item.date_start)} → ${text(item.date_end)}`
                : item.date
                  ? text(item.date)
                  : item.month_window
                    ? `Month ${text(record(item.month_window).start_month)}–${text(record(item.month_window).end_month)}`
                    : "Timing from source";
              const kind = item.date_start
                ? "DATED RANGE"
                : item.date
                  ? "DATED"
                  : "WINDOW";
              return (
                <article className="timeline-item" key={`${text(item.operation)}-${index}`}>
                  <div className="timeline-marker">{index + 1}</div>
                  <div className="timeline-content">
                    <div className="timeline-topline">
                      <span>{kind}</span>
                      <strong>{range}</strong>
                    </div>
                    <h2>{label(item.operation)}</h2>
                    <p>{text(item.timing)}</p>
                    <SourceLine item={item} />
                  </div>
                </article>
              );
            })}
          </div>
          {!timelineEvents.length ? (
            <Notice>No reviewed operations were found for this crop.</Notice>
          ) : null}
        </section>
      );
    }

    if (activeCapability === 5) {
      const rankEvidence = record(ranking?.evidence?.[selectedCrop]);
      const rankFinancial = record(rankEvidence.financials);
      const financial =
        selectedFinancial ??
        (Object.keys(rankFinancial).length ? rankFinancial : null);
      const fitsBudget = rankEvidence.fits_budget as boolean | null | undefined;
      return (
        <section className="workspace-panel">
          <div className="panel-heading">
            <div>
              <span className="step-kicker">05 · FINANCIAL PROJECTION</span>
              <h1>Inspectable farm economics</h1>
              <p>Area-scaled costs, revenue, profit, ROI and break-even from editable assumptions.</p>
            </div>
            <CropSelector value={selectedCrop} onChange={setSelectedCrop} />
          </div>
          {ranking?.budget_bdt != null && fitsBudget != null ? (
            <Notice tone={fitsBudget ? "info" : "danger"}>
              Farmer budget {money(ranking.budget_bdt)} ·{" "}
              {fitsBudget ? "this crop fits the budget" : "this crop exceeds the budget"}{" "}
              (total cost {money(rankEvidence.total_cost_bdt)}).
            </Notice>
          ) : null}
          {financial ? (
            <>
              <div className="finance-metrics">
                <Metric name="Total cost" value={money(financial.total_cost_bdt)} />
                <Metric name="Revenue" value={money(financial.revenue_bdt)} />
                <Metric name="Net profit" value={money(financial.net_profit_bdt)} />
                <Metric name="ROI" value={`${text(financial.roi_percent)}%`} />
              </div>
              <div className="break-even">
                <div>
                  <span>Break-even yield</span>
                  <strong>{text(financial.break_even_yield_kg_per_acre)} kg/acre</strong>
                </div>
                <div>
                  <span>Break-even price</span>
                  <strong>{money(financial.break_even_price_bdt_per_kg)}/kg</strong>
                </div>
              </div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Cost item</th><th>Per acre</th><th>Total</th><th>Evidence</th></tr></thead>
                  <tbody>
                    {rows(financial.line_items).map((item) => (
                      <tr key={text(item.item)}>
                        <td>{label(item.item)}</td>
                        <td>{money(item.cost_per_acre_bdt)}</td>
                        <td>{money(item.total_cost_bdt)}</td>
                        <td><SourceLine item={item} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Notice>{text(financial.warning)}</Notice>
            </>
          ) : plan?.financials.status === "blocked_until_assumption_opt_in" ? (
            <div className="locked-panel">
              <span>৳</span>
              <h2>Finance assumptions are off</h2>
              <p>{text(plan.financials.reason)}</p>
              <label className="assumption-toggle compact">
                <input
                  type="checkbox"
                  checked={includeFinance}
                  onChange={(event) => setIncludeFinance(event.target.checked)}
                />
                <span><strong>I accept editable demo assumptions</strong></span>
              </label>
              <button
                type="button"
                className="primary-button"
                disabled={!includeFinance || loading === "plan"}
                onClick={createPlan}
              >
                Recalculate with finance
              </button>
            </div>
          ) : selectedFinancial ? (
            <>
              <div className="finance-metrics">
                <Metric name="Total cost" value={money(selectedFinancial.total_cost_bdt)} />
                <Metric name="Revenue" value={money(selectedFinancial.revenue_bdt)} />
                <Metric name="Net profit" value={money(selectedFinancial.net_profit_bdt)} />
                <Metric name="ROI" value={`${text(selectedFinancial.roi_percent)}%`} />
              </div>
              <div className="break-even">
                <div>
                  <span>Break-even yield</span>
                  <strong>{text(selectedFinancial.break_even_yield_kg_per_acre)} kg/acre</strong>
                </div>
                <div>
                  <span>Break-even price</span>
                  <strong>{money(selectedFinancial.break_even_price_bdt_per_kg)}/kg</strong>
                </div>
              </div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Cost item</th><th>Per acre</th><th>Total</th><th>Evidence</th></tr></thead>
                  <tbody>
                    {rows(selectedFinancial.line_items).map((item) => (
                      <tr key={text(item.item)}>
                        <td>{label(item.item)}</td>
                        <td>{money(item.cost_per_acre_bdt)}</td>
                        <td>{money(item.total_cost_bdt)}</td>
                        <td><SourceLine item={item} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Notice>{text(selectedFinancial.warning)}</Notice>
            </>
          ) : (
            <Notice>No financial row is available for the selected crop.</Notice>
          )}
        </section>
      );
    }

    if (activeCapability === 6) {
      return (
        <section className="workspace-panel">
          <div className="panel-heading">
            <div>
              <span className="step-kicker">06 · EXPLAINED REASONING</span>
              <h1>Why the plan says what it says</h1>
              <p>Farmer inputs, retrieved data, decisions and unresolved limits stay visible.</p>
            </div>
            <span className="mode-badge">No hidden score</span>
          </div>
          <div className="reason-grid">
            <div className="reason-card">
              <span className="card-label">Farm evidence used</span>
              <h2>{text(adm3.name) || "Selected farm"}</h2>
              <ul>
                <li><span>Soil</span><strong>{label(recognized.soil_class)}</strong></li>
                <li><span>Drainage</span><strong>{label(intake?.plan_input.drainage_condition)}</strong></li>
                <li><span>Area</span><strong>{text(recognized.area_acres)} acre</strong></li>
                <li><span>Water</span><strong>{label(recognized.water_availability)}</strong></li>
                <li><span>Season</span><strong>{label(recognized.target_season)}</strong></li>
              </ul>
            </div>
            <div className="reason-card">
              <span className="card-label">Location inference</span>
              <h2>Administrative prior only</h2>
              <p>
                AEZ candidates: {aezCandidates.map((item) => text(item.aez_id)).join(", ") || "none"}.
              </p>
              <small>{text(plan?.location.warning)}</small>
            </div>
          </div>
          <div className="reason-list">
            {plan?.assessments.map((item) => (
              <article key={text(item.crop_id)}>
                <div><strong>{cropNames[text(item.crop_id)]}</strong><span>{cropNamesBn[text(item.crop_id)]}</span></div>
                <p>
                  Soil is <b>{label(item.soil_class)}</b>. Water remains{" "}
                  <b>{label(item.water_class)}</b>. Therefore{" "}
                  <b>{label(item.ranking_status)}</b>.
                </p>
                <SourceLine item={record(item.soil_evidence)} />
              </article>
            ))}
          </div>
          <div className="limit-grid">
            <div>
              <h3>Missing for full assessment</h3>
              {plan?.missing.map((item) => (
                <p key={text(item.field)}><strong>{label(item.field)}</strong> · {text(item.reason)}</p>
              ))}
            </div>
            <div>
              <h3>Unassessed factors</h3>
              {plan?.unassessed.map((item) => (
                <p key={`${text(item.crop_id)}-${text(item.factor)}`}>
                  <strong>{cropNames[text(item.crop_id)]} · {label(item.factor)}</strong> · {text(item.reason)}
                </p>
              ))}
            </div>
          </div>
        </section>
      );
    }

    if (activeCapability === 7) {
      return (
        <section className="workspace-panel">
          <div className="panel-heading">
            <div>
              <span className="step-kicker">07 · KNOWLEDGE BASE WITH RAG</span>
              <h1>Retrieved evidence, not model recall</h1>
              <p>The intake query is filtered against the reviewed Supabase knowledge base.</p>
            </div>
            <span className="count-badge">{intake?.retrieval.length ?? 0} chunks</span>
          </div>
          {(() => {
            const grounding = record(record(ranking?.chosen_plan).grounding);
            const chunks = rows(grounding.chunks);
            if (!ranking?.chosen_plan) return null;
            return (
              <div className="grounding-block">
                <div className="grounding-head">
                  <strong>
                    Chosen-crop advice grounding ·{" "}
                    {cropNames[text(record(ranking.chosen_plan).crop_id)] ??
                      label(record(ranking.chosen_plan).crop_id)}
                  </strong>
                  <span>{label(grounding.status)}</span>
                </div>
                {chunks.length ? (
                  chunks.map((item) => (
                    <article className="grounding-chunk" key={text(item.chunk_id)}>
                      <div className="rag-meta">
                        <span>{label(item.topic)}</span>
                        <span>score {text(item.score)}</span>
                      </div>
                      <p>{text(item.text)}</p>
                      <SourceLine item={item} />
                    </article>
                  ))
                ) : (
                  <Notice>
                    Retrieval was below the relevance threshold, so no prose advice is
                    attached to the plan.
                  </Notice>
                )}
              </div>
            );
          })()}
          <div className="rag-list">
            {intake?.retrieval.map((item, index) => (
              <article key={text(item.chunk_id)}>
                <div className="rag-index">0{index + 1}</div>
                <div>
                  <div className="rag-meta">
                    <span>{label(item.topic)}</span>
                    <span>{label(item.crop)}</span>
                    <span>{text(item.language)}</span>
                    <span>score {text(item.score)}</span>
                  </div>
                  <p>{text(item.text)}</p>
                  <SourceLine item={item} />
                </div>
              </article>
            ))}
          </div>
          {!intake?.retrieval.length ? <Notice>No knowledge chunks were retrieved yet.</Notice> : null}
        </section>
      );
    }

    return (
      <section className="workspace-panel">
        <div className="panel-heading">
          <div>
            <span className="step-kicker">08 · VISIBLE AGENT TRACE</span>
            <h1>Every saved tool step</h1>
            <p>Sanitized parameters and returned values make the computation inspectable.</p>
          </div>
          <span className="count-badge">{traces.length} calls</span>
        </div>
        <div className="trace-stack">
          {traces.map((trace, index) => (
            <details key={trace.id} open={index === 0}>
              <summary>
                <span className="trace-number">{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <strong>{label(trace.step)}</strong>
                  <small>
                    {trace.tool}
                    {trace.trace_type ? ` · ${label(trace.trace_type)}` : ""}
                  </small>
                </div>
                <span className="trace-status">✓ {trace.status}</span>
              </summary>
              <div className="trace-body">
                <div><span>Parameters sent</span><pre>{JSON.stringify(trace.params_json, null, 2)}</pre></div>
                <div><span>Values returned</span><pre>{JSON.stringify(trace.display_output_json, null, 2)}</pre></div>
              </div>
            </details>
          ))}
        </div>
        {!traces.length ? <Notice>Generate a plan to create the visible tool trace.</Notice> : null}
      </section>
    );
  }

  return (
    <main>
      <header className="topbar">
        <a className="brand" href="#">
          <span>AS</span>
          <div><strong>AgriSense</strong><small>Bangladesh farm intelligence</small></div>
        </a>
        <div className="system-pills">
          <span><i /> Supabase-backed</span>
          <span><i /> Cited data</span>
          <span><i /> Farmer-safe</span>
        </div>
        {plan ? (
          <button className="quiet-button compact-button" onClick={reloadPlan} disabled={loading === "reload"}>
            {loading === "reload" ? "Reloading…" : "↻ Reload plan"}
          </button>
        ) : null}
      </header>

      <section className="intro">
        <span>AI FARM PLANNING · BANGLADESH</span>
        <h1>From a farm story to a <em>traceable</em> season plan.</h1>
        <p>
          Live weather, reviewed agronomy, transparent economics and every
          tool call—kept together in one guided workspace.
        </p>
      </section>

      <div className="app-shell">
        <aside className="capability-rail">
          <div className="progress-head">
            <div>
              <span>Plan readiness</span>
              <strong>{completedCount}/8</strong>
            </div>
            <div className="progress-track"><i style={{ width: `${completedCount * 12.5}%` }} /></div>
          </div>
          <nav aria-label="AgriSense capabilities">
            {capabilityNames.map(([name, detail], index) => {
              const step = index + 1;
              const locked = step > 2 && !plan;
              return (
                <button
                  type="button"
                  className={`${activeCapability === step ? "active" : ""} ${locked ? "locked" : ""}`}
                  onClick={() => !locked && setActiveCapability(step)}
                  key={name}
                  aria-current={activeCapability === step ? "step" : undefined}
                >
                  <span className="rail-number">
                    {completion[index] ? "✓" : String(step).padStart(2, "0")}
                  </span>
                  <span><strong>{name}</strong><small>{detail}</small></span>
                </button>
              );
            })}
          </nav>
          <div className="rail-note">
            <span>Evidence policy</span>
            <p>Missing data stays visible. Provisional values stay labelled.</p>
          </div>
        </aside>

        <div className="workspace">{renderCapability()}</div>

        <aside className="farm-profile">
          <div className="profile-head">
            <div><span>Farm profile</span><strong>{intake ? "In progress" : "Waiting"}</strong></div>
            <span className={`profile-dot ${intake ? "ready" : ""}`} />
          </div>
          <div className="profile-location">
            <span>⌖</span>
            <div>
              <strong>{location ? text(adm3.name) !== "—" ? text(adm3.name) : "Farm location selected" : "No location yet"}</strong>
              <small>{location?.label ?? "Use live location or Maps"}</small>
            </div>
          </div>
          <dl className="profile-facts">
            <div><dt>Area</dt><dd>{recognized.area_acres ? `${text(recognized.area_acres)} acre` : "—"}</dd></div>
            <div><dt>Soil</dt><dd>{label(recognized.soil_class)}</dd></div>
            <div><dt>Water</dt><dd>{label(recognized.water_availability)}</dd></div>
            <div><dt>Budget</dt><dd>{recognized.budget_bdt ? money(recognized.budget_bdt) : "—"}</dd></div>
            <div><dt>Season</dt><dd>{label(recognized.target_season)}</dd></div>
            <div><dt>Target crop</dt><dd>{rows(recognized.crop_ids).length ? rows(recognized.crop_ids).map((crop) => cropNames[text(crop)] ?? label(crop)).join(", ") : "Open"}</dd></div>
          </dl>
          {intake ? (
            <div className="profile-source">
              <span>Intake mode</span>
              <code>{intake.mode}</code>
            </div>
          ) : null}
          {plan ? (
            <div className="profile-session">
              <span>Saved plan</span>
              <code>{plan.session_id.slice(0, 8)}…</code>
              <small>{plan.trace_ids.length} trace records</small>
            </div>
          ) : null}
        </aside>
      </div>

      <footer>
        <strong>AgriSense AI</strong>
        <span>Source-grounded planning · Human review remains essential</span>
      </footer>

      <GoogleMapPicker
        open={mapOpen}
        onClose={() => setMapOpen(false)}
        onPick={(picked: PickedLocation) => void chooseLocation(picked)}
      />
    </main>
  );
}

function CropSelector({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <select
      className="crop-selector"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      aria-label="Selected crop"
    >
      {Object.entries(cropNames).map(([cropId, cropName]) => (
        <option value={cropId} key={cropId}>{cropName}</option>
      ))}
    </select>
  );
}
