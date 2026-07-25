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
  trace_ids?: string[];
  memory?: RecordValue;
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
  recommended_crop_id?: string | null;
  selection_source?: "awaiting_farmer" | "farmer" | "agent_default" | "unavailable";
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
  location?: RecordValue;
  weather_snapshot?: RecordValue | null;
  assessments?: RecordValue[];
  season_events?: { status: string; events: RecordValue[]; by_crop?: RecordValue[] };
  financials?: RecordValue;
  missing?: RecordValue[];
  unassessed?: RecordValue[];
  warnings?: string[];
  explanations?: RecordValue[];
  advanced?: RecordValue | null;
  financial_assumption_consent?: boolean;
  scenario?: RecordValue;
  intake_trace_session_id?: string;
  intake_trace_ids?: string[];
  farmer_project?: FarmerProject | null;
};
type FarmerProject = {
  project_id: string;
  plan_session_id?: string | null;
  intake_session_id?: string | null;
  name: string;
  status: string;
  access_mode?: "farm" | "guest";
  crop_id?: string | null;
  target_season?: string;
  sowing_date?: string | null;
  area_acres?: number;
  budget_bdt?: number | null;
  location?: RecordValue;
  saved_at?: string;
  last_weather_check?: string;
  weather_watch_status?: string;
  weather_alert_count?: number;
  adjusted_operation_count?: number;
  created_at?: string;
  last_activity_at?: string;
};
type ChatEntry = {
  id: string;
  role: "assistant" | "user";
  content: string;
};
type FinancialCostItem =
  | "seed"
  | "fertilizer_bundle"
  | "labor"
  | "irrigation"
  | "other";

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
const financialCostItems: {
  id: FinancialCostItem;
  label: string;
}[] = [
  { id: "seed", label: "Seed" },
  { id: "fertilizer_bundle", label: "Fertilizer" },
  { id: "labor", label: "Labor" },
  { id: "irrigation", label: "Irrigation" },
  { id: "other", label: "Other" },
];
const emptyFinancialCosts = (): Record<FinancialCostItem, string> => ({
  seed: "",
  fertilizer_bundle: "",
  labor: "",
  irrigation: "",
  other: "",
});
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
const responseError = (body: RecordValue, status: number) => {
  const detail = body.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  const structured = record(detail);
  const message =
    typeof structured.message === "string" ? structured.message.trim() : "";
  const missing = Array.isArray(structured.missing)
    ? structured.missing.filter(
        (item): item is string => typeof item === "string" && Boolean(item.trim()),
      )
    : [];
  const supportedSeason =
    typeof structured.supported_season === "string"
      ? structured.supported_season.trim()
      : "";
  const context = [
    missing.length ? `Missing: ${missing.join(", ")}.` : "",
    supportedSeason ? `Supported season: ${label(supportedSeason)}.` : "",
  ].filter(Boolean);
  if (message || context.length) return [message, ...context].filter(Boolean).join(" ");
  return `Request failed (${status})`;
};
const label = (value: unknown) =>
  text(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
const costItemLabel = (value: unknown) =>
  financialCostItems.find((item) => item.id === String(value))?.label ??
  label(value);
const money = (value: unknown) =>
  value == null ? "—" : `৳${Number(value).toLocaleString("en-BD", { maximumFractionDigits: 0 })}`;
const fitMeaning = (value: unknown) => {
  const code = String(value ?? "").toUpperCase();
  return (
    {
      S1: "Strong match",
      S2: "Moderate match",
      S3: "Marginal match",
      N: "Not suitable",
      UNASSESSED: "Not assessed",
    }[code] ?? label(value)
  );
};
const farmerSentence = (value: unknown) =>
  text(value)
    .replaceAll("S1", "strong match")
    .replaceAll("S2", "moderate match")
    .replaceAll("S3", "marginal match");
const entry = (role: ChatEntry["role"], content: string): ChatEntry => ({
  id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
  role,
  content,
});

function tracePresentation(trace: TraceRecord) {
  const key = `${trace.tool} ${trace.step}`.toLowerCase();
  const cropId =
    typeof trace.params_json.crop_id === "string"
      ? trace.params_json.crop_id
      : "";
  const cropSuffix = cropId
    ? ` for ${cropNames[cropId] ?? label(cropId)}`
    : "";
  if (key.includes("weather") || key.includes("open_meteo")) {
    return {
      title: "Fetching the farm forecast",
      detail: "Called Open-Meteo for rainfall, temperature and FAO reference evapotranspiration.",
    };
  }
  if (key.includes("geo") || key.includes("location")) {
    return {
      title: "Checking the farm area",
      detail: "Resolved the selected coordinates to administrative and agro-ecological context.",
    };
  }
  if (key.includes("retriev") || key.includes("vector") || key.includes("rag")) {
    return {
      title: `Looking up reviewed farm guidance${cropSuffix}`,
      detail: "Searched the curated knowledge base for crop, soil, calendar and fertilizer evidence.",
    };
  }
  if (key.includes("water")) {
    return {
      title: `Estimating crop water stress${cropSuffix}`,
      detail: "Applied the forecast to the daily FAO-56 water balance for each candidate crop.",
    };
  }
  if (key.includes("financial") || key.includes("profit")) {
    return {
      title: `Estimating farm costs and profit${cropSuffix}`,
      detail: "Scaled the disclosed cost, yield and price assumptions to this farm.",
    };
  }
  if (key.includes("rank")) {
    return {
      title: "Comparing the candidate crops",
      detail: "Combined soil fit, forecast water fit and rough profit using the disclosed ranking policy.",
    };
  }
  if (key.includes("season") || key.includes("schedule")) {
    return {
      title: "Building the dated season plan",
      detail: "Anchored reviewed operations and crop stages to the farmer’s sowing date.",
    };
  }
  if (key.includes("scenario")) {
    return {
      title: "Testing the what-if scenario",
      detail: "Held the saved forecast constant, changed only the selected rainfall and budget assumptions, then reranked.",
    };
  }
  if (key.includes("pest")) {
    return {
      title: "Screening weather-related crop risks",
      detail: "Compared the crop’s current growth stage with conservative pest and disease warning rules.",
    };
  }
  if (key.includes("advice")) {
    return {
      title: "Preparing plain-language explanations",
      detail: "Connected each recommendation to the farm inputs, calculations and reviewed sources that support it.",
    };
  }
  if (key.includes("advanced")) {
    return {
      title: "Preparing advanced farm advice",
      detail: "Built the weather watch, input schedule, pest screening and persistent-project view.",
    };
  }
  return {
    title: "Processing verified planning data",
    detail: "Completed one bounded step in the farm-planning workflow.",
  };
}

const planFromRanking = (ranking: Ranking): Plan => ({
  status: "partial",
  session_id: ranking.session_id,
  trace_ids: ranking.trace_ids,
  location: ranking.location ?? {},
  weather_snapshot: ranking.weather_snapshot,
  assessments: ranking.assessments ?? [],
  season_events: ranking.season_events ?? {
    status: "unavailable",
    events: [],
  },
  financials: ranking.financials ?? {
    status: "blocked_until_assumption_opt_in",
  },
  missing: ranking.missing ?? [],
  unassessed: ranking.unassessed ?? [],
  warnings: ranking.warnings ?? [],
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
  const [entryStage, setEntryStage] = useState<
    "login" | "projects" | "workspace"
  >("login");
  const [accessMode, setAccessMode] = useState<"farm" | "guest" | null>(null);
  const [activeProject, setActiveProject] = useState<FarmerProject | null>(null);
  const [projectNameInput, setProjectNameInput] = useState("");
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
  const [selectedCrop, setSelectedCrop] = useState("");
  const [includeFinance, setIncludeFinance] = useState(false);
  const [rememberFarm, setRememberFarm] = useState(false);
  const [farmerId, setFarmerId] = useState<string | null>(null);
  const [farmNameInput, setFarmNameInput] = useState("");
  const [farmAccessIdInput, setFarmAccessIdInput] = useState("");
  const [savedMemory, setSavedMemory] = useState<RecordValue | null>(null);
  const [savedProjects, setSavedProjects] = useState<FarmerProject[]>([]);
  const [sowingDate, setSowingDate] = useState("");
  const [soilTestClass, setSoilTestClass] = useState("");
  const [financialCostInputs, setFinancialCostInputs] =
    useState<Record<FinancialCostItem, string>>(emptyFinancialCosts);
  const [budgetInput, setBudgetInput] = useState("");
  const [scenarioRain, setScenarioRain] = useState("-30");
  const [scenarioBudget, setScenarioBudget] = useState("-40");
  const [scenarioResult, setScenarioResult] = useState<Ranking | null>(null);
  const [loading, setLoading] = useState<
    "location" | "chat" | "plan" | "reload" | "profile" | null
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
  const projectMonitorLastRunRef = useRef<Record<string, number>>({});

  useEffect(() => {
    const stored = window.localStorage.getItem("agrisense_farmer_id");
    if (stored) {
      setFarmAccessIdInput(stored);
    }
  }, []);

  useEffect(() => {
    if (!ranking || !selectedCrop) return;
    const evidence = record(ranking.evidence[selectedCrop]);
    const financial = record(evidence.financials);
    const nextCosts = emptyFinancialCosts();
    for (const item of rows(financial.line_items)) {
      const itemId = String(item.item) as FinancialCostItem;
      if (
        financialCostItems.some((candidate) => candidate.id === itemId) &&
        typeof item.cost_per_acre_bdt === "number"
      ) {
        nextCosts[itemId] = String(item.cost_per_acre_bdt);
      }
    }
    setFinancialCostInputs(nextCosts);
    setBudgetInput(
      ranking.budget_bdt == null ? "" : String(ranking.budget_bdt),
    );
  }, [ranking, selectedCrop]);

  async function json(response: Response) {
    const body = (await response.json().catch(() => ({}))) as RecordValue;
    if (!response.ok) {
      throw new Error(responseError(body, response.status));
    }
    return body;
  }

  function applySavedMemory(memoryValue: unknown) {
    const memory = record(memoryValue);
    setSavedMemory(Object.keys(memory).length ? memory : null);
    setSavedProjects(
      rows(memory.projects).filter(
        (item) => typeof item.project_id === "string",
      ) as unknown as FarmerProject[],
    );
  }

  async function refreshSavedMemory(id = farmerId) {
    if (!id || !rememberFarm) {
      applySavedMemory(null);
      return;
    }
    const response = await fetch(
      `/api/farmer/profile/${encodeURIComponent(id)}`,
      { cache: "no-store" },
    );
    if (response.status === 404) {
      applySavedMemory(null);
      return;
    }
    const body = await json(response);
    applySavedMemory(body.memory);
  }

  async function openFarmSession(action: "create" | "login" | "guest") {
    setLoading("profile");
    setError(null);
    try {
      const body = await json(
        await fetch("/api/farmer/session", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            action,
            farmer_id: action === "login" ? farmAccessIdInput.trim() : null,
            farm_name: action === "create" ? farmNameInput.trim() : null,
          }),
        }),
      );
      const id = String(body.farmer_id);
      setFarmerId(id);
      setRememberFarm(true);
      const nextAccessMode = body.session_mode === "guest" ? "guest" : "farm";
      setAccessMode(nextAccessMode);
      if (nextAccessMode === "farm") {
        window.localStorage.setItem("agrisense_farmer_id", id);
      }
      applySavedMemory(body.memory);
      const identity = record(record(body.memory).identity);
      if (typeof identity.farm_name === "string") {
        setFarmNameInput(identity.farm_name);
      }
      setFarmAccessIdInput("");
      setEntryStage("projects");
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "The farm profile could not be opened.",
      );
    } finally {
      setLoading(null);
    }
  }

  function logOutFarm() {
    if (accessMode === "farm") {
      window.localStorage.removeItem("agrisense_farmer_id");
    }
    setFarmerId(null);
    setRememberFarm(false);
    setAccessMode(null);
    setActiveProject(null);
    setEntryStage("login");
    setSavedMemory(null);
    setSavedProjects([]);
    setFarmNameInput("");
    setFarmAccessIdInput("");
    resetWorkspace();
  }

  function resetWorkspace() {
    setLocation(null);
    setIntake(null);
    setIntakeSessionId(null);
    setPlan(null);
    setRanking(null);
    setWeather(null);
    setTraces([]);
    setSelectedCrop("");
    setScenarioResult(null);
    setSowingDate("");
    setSoilTestClass("");
    setFinancialCostInputs(emptyFinancialCosts());
    setBudgetInput("");
    setActiveCapability(1);
    setChat([
      entry(
        "assistant",
        "শুরু করি—খামারের লোকেশন শেয়ার করুন, অথবা এক বাক্যে আপনার খামার ও লক্ষ্য সম্পর্কে বলুন।",
      ),
    ]);
  }

  async function createProject() {
    if (!farmerId || projectNameInput.trim().length < 2) return;
    setLoading("profile");
    setError(null);
    try {
      const body = await json(
        await fetch(
          `/api/farmer/profile/${encodeURIComponent(farmerId)}/projects`,
          {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ name: projectNameInput.trim() }),
          },
        ),
      );
      const project = record(body.project) as unknown as FarmerProject;
      resetWorkspace();
      setActiveProject(project);
      setProjectNameInput("");
      await refreshSavedMemory(farmerId);
      setEntryStage("workspace");
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "The project could not be created.",
      );
    } finally {
      setLoading(null);
    }
  }

  async function enterProject(project: FarmerProject) {
    setActiveProject(project);
    if (!project.plan_session_id) {
      resetWorkspace();
      setEntryStage("workspace");
      return;
    }
    await openSavedProject(project);
  }

  useEffect(() => {
    if (!farmerId || !rememberFarm) {
      applySavedMemory(null);
      return;
    }
    let cancelled = false;
    fetch(`/api/farmer/profile/${encodeURIComponent(farmerId)}`, {
      cache: "no-store",
    })
      .then(async (response) => {
        if (response.status === 404) {
          window.localStorage.removeItem("agrisense_farmer_id");
          setFarmerId(null);
          setRememberFarm(false);
          return null;
        }
        return json(response);
      })
      .then((body) => {
        if (!cancelled) applySavedMemory(body ? body.memory : null);
      })
      .catch((cause) => {
        if (!cancelled) {
          setError(
            cause instanceof Error
              ? cause.message
              : "Saved farmer profile could not be loaded.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [farmerId, rememberFarm]);

  const activeSavedProjectId =
    entryStage === "workspace" &&
    activeProject?.status === "active" &&
    activeProject.plan_session_id
      ? activeProject.project_id
      : null;

  useEffect(() => {
    if (!farmerId || !rememberFarm || !activeSavedProjectId) return;
    let cancelled = false;
    const refreshMonitor = async () => {
      const lastRun = projectMonitorLastRunRef.current[activeSavedProjectId] ?? 0;
      if (Date.now() - lastRun < 60_000) return;
      projectMonitorLastRunRef.current[activeSavedProjectId] = Date.now();
      try {
        const response = await fetch(
          `/api/farmer/profile/${encodeURIComponent(farmerId)}/projects/${encodeURIComponent(activeSavedProjectId)}/refresh`,
          { method: "POST" },
        );
        if (response.ok && !cancelled) {
          await refreshSavedMemory(farmerId);
        }
      } catch {
        // Monitoring retries on the next interval; it must not block the core flow.
      }
    };
    void refreshMonitor();
    const intervalId = window.setInterval(refreshMonitor, 15 * 60 * 1000);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [activeSavedProjectId, farmerId, rememberFarm]);

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
    event: "message" | "location_selected" | "profile_restore" = "message",
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
          farmer_id: rememberFarm ? farmerId : null,
          project_id: activeProject?.project_id ?? null,
          remember_profile: rememberFarm,
        }),
      }),
    )) as Intake;
    setIntake(nextIntake);
    setIntakeSessionId(nextIntake.session_id);
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

  async function restoreSavedProfile() {
    if (!farmerId || !rememberFarm || !savedMemory) return;
    setLoading("profile");
    setError(null);
    try {
      const restored = await runIntake(
        "Restore my saved farm profile.",
        location,
        "profile_restore",
      );
      const restoredLat = Number(restored.plan_input.lat);
      const restoredLon = Number(restored.plan_input.lon);
      if (
        !location &&
        Number.isFinite(restoredLat) &&
        Number.isFinite(restoredLon)
      ) {
        const savedLocation = record(savedMemory.location);
        setLocation({
          lat: restoredLat,
          lon: restoredLon,
          source:
            savedLocation.source === "live_location"
              ? "live_location"
              : "google_maps",
          label:
            typeof savedLocation.label === "string"
              ? savedLocation.label
              : "Restored farm location",
        });
      }
      setChat((current) => [
        ...current,
        entry("user", "Use my saved farm profile."),
        entry("assistant", restored.assistant_message),
      ]);
      await refreshSavedMemory(farmerId);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Saved farmer profile could not be restored.",
      );
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
    setSelectedCrop("");
    setTraces([]);
    setActiveCapability(1);
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

  async function loadTraces(...sessionIds: string[]) {
    const groups = await Promise.all(
      sessionIds.filter(Boolean).map(async (sessionId) => {
        const body = await json(
          await fetch(`/api/plan/preview/${encodeURIComponent(sessionId)}/traces`),
        );
        return rows(body.traces) as unknown as TraceRecord[];
      }),
    );
    setTraces(groups.flat());
  }

  async function requestPlan(selectedCropId: string | null) {
    if (!intake) return;
    if (!activeProject || !farmerId) {
      setError("Open a farm project before creating a plan.");
      return;
    }
    const input = intake.plan_input;
    if (input.lat == null || input.lon == null || input.soil_class == null) {
      setError("Complete the farm context and choose a location first.");
      return;
    }
    if (!(sowingDate || input.sowing_date)) {
      setError("Choose a sowing date so every season operation can be dated.");
      return;
    }
    if (input.target_season !== "rabi") {
      setError(
        "The reviewed three-crop planner currently supports Rabi only. Tell AgriSense “I want a Rabi plan” to correct the season before ranking.",
      );
      return;
    }
    if (!soilTestClass) {
      setError("Choose the laboratory soil-test class for fertilizer quantities.");
      return;
    }
    if (!includeFinance) {
      setError("Accept or edit the labelled financial assumptions to build a costed ranking.");
      return;
    }
    setLoading("plan");
    setError(null);
    try {
      if (!intakeSessionId) throw new Error("The conversational intake session is missing.");
      const overrides: Record<string, number> = {};
      for (const item of financialCostItems) {
        const rawValue = financialCostInputs[item.id].trim();
        if (!rawValue) continue;
        const value = Number(rawValue);
        if (!Number.isFinite(value) || value < 0) {
          throw new Error(`${item.label} cost must be zero or a positive number.`);
        }
        overrides[`${item.id}_cost_per_acre_bdt`] = value;
      }
      const editedBudget = budgetInput.trim()
        ? Number(budgetInput)
        : Number(input.budget_bdt);
      if (!Number.isFinite(editedBudget) || editedBudget < 0) {
        throw new Error("Total farm budget must be zero or a positive number.");
      }
      const overrideCropId = selectedCropId || selectedCrop;
      const financialOverrides =
        Object.keys(overrides).length > 0 && overrideCropId
          ? { [overrideCropId]: overrides }
          : {};
      const nextRanking = (await json(
        await fetch("/api/plan/from-conversation", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            session_id: intakeSessionId,
            lat: input.lat,
            lon: input.lon,
            starting_depletion_mm: Number(startingDepletion),
            irrigation_mm_per_day: Number(irrigationPerDay),
            forecast_days: 7,
            soil_test_class: soilTestClass,
            sowing_date: sowingDate || input.sowing_date,
            variety_id: input.variety_id,
            allow_assumptions: includeFinance,
            financial_overrides: financialOverrides,
            budget_bdt: editedBudget,
            farmer_id: rememberFarm ? farmerId : null,
            project_id: activeProject.project_id,
            remember_profile: rememberFarm,
            selected_crop_id: selectedCropId,
          }),
        }),
      )) as Ranking;
      setRanking(nextRanking);
      setPlan(planFromRanking(nextRanking));
      setScenarioResult(null);
      setSelectedCrop(nextRanking.chosen_crop_id ?? "");
      if (nextRanking.farmer_project) {
        setActiveProject(nextRanking.farmer_project);
      }
      await loadTraces(intakeSessionId, nextRanking.session_id);
      if (rememberFarm && farmerId) {
        if (nextRanking.farmer_project?.project_id) {
          projectMonitorLastRunRef.current[
            nextRanking.farmer_project.project_id
          ] = Date.now();
        }
        await refreshSavedMemory(farmerId);
      }
      setActiveCapability(nextRanking.chosen_crop_id ? 4 : 3);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to create plan.");
    } finally {
      setLoading(null);
    }
  }

  async function createRanking() {
    await requestPlan(null);
  }

  async function confirmCropSelection() {
    if (!selectedCrop || !ranking?.ranked.some((row) => row.crop_id === selectedCrop)) {
      setError("Select one of the ranked crops before building the season plan.");
      return;
    }
    await requestPlan(selectedCrop);
  }

  async function recalculatePlan() {
    if (!selectedCrop) {
      setError("The farmer must select a crop before recalculating the plan.");
      return;
    }
    await requestPlan(selectedCrop);
  }

  async function reloadPlan() {
    if (!plan) return;
    setLoading("reload");
    setError(null);
    try {
      const restored = (await json(
        await fetch(`/api/plan/preview/${encodeURIComponent(plan.session_id)}`),
      )) as unknown as Ranking;
      setRanking(restored);
      setPlan(planFromRanking(restored));
      setSelectedCrop(restored.chosen_crop_id ?? "");
      await loadTraces(
        restored.intake_trace_session_id ?? "",
        restored.session_id,
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to reload plan.");
    } finally {
      setLoading(null);
    }
  }

  async function openSavedProject(project: FarmerProject) {
    if (!farmerId) return;
    projectMonitorLastRunRef.current[project.project_id] = Date.now();
    setActiveProject(project);
    setEntryStage("workspace");
    if (!project.plan_session_id) {
      resetWorkspace();
      return;
    }
    setLoading("profile");
    setError(null);
    try {
      const refreshResponse = await fetch(
        `/api/farmer/profile/${encodeURIComponent(farmerId)}/projects/${encodeURIComponent(project.project_id)}/refresh`,
        {
          method: "POST",
        },
      );
      let restored: Ranking;
      if (refreshResponse.ok) {
        const refreshed = await json(refreshResponse);
        restored = record(refreshed.plan) as unknown as Ranking;
        const refreshedProject = record(refreshed.project) as unknown as FarmerProject;
        if (refreshedProject.project_id) setActiveProject(refreshedProject);
      } else {
        const failedBody = (await refreshResponse.json().catch(() => ({}))) as RecordValue;
        restored = (await json(
          await fetch(
            `/api/plan/preview/${encodeURIComponent(project.plan_session_id)}`,
          ),
        )) as unknown as Ranking;
        setError(
          `Saved plan opened, but live advice was not refreshed. ${responseError(
            failedBody,
            refreshResponse.status,
          )}`,
        );
      }
      setRanking(restored);
      setPlan(planFromRanking(restored));
      setSelectedCrop(restored.chosen_crop_id ?? "");
      setIncludeFinance(Boolean(restored.financial_assumption_consent));
      const restoredChosenPlan = record(restored.chosen_plan);
      if (typeof restoredChosenPlan.sowing_date === "string") {
        setSowingDate(restoredChosenPlan.sowing_date);
      }
      if (typeof restoredChosenPlan.soil_test_class === "string") {
        setSoilTestClass(restoredChosenPlan.soil_test_class);
      }
      if (restored.weather_snapshot) {
        setWeather(restored.weather_snapshot as Weather);
      }
      const projectLocation = record(project.location);
      const projectLat = Number(projectLocation.lat);
      const projectLon = Number(projectLocation.lon);
      if (Number.isFinite(projectLat) && Number.isFinite(projectLon)) {
        setLocation({
          lat: projectLat,
          lon: projectLon,
          source: "google_maps",
          label:
            typeof projectLocation.label === "string"
              ? projectLocation.label
              : "Saved project location",
        });
      }
      const restoredIntakeSessionId =
        restored.intake_trace_session_id ??
        project.intake_session_id ??
        null;
      if (restoredIntakeSessionId) {
        const restoredProfile = record(restored.profile_used);
        setIntakeSessionId(restoredIntakeSessionId);
        setIntake({
          session_id: restoredIntakeSessionId,
          assistant_message: "Saved project context restored.",
          next_field: null,
          answer_options: [],
          facts: [],
          missing: [],
          recognized: restoredProfile,
          plan_input: {
            ...restoredProfile,
            lat: projectLat,
            lon: projectLon,
          },
          retrieval: [],
          mode: "saved_project_restore_v1",
        });
      }
      await loadTraces(
        restored.intake_trace_session_id ?? "",
        restored.session_id,
      );
      await refreshSavedMemory(farmerId);
      setActiveCapability(restored.chosen_crop_id ? 9 : 3);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Saved project could not be opened.",
      );
    } finally {
      setLoading(null);
    }
  }

  async function runScenario() {
    if (!ranking || !location) return;
    setLoading("plan");
    setError(null);
    try {
      const revised = (await json(
        await fetch("/api/plan/scenario", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            base_session_id: ranking.session_id,
            farmer_id: farmerId,
            project_id: activeProject?.project_id ?? null,
            lat: location.lat,
            lon: location.lon,
            rainfall_change_percent: Number(scenarioRain) || 0,
            budget_change_percent: Number(scenarioBudget) || 0,
          }),
        }),
      )) as Ranking;
      setScenarioResult(revised);
      await loadTraces(
        intakeSessionId ?? "",
        ranking.session_id,
        revised.session_id,
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Scenario could not be simulated.");
    } finally {
      setLoading(null);
    }
  }

  const recognized = intake?.recognized ?? {};
  const savedIdentity = record(savedMemory?.identity);
  const savedRecognized = record(savedMemory?.recognized);
  const rankedProfile = record(ranking?.profile_used);
  const planningProfile = {
    ...savedRecognized,
    ...Object.fromEntries(
      Object.entries(recognized).filter(
        ([, value]) => value != null && value !== "",
      ),
    ),
    // The latest completed plan contains project-specific edits such as the
    // revised total budget, so it wins over the older intake/profile value.
    ...rankedProfile,
  };
  const currentFarmName =
    typeof savedIdentity.farm_name === "string"
      ? savedIdentity.farm_name
      : "Saved farm";
  const hasSavedFarmFacts = Object.keys(savedRecognized).length > 0;
  const planAdmin = record(plan?.location?.admin);
  const adm3 = record(planAdmin.adm3);
  const aezCandidates = rows(plan?.location?.aez_candidates);
  const hasFarmerSelectedPlan = Boolean(
    ranking?.selection_source === "farmer" &&
      ranking.chosen_crop_id &&
      ranking.chosen_plan,
  );
  const tier1Available = Boolean(
    hasFarmerSelectedPlan || savedMemory || savedProjects.length,
  );
  const chosenGrounding = record(record(ranking?.chosen_plan).grounding);
  const completion = [
    Boolean(intake),
    Boolean(weather),
    Boolean(ranking?.ranked.length),
    hasFarmerSelectedPlan && Boolean(plan?.season_events.events.length),
    hasFarmerSelectedPlan &&
      plan?.financials.status === "included_provisional_assumptions",
    hasFarmerSelectedPlan && Boolean(ranking?.explanations?.length),
    hasFarmerSelectedPlan &&
      Boolean(rows(chosenGrounding.chunks).length),
    hasFarmerSelectedPlan && Boolean(traces.length),
  ];
  const completedCount = completion.filter(Boolean).length;
  const supportedPlanningSeason = intake?.plan_input.target_season === "rabi";
  const canPlan = Boolean(
    intake &&
      intake.missing.length === 0 &&
      supportedPlanningSeason &&
      (sowingDate || intake.plan_input.sowing_date) &&
      soilTestClass &&
      includeFinance,
  );
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

          {intake &&
          intake.missing.length === 0 &&
          !supportedPlanningSeason ? (
            <Notice tone="warning">
              The farm profile says {label(intake.plan_input.target_season)}, but the
              reviewed three-crop planner currently supports Rabi only. Type “I want a
              Rabi plan” in the chat to correct the season; AgriSense will not change it
              without the farmer&apos;s instruction.
            </Notice>
          ) : null}

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
                  <small>Required for the final dated land-preparation-to-harvest plan.</small>
                </label>
                <label>
                  <span>Laboratory soil-test class</span>
                  <select
                    value={soilTestClass}
                    onChange={(event) => setSoilTestClass(event.target.value)}
                  >
                    <option value="">Choose a reviewed class</option>
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                  <small>Required for cited fertilizer quantities; do not guess from texture.</small>
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
                  <small>Required for ranking, cost, ROI and break-even; values stay labelled.</small>
                </span>
              </label>
              <div className={`memory-save-state ${rememberFarm ? "connected" : ""}`}>
                <span>{rememberFarm ? "✓" : "○"}</span>
                <div>
                  <strong>
                    This work is saved inside {activeProject?.name ?? "the active project"}
                  </strong>
                  <small>
                    Intake, rounded location, ranking, selected crop, plan and
                    scenarios use this project&apos;s database records.
                  </small>
                </div>
              </div>
              <button
                type="button"
                className="primary-button"
                onClick={createRanking}
                disabled={!canPlan || loading === "plan"}
              >
                {loading === "plan" ? "Ranking crops…" : "Rank 3 candidate crops →"}
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
      const recommendedCrop = ranking?.recommended_crop_id ?? null;
      const chosenCrop = ranking?.chosen_crop_id ?? null;
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
                <strong>Best options for this farm</strong>
                {recommendedCrop ? (
                  <span>
                    Agent recommendation:{" "}
                    {cropNames[recommendedCrop] ?? label(recommendedCrop)}
                  </span>
                ) : null}
              </div>
              {ranking.ranked.map((row) => (
                <button
                  type="button"
                  key={row.crop_id}
                  className={`ranked-row ${row.crop_id === selectedCrop ? "selected" : ""}`}
                  onClick={() => setSelectedCrop(row.crop_id)}
                  aria-pressed={row.crop_id === selectedCrop}
                >
                  <span className="ranked-rank">#{row.rank}</span>
                  <span className="ranked-name">
                    {cropNames[row.crop_id] ?? label(row.crop_id)}
                  </span>
                  <span className="ranked-metric">
                    Soil: {fitMeaning(row.soil_suitability_class)}
                  </span>
                  <span className="ranked-metric">
                    Water: {fitMeaning(row.water_class)}
                  </span>
                  <span className="ranked-metric">Risk {label(row.risk_level)}</span>
                  <span className="ranked-metric strong">{money(row.rough_profit_bdt)}</span>
                  {row.crop_id === recommendedCrop ? (
                    <span className="recommendation-pill">Agent recommended</span>
                  ) : null}
                  {row.fits_budget != null ? (
                    <span className={`budget-pill ${row.fits_budget ? "ok" : "over"}`}>
                      {row.fits_budget ? "Within budget" : "Over budget"}
                    </span>
                  ) : null}
                  <span className="ranked-why">
                    <strong>Why this rank:</strong>{" "}
                    {fitMeaning(row.soil_suitability_class)} soil,{" "}
                    {fitMeaning(row.water_class).toLowerCase()} forecast water conditions
                    and about {money(row.rough_profit_bdt)} net profit
                    {row.fits_budget === true
                      ? " while staying within the farmer’s budget."
                      : row.fits_budget === false
                        ? ", but the expected cost is above the farmer’s budget."
                        : "."}
                  </span>
                </button>
              ))}
              <details className="ranking-method">
                <summary>How the three crops were compared</summary>
                <p>
                  Soil fit and forecast water fit each contribute 40%; rough
                  profit contributes 20%. S1 means a strong match, S2 moderate,
                  and S3 marginal. Policy: {text(ranking.policy)}
                </p>
              </details>
              <div className="crop-choice-action">
                <div>
                  <strong>
                    {selectedCrop
                      ? chosenCrop === selectedCrop
                        ? `Farmer selected: ${cropNames[selectedCrop] ?? label(selectedCrop)}`
                        : `Your selection: ${cropNames[selectedCrop] ?? label(selectedCrop)}`
                      : "No crop selected"}
                  </strong>
                  <small>
                    The recommendation is guidance only. The dated season plan is
                    generated only after the farmer confirms a crop.
                  </small>
                </div>
                <button
                  type="button"
                  className="primary-button"
                  onClick={confirmCropSelection}
                  disabled={
                    !selectedCrop ||
                    loading === "plan" ||
                    chosenCrop === selectedCrop
                  }
                >
                  {loading === "plan"
                    ? "Building selected plan…"
                    : !selectedCrop
                      ? "Select a crop above"
                      : chosenCrop === selectedCrop
                        ? "Selection confirmed"
                        : chosenCrop
                          ? `Change plan to ${cropNames[selectedCrop] ?? label(selectedCrop)}`
                          : `Build plan for ${cropNames[selectedCrop] ?? label(selectedCrop)} →`}
                </button>
              </div>
            </div>
          ) : null}
          <div className="crop-grid">
            {plan?.assessments.map((item, index) => {
              const rankedRow = ranking?.ranked.find(
                (row) => row.crop_id === item.crop_id,
              );
              return (
                <article
                  className="crop-card"
                  key={text(item.crop_id)}
                >
                  <div className="crop-card-top">
                    <span className="candidate-number">0{index + 1}</span>
                    <span className={`fit-pill ${item.soil_class === "unassessed" ? "pending" : ""}`}>
                      {fitMeaning(item.soil_class)}
                    </span>
                  </div>
                  <h2>{cropNames[text(item.crop_id)] ?? label(item.crop_id)}</h2>
                  <p>{cropNamesBn[text(item.crop_id)]}</p>
                  <dl>
                    <div><dt>Soil fit</dt><dd>{fitMeaning(item.soil_class)}</dd></div>
                    <div><dt>Water</dt><dd>{fitMeaning(item.water_class)}</dd></div>
                    <div><dt>Ranking</dt><dd>{rankedRow ? `#${rankedRow.rank}` : "Unassessed"}</dd></div>
                  </dl>
                  <SourceLine item={record(item.soil_evidence)} />
                </article>
              );
            })}
          </div>
          <Notice tone={ranking?.ranked?.length ? "info" : "warning"}>
            {ranking?.ranked?.length
              ? "The order combines reviewed soil suitability, forecast-driven water stress and provisional profit. The farmer—not the agent—chooses which crop receives a dated plan."
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
      const seasonSources = Array.from(
        new Set(
          timelineEvents
            .map((item) => text(item.source_id))
            .filter((source) => source !== "—"),
        ),
      );
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
            <span className="mode-badge">
              Farmer selected · {cropNames[selectedCrop] ?? label(selectedCrop)}
            </span>
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
          {timelineEvents.length ? (
            <div className="plan-why">
              <div className="plan-why-head">
                <span>WHY THIS PLAN LOOKS THIS WAY</span>
                <h2>From the farmer’s date to practical field actions</h2>
              </div>
              <div className="plan-why-grid">
                <article>
                  <span>1</span>
                  <div>
                    <strong>Dates start from your sowing choice</strong>
                    <p>
                      AgriSense uses {text(chosenPlan.sowing_date || sowingDate)} as
                      the anchor, then places reviewed crop stages and operations
                      on the calendar.
                    </p>
                  </div>
                </article>
                <article>
                  <span>2</span>
                  <div>
                    <strong>Water checks follow crop stages</strong>
                    <p>
                      Rainfall, evapotranspiration, starting moisture deficit and
                      planned irrigation determine when water stress needs attention.
                    </p>
                  </div>
                </article>
                <article>
                  <span>3</span>
                  <div>
                    <strong>Fertilizer stays tied to the soil test</strong>
                    <p>
                      Quantities use the farmer-selected{" "}
                      {label(chosenPlan.soil_test_class || soilTestClass)} soil-test
                      class and remain cited; they are not guessed from the location.
                    </p>
                  </div>
                </article>
              </div>
              <p className="plan-source-summary">
                Reviewed sources used: {seasonSources.join(", ") || "source attached to each operation"}.
              </p>
            </div>
          ) : null}
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
            <span className="mode-badge">
              Farmer selected · {cropNames[selectedCrop] ?? label(selectedCrop)}
            </span>
          </div>
          {ranking?.budget_bdt != null && fitsBudget != null ? (
            <Notice tone={fitsBudget ? "info" : "danger"}>
              Farmer budget {money(ranking.budget_bdt)} ·{" "}
              {fitsBudget ? "this crop fits the budget" : "this crop exceeds the budget"}{" "}
              (total cost {money(rankEvidence.total_cost_bdt)}).
            </Notice>
          ) : null}
          <div className="financial-editor">
            <div className="financial-editor-head">
              <div>
                <strong>Edit your cost assumptions</strong>
                <small>Costs are per acre; totals below scale to the farm area.</small>
              </div>
              <span>{text(planningProfile.area_acres)} acre farm</span>
            </div>
            <div className="assessment-details financial-cost-inputs">
              {financialCostItems.map((item) => (
                <label key={item.id}>
                  <span>{item.label} (BDT/acre)</span>
                  <input
                    type="number"
                    min="0"
                    step="100"
                    value={financialCostInputs[item.id]}
                    onChange={(event) =>
                      setFinancialCostInputs((current) => ({
                        ...current,
                        [item.id]: event.target.value,
                      }))
                    }
                    placeholder="Enter cost"
                  />
                </label>
              ))}
              <label className="budget-input">
                <span>Total farm budget (BDT)</span>
                <input
                  type="number"
                  min="0"
                  step="500"
                  value={budgetInput}
                  onChange={(event) => setBudgetInput(event.target.value)}
                  placeholder="Enter total budget"
                />
                <small>Budget fit is recalculated for every ranked crop.</small>
              </label>
            </div>
            <button
              type="button"
              className="primary-button financial-recalculate"
              onClick={recalculatePlan}
              disabled={loading === "plan"}
            >
              {loading === "plan" ? "Updating costs…" : "Update final costs and budget"}
            </button>
          </div>
          {error ? <Notice tone="danger">{error}</Notice> : null}
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
                        <td>{costItemLabel(item.item)}</td>
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
                onClick={recalculatePlan}
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
                        <td>{costItemLabel(item.item)}</td>
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
      const chosenRow = ranking?.ranked.find(
        (item) => item.crop_id === ranking.chosen_crop_id,
      );
      return (
        <section className="workspace-panel">
          <div className="panel-heading">
            <div>
              <span className="step-kicker">06 · EXPLAINED REASONING</span>
              <h1>Why the plan says what it says</h1>
              <p>Farmer inputs, retrieved data, decisions and unresolved limits stay visible.</p>
            </div>
            <span className="mode-badge">Plain-language decision trail</span>
          </div>
          <div className="reason-grid">
            <div className="reason-card">
              <span className="card-label">Farm evidence used</span>
              <h2>{text(adm3.name) || "Selected farm"}</h2>
              <ul>
                <li><span>Soil</span><strong>{label(planningProfile.soil_class)}</strong></li>
                <li><span>Drainage</span><strong>{label(planningProfile.drainage_condition)}</strong></li>
                <li><span>Area</span><strong>{text(planningProfile.area_acres)} acre</strong></li>
                <li><span>Water</span><strong>{label(planningProfile.water_availability)}</strong></li>
                <li><span>Season</span><strong>{label(planningProfile.target_season)}</strong></li>
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
          <div className="decision-flow">
            <article>
              <span>01</span>
              <div>
                <strong>Understood the farm</strong>
                <p>
                  Used only the farmer-confirmed area, soil, drainage, water,
                  season and budget. Location selection did not invent any of
                  these facts.
                </p>
              </div>
            </article>
            <article>
              <span>02</span>
              <div>
                <strong>Checked live conditions</strong>
                <p>
                  Open-Meteo rainfall and evapotranspiration were applied to an
                  FAO-56 daily water balance for each candidate crop.
                </p>
              </div>
            </article>
            <article>
              <span>03</span>
              <div>
                <strong>Compared the three choices</strong>
                <p>
                  Soil and water each carried 40% of the ranking; provisional
                  net profit carried 20%. Missing factors would exclude a crop
                  instead of being fabricated.
                </p>
              </div>
            </article>
            <article>
              <span>04</span>
              <div>
                <strong>The farmer made the final choice</strong>
                <p>
                  {ranking?.chosen_crop_id
                    ? `${cropNames[ranking.chosen_crop_id] ?? label(ranking.chosen_crop_id)} was confirmed by the farmer. Its soil fit is ${fitMeaning(chosenRow?.soil_suitability_class)}, its forecast water fit is ${fitMeaning(chosenRow?.water_class)}, and the rough net profit is ${money(chosenRow?.rough_profit_bdt)}.`
                    : "AgriSense has ranked the choices, but no dated crop plan is created until the farmer confirms one."}
                </p>
              </div>
            </article>
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
              <h1>Reviewed guidance used for the chosen crop</h1>
              <p>Only the evidence that supports the farmer’s selected crop is shown here.</p>
            </div>
            <span className="count-badge">
              {rows(chosenGrounding.chunks).length} sources
            </span>
          </div>
          {(() => {
            const grounding = record(record(ranking?.chosen_plan).grounding);
            const chunks = rows(grounding.chunks).filter(
              (item, index, all) =>
                all.findIndex(
                  (candidate) =>
                    `${text(candidate.source_id)}|${text(candidate.source_locator)}|${text(candidate.text)}` ===
                    `${text(item.source_id)}|${text(item.source_locator)}|${text(item.text)}`,
                ) === index,
            );
            if (!ranking?.chosen_plan) return null;
            return (
              <div className="grounding-block">
                <div className="grounding-head">
                  <strong>
                    Why this advice is trustworthy ·{" "}
                    {cropNames[text(record(ranking.chosen_plan).crop_id)] ??
                      label(record(ranking.chosen_plan).crop_id)}
                  </strong>
                  <span>{chunks.length} reviewed item(s)</span>
                </div>
                {chunks.length ? (
                  chunks.map((item) => (
                    <article className="grounding-chunk" key={text(item.chunk_id)}>
                      <div className="rag-meta">
                        <span>{label(item.topic)}</span>
                        {item.crop ? (
                          <span>{cropNames[text(item.crop)] ?? label(item.crop)}</span>
                        ) : null}
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
          {!ranking?.chosen_plan ? (
            <Notice>Confirm a crop to see the reviewed guidance used for its plan.</Notice>
          ) : null}
          <Notice tone="info">
            Retrieval similarity scores and chunk IDs are internal diagnostics.
            They are intentionally hidden from the farmer view.
          </Notice>
        </section>
      );
    }

    if (activeCapability === 8) {
      return (
        <section className="workspace-panel">
          <div className="panel-heading">
            <div>
              <span className="step-kicker">08 · VISIBLE AGENT TRACE</span>
              <h1>What AgriSense did for this plan</h1>
              <p>A readable activity timeline first; technical payloads stay optional.</p>
            </div>
            <span className="count-badge">{traces.length} activities</span>
          </div>
          <div className="trace-stack">
            {traces.map((trace, index) => {
              const presentation = tracePresentation(trace);
              return (
                <article className="agent-activity" key={trace.id}>
                  <span className="trace-number">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <strong>{presentation.title}</strong>
                    <p>{presentation.detail}</p>
                    <span className="activity-tool">
                      {trace.tool.includes("weather") ? "Open-Meteo" : trace.tool}
                    </span>
                    <details className="technical-trace">
                      <summary>Technical call details</summary>
                      <div className="trace-body">
                        <div><span>Parameters sent</span><pre>{JSON.stringify(trace.params_json, null, 2)}</pre></div>
                        <div><span>Values returned</span><pre>{JSON.stringify(trace.display_output_json, null, 2)}</pre></div>
                      </div>
                    </details>
                  </div>
                  <span className="trace-status">✓ Completed</span>
                </article>
              );
            })}
          </div>
          {!traces.length ? <Notice>Generate a plan to see its activity timeline.</Notice> : null}
        </section>
      );
    }

    const advanced = record(ranking?.advanced);
    const watch = record(advanced.weather_watch);
    const scheduler = record(advanced.input_scheduler);
    const pestRisk = record(advanced.pest_disease_risk);
    const simulated = record(scenarioResult?.scenario);
    return (
      <section className="workspace-panel">
        <div className="panel-heading">
          <div>
            <span className="step-kicker">TIER 1 · ADVANCED ADVICE</span>
            <h1>Memory, weather actions and what-if planning</h1>
            <p>All five advanced capabilities are inspectable and remain fail-closed.</p>
          </div>
          <span className="mode-badge">{ranking ? "Active" : "Waiting for plan"}</span>
        </div>

        <div className="reason-grid">
          <div className="reason-card">
            <span className="card-label">Persistent memory</span>
            <h2>{rememberFarm ? "Farm profile logged in" : "Not logged in"}</h2>
            <p>
              {savedMemory
                ? "This farm keeps confirmed facts and projects across sessions. Saved facts are applied only after the farmer chooses Use saved profile."
                : "Log in or create a farm profile to keep confirmed facts and projects after this session."}
            </p>
            <ul className="memory-schema-list">
              <li><strong>Farm profile</strong><span>name and confirmed farm facts</span></li>
              <li><strong>Farm location</strong><span>consented and rounded to 6 decimals</span></li>
              <li><strong>Recent context</strong><span>maximum 8 short chat entries</span></li>
              <li><strong>Projects</strong><span>maximum 10 farmer-selected crop plans</span></li>
            </ul>
            {savedMemory ? (
              <button
                type="button"
                className="quiet-button compact-button"
                onClick={restoreSavedProfile}
                disabled={loading === "profile"}
              >
                Use saved profile
              </button>
            ) : null}
          </div>
          <div className="reason-card">
            <span className="card-label">Weather-triggered advice</span>
            <h2>{label(watch.status)}</h2>
            {rows(watch.alerts).map((item) => (
              <p key={`${text(item.trigger)}-${text(item.date)}`}>
                <strong>{label(item.trigger)}</strong> · {text(item.value)} {text(item.unit)} · {text(item.action)}
              </p>
            ))}
            {!rows(watch.alerts).length ? <p>No trigger in the current forecast window.</p> : null}
            {rows(watch.adjusted_events).map((item, index) => (
              <p key={`adjusted-${index}`}>
                <strong>Plan adjusted</strong> · {text(item.weather_adjustment)}
              </p>
            ))}
          </div>
        </div>

        <div className="grounding-block">
          <div className="grounding-head">
            <strong>Saved farm projects</strong>
            <span>{savedProjects.length} saved</span>
          </div>
          {savedProjects.map((project) => (
            <article className="project-row" key={project.project_id}>
              <div>
                <strong>{project.name}</strong>
                <small>
                  {label(project.status)} · weather{" "}
                  {label(project.weather_watch_status)}
                </small>
              </div>
              <button
                type="button"
                className="quiet-button compact-button"
                onClick={() => openSavedProject(project)}
                disabled={loading === "profile"}
              >
                Open + refresh
              </button>
            </article>
          ))}
          {!savedProjects.length ? (
            <p className="empty-copy">
              Log in to a farm, then confirm a crop to create a monitored project.
            </p>
          ) : null}
        </div>

        <div className="grounding-block">
          <div className="grounding-head">
            <strong>Fertilizer and irrigation scheduler</strong>
            <span>
              {label(scheduler.status)} · {label(scheduler.crop_id)} · soil test{" "}
              {label(scheduler.soil_test_class)}
            </span>
          </div>
          {rows(scheduler.fertilizer).map((item, index) => (
            <article className="grounding-chunk" key={`fertilizer-${index}`}>
              <strong>{text(item.date_start || item.date)} · {text(item.timing)}</strong>
              <ul className="quantity-list">
                {rows(item.quantities).map((quantity, quantityIndex) => (
                  <li key={`${text(quantity.nutrient)}-${quantityIndex}`}>
                    <span>{label(quantity.nutrient)}</span>
                    <strong>
                      {text(quantity.total_min_for_farm)}
                      {quantity.total_min_for_farm !== quantity.total_max_for_farm
                        ? `–${text(quantity.total_max_for_farm)}`
                        : ""}{" "}
                      {text(quantity.farm_total_unit)}
                    </strong>
                  </li>
                ))}
              </ul>
              <p>Budgeted cost: {money(item.allocated_cost_bdt)}</p>
              <SourceLine item={item} />
            </article>
          ))}
          {rows(scheduler.irrigation).map((item, index) => (
            <article className="grounding-chunk" key={`irrigation-${index}`}>
              <strong>{text(item.date)} · {label(item.stage)} irrigation check</strong>
              <p>{text(item.planned_net_depth_mm)} mm planned · {money(item.allocated_cost_bdt)}</p>
            </article>
          ))}
        </div>

        <div className="reason-list">
          {rows(pestRisk.risks).map((item) => (
            <article key={text(item.name)}>
              <div><strong>{text(item.name)}</strong><span>{label(item.risk_level)}</span></div>
              <p>
                Growth stage: {label(item.growth_stage)} · weather trigger:{" "}
                {item.weather_triggered ? "yes" : "no"}
              </p>
              <p>Prevention: {rows(item.prevention).map(text).join(" ")}</p>
              <p>Treatment: {rows(item.treatment).map(text).join(" ")}</p>
              <small>Estimated scouting cost: {money(item.estimated_scouting_cost_bdt)}</small>
            </article>
          ))}
        </div>
        <Notice>{text(pestRisk.pesticide_safety)}</Notice>

        <div className="assessment-details">
          <label>
            <span>Rainfall change (%)</span>
            <input type="number" min="-100" max="300" value={scenarioRain} onChange={(event) => setScenarioRain(event.target.value)} />
          </label>
          <label>
            <span>Budget change (%)</span>
            <input type="number" min="-100" max="300" value={scenarioBudget} onChange={(event) => setScenarioBudget(event.target.value)} />
          </label>
          <button type="button" className="primary-button" onClick={runScenario} disabled={!ranking || loading === "plan"}>
            Simulate revised plan
          </button>
        </div>
        {scenarioResult ? (
          <div className="scenario-result">
            <div className="grounding-head">
              <strong>What could happen</strong>
              <span>Scenario, not a forecast</span>
            </div>
            <p>
              Budget {money(simulated.budget_before_bdt)} → {money(simulated.budget_after_bdt)};
              assumed rainfall change {text(simulated.rainfall_change_percent)}%.
            </p>
            <Notice tone="info">{text(simulated.summary)}</Notice>
            <div className="scenario-impact-grid">
              {rows(simulated.impacts).map((impact) => (
                <article
                  className={`scenario-impact ${text(impact.attention)}`}
                  key={text(impact.crop_id)}
                >
                  <div>
                    <strong>
                      {cropNames[text(impact.crop_id)] ?? label(impact.crop_id)}
                    </strong>
                    <span>
                      #{text(impact.rank_before)} → #{text(impact.rank_after)}
                    </span>
                  </div>
                  <h3>{text(impact.headline)}</h3>
                  <ul>
                    {rows(impact.messages).map((message, index) => (
                      <li key={`${text(impact.crop_id)}-${index}`}>
                        {farmerSentence(message)}
                      </li>
                    ))}
                  </ul>
                </article>
              ))}
            </div>
            <small>
              This keeps the saved weather snapshot fixed so the selected change
              can be compared fairly. It does not predict that the scenario will occur.
            </small>
          </div>
        ) : null}
      </section>
    );
  }

  if (entryStage === "login") {
    return (
      <main className="entry-page">
        <header className="entry-topbar">
          <div className="brand">
            <span>AS</span>
            <div>
              <strong>AgriSense</strong>
              <small>Bangladesh farm intelligence</small>
            </div>
          </div>
          <span className="database-badge">Database-backed farm planning</span>
        </header>
        <section className="login-hero">
          <div className="login-copy">
            <span>START HERE</span>
            <h1>Your farm plans, kept together.</h1>
            <p>
              Log in to a saved farm, create a new farm, or enter as a guest.
              You will create or open a project before using the advisor.
            </p>
            <div className="entry-flow" aria-label="AgriSense setup flow">
              <span><b>1</b> Farm login</span>
              <i>→</i>
              <span><b>2</b> Choose project</span>
              <i>→</i>
              <span><b>3</b> Farm advisor</span>
            </div>
          </div>
          <div className="login-panel">
            <form
              className="entry-form"
              onSubmit={(event) => {
                event.preventDefault();
                void openFarmSession("login");
              }}
            >
              <span className="card-label">RETURNING FARM</span>
              <h2>Log in</h2>
              <label>
                <span>Farm Access ID</span>
                <input
                  value={farmAccessIdInput}
                  onChange={(event) => setFarmAccessIdInput(event.target.value)}
                  placeholder="Paste your saved Farm Access ID"
                  autoComplete="off"
                />
              </label>
              <button
                type="submit"
                className="primary-button"
                disabled={!farmAccessIdInput.trim() || loading === "profile"}
              >
                {loading === "profile" ? "Opening…" : "Log in to farm"}
              </button>
            </form>
            <div className="entry-divider"><span>New here?</span></div>
            <form
              className="entry-form compact"
              onSubmit={(event) => {
                event.preventDefault();
                void openFarmSession("create");
              }}
            >
              <label>
                <span>New farm name</span>
                <input
                  value={farmNameInput}
                  onChange={(event) => setFarmNameInput(event.target.value)}
                  placeholder="e.g. Rahman Family Farm"
                />
              </label>
              <button
                type="submit"
                className="quiet-button"
                disabled={farmNameInput.trim().length < 2 || loading === "profile"}
              >
                Create farm
              </button>
            </form>
            <button
              type="button"
              className="guest-button"
              onClick={() => void openFarmSession("guest")}
              disabled={loading === "profile"}
            >
              Continue as guest
              <small>Still saved in the database for this guest session</small>
            </button>
            {error ? <Notice tone="danger">{error}</Notice> : null}
            <p className="auth-boundary">
              Farm Access IDs are demo access keys, not password-grade accounts.
              Keep yours private.
            </p>
          </div>
        </section>
      </main>
    );
  }

  if (entryStage === "projects" || !activeProject) {
    return (
      <main className="entry-page">
        <header className="entry-topbar">
          <div className="brand">
            <span>AS</span>
            <div>
              <strong>AgriSense</strong>
              <small>{currentFarmName}</small>
            </div>
          </div>
          <div className="entry-session-actions">
            <span>{accessMode === "guest" ? "Guest session" : "Farm logged in"}</span>
            <button type="button" className="quiet-button compact-button" onClick={logOutFarm}>
              Log out
            </button>
          </div>
        </header>
        <section className="project-hub">
          <div className="project-hub-head">
            <span>PROJECTS</span>
            <h1>What are you planning?</h1>
            <p>
              Every conversation, selected location, recommendation, confirmed
              crop, season plan, trace and scenario is stored under its project.
            </p>
          </div>
          <div className="project-create-card">
            <div>
              <span className="card-label">NEW PROJECT</span>
              <h2>Create a farm project</h2>
              <p>Name it by field, season, or goal so it is easy to find later.</p>
            </div>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void createProject();
              }}
            >
              <input
                value={projectNameInput}
                onChange={(event) => setProjectNameInput(event.target.value)}
                placeholder="e.g. North field · Rabi 2026"
                maxLength={80}
              />
              <button
                type="submit"
                className="primary-button"
                disabled={projectNameInput.trim().length < 2 || loading === "profile"}
              >
                {loading === "profile" ? "Creating…" : "Create and enter"}
              </button>
            </form>
          </div>
          <div className="project-list-head">
            <div>
              <strong>Your projects</strong>
              <small>{savedProjects.length} stored in Supabase</small>
            </div>
            {accessMode === "farm" && farmerId ? (
              <button
                type="button"
                className="quiet-button compact-button"
                onClick={() => {
                  if (!navigator.clipboard) {
                    setError("Clipboard access is unavailable in this browser.");
                    return;
                  }
                  void navigator.clipboard.writeText(farmerId).catch(() =>
                    setError("The Farm Access ID could not be copied."),
                  );
                }}
              >
                Copy Farm Access ID
              </button>
            ) : null}
          </div>
          <div className="project-card-grid">
            {savedProjects.map((project) => (
              <article className="project-card" key={project.project_id}>
                <div>
                  <span className={`project-status ${project.status}`}>
                    {label(project.status)}
                  </span>
                  <small>{project.access_mode === "guest" ? "Guest" : "Farm"} project</small>
                </div>
                <h2>{project.name}</h2>
                <p>
                  {project.crop_id
                    ? `${cropNames[project.crop_id] ?? label(project.crop_id)} · ${label(project.target_season)}`
                    : "Farm intake has not selected a crop yet."}
                </p>
                <button
                  type="button"
                  className="quiet-button"
                  onClick={() => void enterProject(project)}
                  disabled={loading === "profile"}
                >
                  {project.plan_session_id ? "Open project" : "Continue setup"} →
                </button>
              </article>
            ))}
            {!savedProjects.length ? (
              <div className="empty-projects">
                <span>＋</span>
                <strong>No projects yet</strong>
                <p>Create the first project above to enter the farm advisor.</p>
              </div>
            ) : null}
          </div>
          {accessMode === "guest" ? (
            <Notice tone="warning">
              Guest work is database-backed, but this guest session has no reusable
              login key. Create a named farm next time if you need to return after logout.
            </Notice>
          ) : null}
          {error ? <Notice tone="danger">{error}</Notice> : null}
        </section>
      </main>
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
          <span><i /> {activeProject.name}</span>
        </div>
        <button
          type="button"
          className="quiet-button compact-button"
          onClick={() => {
            setEntryStage("projects");
            setActiveProject(null);
          }}
        >
          ← Projects
        </button>
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
              const locked =
                step === 3
                  ? !ranking
                  : step > 3
                    ? !hasFarmerSelectedPlan
                    : false;
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
            <button
              type="button"
              className={`${activeCapability === 9 ? "active" : ""} ${!tier1Available ? "locked" : ""}`}
              onClick={() => tier1Available && setActiveCapability(9)}
              aria-current={activeCapability === 9 ? "step" : undefined}
            >
              <span className="rail-number">T1</span>
              <span><strong>Advanced advisor</strong><small>Memory · alerts · scenarios</small></span>
            </button>
          </nav>
          <div className="rail-note">
            <span>Evidence policy</span>
            <p>Missing data stays visible. Provisional values stay labelled.</p>
          </div>
        </aside>

        <div className="workspace">{renderCapability()}</div>

        <aside className="farm-profile">
          <div className="profile-head">
            <div>
              <span>{accessMode === "guest" ? "Guest farm" : "Farm"}</span>
              <strong>{currentFarmName}</strong>
            </div>
            <span className="profile-dot ready" />
          </div>
          <div className="farm-session-card active-project-card">
            <span>ACTIVE PROJECT</span>
            <strong>{activeProject.name}</strong>
            <small>
              {label(activeProject.status)} ·{" "}
              {activeProject.crop_id
                ? cropNames[activeProject.crop_id] ?? label(activeProject.crop_id)
                : "Crop not selected"}
            </small>
            <button
              type="button"
              className="quiet-button compact-button"
              onClick={() => {
                setEntryStage("projects");
                setActiveProject(null);
              }}
            >
              Switch project
            </button>
            <button
              type="button"
              className="quiet-button compact-button logout-button"
              onClick={logOutFarm}
            >
              Log out
            </button>
          </div>
          <div className="profile-location">
            <span>⌖</span>
            <div>
              <strong>{location ? text(adm3.name) !== "—" ? text(adm3.name) : "Farm location selected" : "No location yet"}</strong>
              <small>{location?.label ?? "Use live location or Maps"}</small>
            </div>
          </div>
          <dl className="profile-facts">
            <div><dt>Area</dt><dd>{planningProfile.area_acres ? `${text(planningProfile.area_acres)} acre` : "—"}</dd></div>
            <div><dt>Soil</dt><dd>{label(planningProfile.soil_class)}</dd></div>
            <div><dt>Water</dt><dd>{label(planningProfile.water_availability)}</dd></div>
            <div><dt>Budget</dt><dd>{planningProfile.budget_bdt ? money(planningProfile.budget_bdt) : "—"}</dd></div>
            <div><dt>Season</dt><dd>{label(planningProfile.target_season)}</dd></div>
            <div>
              <dt>Target crop</dt>
              <dd>
                {ranking?.chosen_crop_id
                  ? cropNames[ranking.chosen_crop_id] ?? label(ranking.chosen_crop_id)
                  : rows(planningProfile.crop_ids).length
                    ? rows(planningProfile.crop_ids)
                        .map((crop) => cropNames[text(crop)] ?? label(crop))
                        .join(", ")
                    : "Open"}
              </dd>
            </div>
          </dl>
          {intake ? (
            <div className="profile-source">
              <span>Intake mode</span>
              <code>{intake.mode}</code>
            </div>
          ) : null}
          {savedMemory && hasSavedFarmFacts ? (
            <div className="profile-session">
              <span>Saved farm memory</span>
              <code>Confirmed facts · {savedProjects.length} project(s)</code>
              <button
                type="button"
                className="quiet-button compact-button"
                onClick={restoreSavedProfile}
                disabled={loading === "profile"}
              >
                Use saved profile
              </button>
            </div>
          ) : null}
          {savedProjects.slice(0, 3).map((project) => (
            <div className="profile-session" key={project.project_id}>
              <span>Farm project</span>
              <code>{project.name}</code>
              <button
                type="button"
                className="quiet-button compact-button"
                onClick={() => openSavedProject(project)}
                disabled={loading === "profile"}
              >
                Open + refresh
              </button>
            </div>
          ))}
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
