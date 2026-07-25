"use client";

import { ChangeEvent, DragEvent, useEffect, useRef, useState } from "react";
import styles from "./plant-health.module.css";

type Language = "en" | "bn";
type RecordValue = Record<string, unknown>;
type Suggestion = {
  id: string;
  name: string;
  scientific_or_provider_name?: string;
  confidence: number;
  description?: string | null;
  prevention?: string | null;
  field_check?: string | null;
};
type Diagnosis = {
  provider: string;
  diagnosed_at: string;
  language?: Language;
  status: "healthy" | "possible_issue" | "not_a_plant" | "inconclusive";
  plant_detected: { value?: boolean | null; confidence?: number | null };
  healthy: { value?: boolean | null; confidence?: number | null };
  suggestions: Suggestion[];
  follow_up_question?: string | null;
  confidence_note?: string | null;
  safety: string;
};
type RecognitionEventLike = {
  results: { [index: number]: { [index: number]: { transcript: string } } };
};
type RecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: RecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
};
type RecognitionConstructor = new () => RecognitionLike;

const COPY = {
  en: {
    brandSub: "Bangladesh farm intelligence",
    back: "← Farm planning",
    eyebrow: "TIER 2 · PLANT HEALTH",
    heroTitle: "Spot a crop problem from a photo.",
    heroBody: "Photograph the affected part. AgriSense securely sends the image through its backend to Gemini and returns a cautious visual screening.",
    provider: "Analyzed with Google Gemini",
    listenIntro: "Listen to instructions",
    stopVoice: "Stop voice",
    addTitle: "Add a crop photo",
    addBody: "Use a close, sharp photo of the affected leaf, stem, fruit or pest.",
    choose: "Take or upload photo",
    chooseAnother: "Choose another photo",
    tipClose: "Move close",
    tipCloseBody: "Fill the frame with symptoms.",
    tipLight: "Use daylight",
    tipLightBody: "Avoid shadows and filters.",
    tipSharp: "Keep it sharp",
    tipSharpBody: "Retake blurred photographs.",
    notesLabel: "What did you notice? (optional)",
    notesPlaceholder: "For example: spots started three days ago and are under the leaves.",
    dictate: "Speak",
    dictating: "Listening…",
    analyze: "Check plant health",
    analyzing: "Checking plant health…",
    privacy: "Your image and optional transcript go to Gemini only after you press “Check plant health.” The API key never enters the browser, and AgriSense does not upload microphone audio.",
    report: "PLANT HEALTH REPORT",
    emptyTitle: "Your results will appear here.",
    emptyBody: "Possible conditions, estimated confidence and safer next steps will stay together.",
    listenResult: "Listen to result",
    plantEstimate: "Plant estimate",
    healthyEstimate: "Healthy estimate",
    likely: "Likely causes",
    top: "Top",
    prevention: "Prevention",
    checkNext: "Check next",
    fieldCheck: "Check in the field",
    screening: "Screening only",
    unsupportedSpeech: "Voice is not supported in this browser. You can continue by typing and reading.",
    speechError: "Voice input could not start. Check browser microphone permission or type the notes.",
    invalidType: "Upload a JPEG, PNG or WebP image.",
    tooLarge: "The image is larger than the 8 MB limit.",
    failed: "The image could not be assessed.",
    introSpeech: "Take a clear close photo of the affected leaf, stem, fruit, or pest. Use daylight and keep the symptom in focus. You may also describe what you noticed by typing or speaking.",
    statuses: {
      healthy: ["No issue detected", "This plant appears healthy", "Gemini did not find a clear visual health issue in this photo."],
      possible_issue: ["Possible issue found", "Review these likely causes", "Image symptoms can overlap, so compare more than one possibility."],
      not_a_plant: ["Plant not detected", "Try another photo", "Fill the frame with one affected leaf, stem, fruit or visible pest."],
      inconclusive: ["Not enough evidence", "The result is inconclusive", "Retake the image in daylight with the affected area in sharp focus."],
    },
  },
  bn: {
    brandSub: "বাংলাদেশের কৃষি সহায়তা",
    back: "← খামার পরিকল্পনা",
    eyebrow: "টিয়ার ২ · গাছের স্বাস্থ্য",
    heroTitle: "ছবি থেকে ফসলের সমস্যা দেখুন।",
    heroBody: "আক্রান্ত অংশের ছবি তুলুন। অ্যাগ্রিসেন্স নিরাপদে ব্যাকএন্ডের মাধ্যমে ছবিটি জেমিনিতে পাঠিয়ে সতর্কভাবে প্রাথমিক বিশ্লেষণ দেখাবে।",
    provider: "Google Gemini দিয়ে বিশ্লেষণ",
    listenIntro: "নির্দেশনা শুনুন",
    stopVoice: "শোনা বন্ধ করুন",
    addTitle: "ফসলের ছবি দিন",
    addBody: "আক্রান্ত পাতা, কাণ্ড, ফল বা পোকার কাছ থেকে পরিষ্কার ছবি তুলুন।",
    choose: "ছবি তুলুন বা আপলোড করুন",
    chooseAnother: "অন্য ছবি দিন",
    tipClose: "কাছে যান",
    tipCloseBody: "লক্ষণটি পুরো ফ্রেমে রাখুন।",
    tipLight: "দিনের আলো নিন",
    tipLightBody: "ছায়া ও ফিল্টার এড়িয়ে চলুন।",
    tipSharp: "ছবি পরিষ্কার রাখুন",
    tipSharpBody: "ঝাপসা হলে আবার তুলুন।",
    notesLabel: "আপনি কী দেখেছেন? (ঐচ্ছিক)",
    notesPlaceholder: "যেমন: তিন দিন আগে দাগ শুরু হয়েছে এবং পাতার নিচেও আছে।",
    dictate: "বলে লিখুন",
    dictating: "শুনছি…",
    analyze: "গাছের স্বাস্থ্য পরীক্ষা করুন",
    analyzing: "গাছের স্বাস্থ্য পরীক্ষা হচ্ছে…",
    privacy: "“গাছের স্বাস্থ্য পরীক্ষা করুন” চাপার পরেই ছবি ও ঐচ্ছিক কথার লিখিত রূপ জেমিনিতে যায়। API কী ব্রাউজারে আসে না এবং অ্যাগ্রিসেন্স মাইক্রোফোনের অডিও আপলোড করে না।",
    report: "গাছের স্বাস্থ্য প্রতিবেদন",
    emptyTitle: "ফলাফল এখানে দেখা যাবে।",
    emptyBody: "সম্ভাব্য সমস্যা, আনুমানিক নির্ভরতা এবং নিরাপদ পরবর্তী পদক্ষেপ একসঙ্গে থাকবে।",
    listenResult: "ফলাফল শুনুন",
    plantEstimate: "গাছ হওয়ার অনুমান",
    healthyEstimate: "সুস্থতার অনুমান",
    likely: "সম্ভাব্য কারণ",
    top: "সেরা",
    prevention: "প্রতিরোধ",
    checkNext: "এরপর দেখুন",
    fieldCheck: "জমিতে যাচাই করুন",
    screening: "শুধু প্রাথমিক যাচাই",
    unsupportedSpeech: "এই ব্রাউজারে ভয়েস সুবিধা নেই। আপনি লিখে ও পড়ে ব্যবহার চালিয়ে যেতে পারবেন।",
    speechError: "ভয়েস ইনপুট শুরু হয়নি। ব্রাউজারের মাইক্রোফোন অনুমতি দেখুন অথবা লিখে জানান।",
    invalidType: "JPEG, PNG বা WebP ছবি দিন।",
    tooLarge: "ছবিটি ৮ MB সীমার চেয়ে বড়।",
    failed: "ছবিটি বিশ্লেষণ করা যায়নি।",
    introSpeech: "আক্রান্ত পাতা, কাণ্ড, ফল বা পোকার কাছ থেকে পরিষ্কার ছবি তুলুন। দিনের আলো ব্যবহার করুন এবং লক্ষণটি ফোকাসে রাখুন। চাইলে যা দেখেছেন তা লিখে বা বলে জানাতে পারেন।",
    statuses: {
      healthy: ["সমস্যা ধরা পড়েনি", "গাছটি সুস্থ মনে হচ্ছে", "এই ছবিতে জেমিনি স্পষ্ট কোনো স্বাস্থ্য সমস্যা খুঁজে পায়নি।"],
      possible_issue: ["সম্ভাব্য সমস্যা পাওয়া গেছে", "সম্ভাব্য কারণগুলো দেখুন", "ছবির লক্ষণ একাধিক সমস্যার সঙ্গে মিলতে পারে, তাই কয়েকটি সম্ভাবনা তুলনা করুন।"],
      not_a_plant: ["গাছ শনাক্ত হয়নি", "আরেকটি ছবি তুলুন", "একটি আক্রান্ত পাতা, কাণ্ড, ফল বা দৃশ্যমান পোকা দিয়ে ফ্রেমটি পূর্ণ করুন।"],
      inconclusive: ["যথেষ্ট তথ্য নেই", "ফলাফল অনিশ্চিত", "দিনের আলোতে আক্রান্ত অংশ ফোকাসে রেখে আবার ছবি তুলুন।"],
    },
  },
} as const;

const allowedTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
const maxBytes = 8 * 1024 * 1024;

const percent = (value: unknown) => {
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.round(number * 100)}%` : "—";
};

const errorMessage = (body: RecordValue, status: number, fallback: string) =>
  typeof body.detail === "string" && body.detail.trim()
    ? body.detail
    : `${fallback} (${status})`;

export default function PlantHealthPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<RecognitionLike | null>(null);
  const [language, setLanguage] = useState<Language>("en");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [symptomNotes, setSymptomNotes] = useState("");
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [speechInputSupported, setSpeechInputSupported] = useState(false);
  const [speechOutputSupported, setSpeechOutputSupported] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const t = COPY[language];

  useEffect(() => {
    const voiceWindow = window as typeof window & {
      SpeechRecognition?: RecognitionConstructor;
      webkitSpeechRecognition?: RecognitionConstructor;
    };
    setSpeechInputSupported(Boolean(voiceWindow.SpeechRecognition || voiceWindow.webkitSpeechRecognition));
    setSpeechOutputSupported("speechSynthesis" in window);
    return () => {
      recognitionRef.current?.stop();
      window.speechSynthesis?.cancel();
    };
  }, []);

  useEffect(() => {
    if (!file) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function stopVoice() {
    window.speechSynthesis?.cancel();
    setSpeaking(false);
  }

  function speak(text: string) {
    if (!speechOutputSupported) {
      setError(t.unsupportedSpeech);
      return;
    }
    if (speaking) {
      stopVoice();
      return;
    }
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = language === "bn" ? "bn-BD" : "en-US";
    utterance.rate = language === "bn" ? 0.88 : 0.94;
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    setSpeaking(true);
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  }

  function changeLanguage(next: Language) {
    if (next === language) return;
    recognitionRef.current?.stop();
    stopVoice();
    setListening(false);
    setLanguage(next);
    setDiagnosis(null);
    setError(null);
  }

  function startDictation() {
    if (listening) {
      recognitionRef.current?.stop();
      return;
    }
    const voiceWindow = window as typeof window & {
      SpeechRecognition?: RecognitionConstructor;
      webkitSpeechRecognition?: RecognitionConstructor;
    };
    const Recognition = voiceWindow.SpeechRecognition || voiceWindow.webkitSpeechRecognition;
    if (!Recognition) {
      setError(t.unsupportedSpeech);
      return;
    }
    const recognition = new Recognition();
    recognition.lang = language === "bn" ? "bn-BD" : "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      const transcript = event.results[0]?.[0]?.transcript?.trim();
      if (transcript) {
        setSymptomNotes((current) => `${current}${current ? " " : ""}${transcript}`.slice(0, 1000));
      }
    };
    recognition.onerror = () => {
      setError(t.speechError);
      setListening(false);
    };
    recognition.onend = () => setListening(false);
    recognitionRef.current = recognition;
    setError(null);
    setListening(true);
    try {
      recognition.start();
    } catch {
      setListening(false);
      setError(t.speechError);
    }
  }

  function chooseImage(next: File | null) {
    setDiagnosis(null);
    setError(null);
    if (!next) {
      setFile(null);
      return;
    }
    if (!allowedTypes.has(next.type)) {
      setFile(null);
      setError(t.invalidType);
      return;
    }
    if (next.size > maxBytes) {
      setFile(null);
      setError(t.tooLarge);
      return;
    }
    setFile(next);
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    chooseImage(event.target.files?.[0] ?? null);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    chooseImage(event.dataTransfer.files?.[0] ?? null);
  }

  async function diagnose() {
    if (!file) return;
    stopVoice();
    setLoading(true);
    setError(null);
    setDiagnosis(null);
    try {
      const form = new FormData();
      form.append("image", file);
      form.append("language", language);
      form.append("symptom_notes", symptomNotes.trim());
      const response = await fetch("/api/plant-health/diagnose", {
        method: "POST",
        body: form,
      });
      const body = (await response.json().catch(() => ({}))) as RecordValue;
      if (!response.ok) throw new Error(errorMessage(body, response.status, t.failed));
      setDiagnosis(body as unknown as Diagnosis);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t.failed);
    } finally {
      setLoading(false);
    }
  }

  const statusText = diagnosis ? t.statuses[diagnosis.status] : null;

  function readDiagnosis() {
    if (!diagnosis || !statusText) return;
    const details = diagnosis.suggestions.flatMap((item, index) => [
      `${index + 1}. ${item.name}. ${percent(item.confidence)}.`,
      item.description || "",
      item.prevention ? `${t.prevention}: ${item.prevention}` : "",
      item.field_check ? `${t.checkNext}: ${item.field_check}` : "",
    ]);
    speak([
      statusText[1],
      statusText[2],
      ...details,
      diagnosis.follow_up_question || "",
      diagnosis.safety,
    ].filter(Boolean).join(" "));
  }

  return (
    <main className={styles.page} lang={language === "bn" ? "bn-BD" : "en"}>
      <header className={styles.topbar}>
        <a className={styles.brand} href="/">
          <span>AS</span>
          <div><strong>AgriSense</strong><small>{t.brandSub}</small></div>
        </a>
        <div className={styles.topbarActions}>
          <div className={styles.languageSwitch} aria-label="Language">
            <button type="button" className={language === "en" ? styles.activeLanguage : ""} onClick={() => changeLanguage("en")}>English</button>
            <button type="button" className={language === "bn" ? styles.activeLanguage : ""} onClick={() => changeLanguage("bn")}>বাংলা</button>
          </div>
          <a className={styles.back} href="/">{t.back}</a>
        </div>
      </header>

      <section className={styles.hero}>
        <div>
          <span className={styles.eyebrow}>{t.eyebrow}</span>
          <h1>{t.heroTitle}</h1>
          <p>{t.heroBody}</p>
        </div>
        <div className={styles.heroActions}>
          <div className={styles.providerBadge}><i /> {t.provider}</div>
          <button type="button" className={styles.voiceButton} onClick={() => speak(t.introSpeech)} disabled={!speechOutputSupported}>
            {speaking ? "■ " : "▶ "}{speaking ? t.stopVoice : t.listenIntro}
          </button>
        </div>
      </section>

      <section className={styles.workspace}>
        <div className={styles.uploadPanel}>
          <div
            className={`${styles.dropzone} ${dragging ? styles.dragging : ""} ${preview ? styles.hasImage : ""}`}
            onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            {preview ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={preview} alt={t.addTitle} />
            ) : (
              <div className={styles.emptyUpload}>
                <span>⌁</span>
                <h2>{t.addTitle}</h2>
                <p>{t.addBody}</p>
              </div>
            )}
            <input ref={inputRef} className={styles.fileInput} type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={onFileChange} />
            <button type="button" className={styles.chooseButton} onClick={() => inputRef.current?.click()}>
              {preview ? t.chooseAnother : t.choose}
            </button>
          </div>

          <div className={styles.photoTips}>
            <div><b>01</b><span><strong>{t.tipClose}</strong><small>{t.tipCloseBody}</small></span></div>
            <div><b>02</b><span><strong>{t.tipLight}</strong><small>{t.tipLightBody}</small></span></div>
            <div><b>03</b><span><strong>{t.tipSharp}</strong><small>{t.tipSharpBody}</small></span></div>
          </div>

          <div className={styles.notesBlock}>
            <label htmlFor="symptom-notes">{t.notesLabel}</label>
            <div>
              <textarea id="symptom-notes" maxLength={1000} rows={3} value={symptomNotes} placeholder={t.notesPlaceholder} onChange={(event) => setSymptomNotes(event.target.value)} />
              <button type="button" className={listening ? styles.listeningButton : ""} onClick={startDictation} disabled={!speechInputSupported} title={speechInputSupported ? t.dictate : t.unsupportedSpeech}>
                {listening ? "■" : "●"} {listening ? t.dictating : t.dictate}
              </button>
            </div>
          </div>

          <button type="button" className={styles.diagnoseButton} disabled={!file || loading} onClick={() => void diagnose()}>
            {loading ? t.analyzing : t.analyze}
          </button>
          <small className={styles.privacy}>{t.privacy}</small>
          {error ? <div className={styles.error}>{error}</div> : null}
        </div>

        <div className={styles.resultPanel}>
          {!diagnosis || !statusText ? (
            <div className={styles.emptyResult}>
              <span>{t.report}</span>
              <h2>{t.emptyTitle}</h2>
              <p>{t.emptyBody}</p>
            </div>
          ) : (
            <>
              <div className={styles.resultTools}>
                <button type="button" className={styles.voiceButton} onClick={readDiagnosis} disabled={!speechOutputSupported}>
                  {speaking ? "■ " : "▶ "}{speaking ? t.stopVoice : t.listenResult}
                </button>
              </div>
              <div className={`${styles.resultHeader} ${styles[diagnosis.status]}`}>
                <span>{statusText[0]}</span>
                <h2>{statusText[1]}</h2>
                <p>{statusText[2]}</p>
                <div className={styles.healthSignals}>
                  <div><small>{t.plantEstimate}</small><strong>{percent(diagnosis.plant_detected.confidence)}</strong></div>
                  <div><small>{t.healthyEstimate}</small><strong>{percent(diagnosis.healthy.confidence)}</strong></div>
                </div>
                {diagnosis.confidence_note ? <small className={styles.confidenceNote}>{diagnosis.confidence_note}</small> : null}
              </div>

              {diagnosis.suggestions.length ? (
                <div className={styles.suggestions}>
                  <div className={styles.sectionTitle}><strong>{t.likely}</strong><span>{t.top} {diagnosis.suggestions.length}</span></div>
                  {diagnosis.suggestions.map((item, index) => (
                    <article className={styles.suggestion} key={item.id}>
                      <div className={styles.suggestionHead}>
                        <b>{String(index + 1).padStart(2, "0")}</b>
                        <div><h3>{item.name}</h3><small>{item.scientific_or_provider_name}</small></div>
                        <strong>{percent(item.confidence)}</strong>
                      </div>
                      <div className={styles.confidenceTrack}><i style={{ width: `${Math.max(0, Math.min(100, item.confidence * 100))}%` }} /></div>
                      {item.description ? <p>{item.description}</p> : null}
                      {item.prevention ? <div className={styles.action}><span>{t.prevention}</span><p>{item.prevention}</p></div> : null}
                      {item.field_check ? <div className={styles.action}><span>{t.checkNext}</span><p>{item.field_check}</p></div> : null}
                    </article>
                  ))}
                </div>
              ) : null}

              {diagnosis.follow_up_question ? <div className={styles.followUp}><span>{t.fieldCheck}</span><strong>{diagnosis.follow_up_question}</strong></div> : null}
              <div className={styles.safety}><strong>{t.screening}</strong><p>{diagnosis.safety}</p></div>
            </>
          )}
        </div>
      </section>
    </main>
  );
}
