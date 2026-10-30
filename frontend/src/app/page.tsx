"use client";

import { useEffect, useState } from "react";
import { ProjectWorkbench } from "@/components/project-workbench";

type Language = "bn" | "en";

const copy = {
  bn: {
    navProjects: "প্রজেক্ট",
    navFeatures: "সুবিধা",
    navHow: "কীভাবে কাজ করে",
    local: "লোকাল-ফার্স্ট",
    eyebrow: "আইডিয়া থেকে পরিষ্কার প্রজেক্ট কনটেক্সট",
    title: "আপনার আইডিয়াকে coding agent-এর জন্য প্রস্তুত করুন।",
    intro:
      "Context OS গুরুত্বপূর্ণ প্রশ্ন করে, সিদ্ধান্ত ও অনিশ্চয়তা আলাদা রাখে, তারপর আপনার project-এর জন্য যাচাইকৃত documentation ZIP তৈরি করে।",
    primary: "প্রক্রিয়াটি দেখুন",
    secondary: "এখনো MVP চলছে",
    productNote: "প্রথম সংস্করণ documentation তৈরি করে—আপনার application code লেখে বা চালায় না।",
    sectionLabel: "বিশ্বাসযোগ্য কাজের ভিত্তি",
    featureTitle: "অনুমান নয়, স্পষ্ট প্রেক্ষাপট",
    featureIntro: "একটি ভালো coding task শুরু হয় সঠিক context দিয়ে। প্রতিটি ধাপ আপনাকে নিয়ন্ত্রণে রাখে।",
    features: [
      {
        number: "01",
        title: "যা জানা, তা যাচাই",
        text: "Confirmed facts, user decisions, assumptions ও open questions আলাদা করে দেখা যায়।",
      },
      {
        number: "02",
        title: "শুধু দরকারি নথি",
        text: "Project-এর আকার ও প্রয়োজন বুঝে compact বা detailed documentation package তৈরি হয়।",
      },
      {
        number: "03",
        title: "Download-এর আগে পরীক্ষা",
        text: "Schema, links, paths, placeholders ও ZIP manifest যাচাই না হলে export সফল দেখায় না।",
      },
    ],
    howTitle: "আপনার idea, আপনার সিদ্ধান্ত",
    steps: [
      ["01", "আইডিয়া জানান", "আপনার ভাষায় app-এর লক্ষ্য ও প্রয়োজন লিখুন।"],
      ["02", "প্রশ্নের উত্তর দিন", "গুরুত্বপূর্ণ অজানা বিষয় পরিষ্কার করুন; যা জানেন না তা অজানাই থাকুক।"],
      ["03", "Review ও export", "নথি যাচাই করে coding agent-এর জন্য ZIP download করুন।"],
    ],
    safetyTitle: "নিরাপদ ও নিয়ন্ত্রিত",
    safety:
      "Local-first • আপনার অনুমতি ছাড়া AI provider-এ idea পাঠানো হবে না • model-এর তৈরি code বা command চালানো হয় না",
    footer: "আপনার idea-র জন্য Context OS কোনো নির্দিষ্ট industry ধরে নেয় না।",
    language: "English",
    languageLabel: "ভাষা পরিবর্তন করুন",
    status: "Backend integration তৈরি হচ্ছে",
    progress: "এই পর্যায়ে কী আছে",
  },
  en: {
    navProjects: "Projects",
    navFeatures: "Features",
    navHow: "How it works",
    local: "LOCAL-FIRST",
    eyebrow: "FROM IDEA TO CLEAR PROJECT CONTEXT",
    title: "Prepare your idea for a coding agent.",
    intro:
      "Context OS asks the important questions, separates decisions from uncertainty, then creates a validated documentation ZIP for your project.",
    primary: "See how it works",
    secondary: "MVP in progress",
    productNote:
      "The first release creates documentation—it does not write or execute your application code.",
    sectionLabel: "A foundation for trustworthy work",
    featureTitle: "Clear context, not guesses",
    featureIntro:
      "Good coding work starts with the right context. You stay in control at every step.",
    features: [
      {
        number: "01",
        title: "Facts stay traceable",
        text: "Confirmed facts, user decisions, assumptions, and open questions stay distinct.",
      },
      {
        number: "02",
        title: "Only useful documents",
        text: "Choose a compact or detailed documentation package sized to your project.",
      },
      {
        number: "03",
        title: "Validated before download",
        text: "Exports fail closed unless schemas, links, paths, placeholders, and ZIP manifests pass.",
      },
    ],
    howTitle: "Your idea, your decisions",
    steps: [
      ["01", "Describe the idea", "Write the app's goal and needs in your own words."],
      ["02", "Answer questions", "Clarify important unknowns; unknowns remain unknown."],
      ["03", "Review and export", "Check the documents and download a ZIP for your coding agent."],
    ],
    safetyTitle: "Safe and under your control",
    safety:
      "Local-first • Your idea is not sent to an AI provider without consent • Model-generated code or commands are never executed",
    footer: "Context OS does not assume an industry for your idea.",
    language: "বাংলা",
    languageLabel: "Change language",
    status: "Backend integration in progress",
    progress: "What is available now",
  },
} as const;

export default function Home() {
  const [language, setLanguage] = useState<Language>("bn");
  const text = copy[language];

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  return (
    <main>
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Context OS home">
          <span className="brand-mark" aria-hidden="true">
            C
          </span>
          <span>Context OS</span>
        </a>
        <nav className="navigation" aria-label="Main navigation">
          <a href="#projects">{text.navProjects}</a>
          <a href="#features">{text.navFeatures}</a>
          <a href="#workflow">{text.navHow}</a>
        </nav>
        <div className="topbar-actions">
          <span className="local-badge">
            <span className="status-dot" aria-hidden="true" />
            {text.local}
          </span>
          <button
            className="language-toggle"
            type="button"
            aria-label={text.languageLabel}
            aria-pressed={language === "en"}
            onClick={() => setLanguage(language === "bn" ? "en" : "bn")}
          >
            {text.language}
          </button>
        </div>
      </header>

      <section className="hero section-wrap" id="top" aria-labelledby="hero-title">
        <div className="hero-copy">
          <p className="eyebrow">
            <span className="eyebrow-line" aria-hidden="true" />
            {text.eyebrow}
          </p>
          <h1 id="hero-title">{text.title}</h1>
          <p className="hero-intro">{text.intro}</p>
          <div className="hero-actions">
            <a className="button button-primary" href="#workflow">
              {text.primary}
              <span aria-hidden="true">→</span>
            </a>
            <span className="build-status">
              <span className="status-dot" aria-hidden="true" />
              {text.secondary}
            </span>
          </div>
          <p className="product-note">
            <span aria-hidden="true">ⓘ</span>
            {text.productNote}
          </p>
        </div>
        <section className="context-card" aria-label={text.progress}>
          <div className="context-card-head">
            <span className="card-kicker">
              {language === "bn" ? "ডেমো · নমুনা তথ্য" : "DEMO · SAMPLE DATA"}
            </span>
            <span className="live-tag">
              <span className="status-dot" aria-hidden="true" />
              {text.status}
            </span>
          </div>
          <div className="context-lines" aria-hidden="true">
            <div className="context-line context-line-short" />
            <div className="context-line" />
            <div className="context-line context-line-medium" />
          </div>
          <div className="context-divider" />
          <div className="context-facts">
            <div>
              <span className="fact-marker fact-confirmed" aria-hidden="true" />
              <span>{language === "bn" ? "নিশ্চিত তথ্য" : "Confirmed facts"}</span>
              <strong>04</strong>
            </div>
            <div>
              <span className="fact-marker fact-assumption" aria-hidden="true" />
              <span>{language === "bn" ? "অনুমান" : "Assumptions"}</span>
              <strong>02</strong>
            </div>
            <div>
              <span className="fact-marker fact-open" aria-hidden="true" />
              <span>{language === "bn" ? "খোলা প্রশ্ন" : "Open questions"}</span>
              <strong>01</strong>
            </div>
          </div>
          <p className="card-footnote">
            {language === "bn"
              ? "এটি উদাহরণ—আপনার project-এর তথ্য নয়"
              : "Illustration only—not your project data"}
          </p>
        </section>
      </section>

      <ProjectWorkbench language={language} />

      <section className="features section-wrap" id="features" aria-labelledby="features-title">
        <div className="section-heading">
          <div>
            <p className="section-label">{text.sectionLabel}</p>
            <h2 id="features-title">{text.featureTitle}</h2>
          </div>
          <p>{text.featureIntro}</p>
        </div>
        <div className="feature-grid">
          {text.features.map((feature) => (
            <article className="feature-card" key={feature.number}>
              <span className="feature-number">{feature.number}</span>
              <h3>{feature.title}</h3>
              <p>{feature.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="workflow section-wrap" id="workflow" aria-labelledby="workflow-title">
        <div className="workflow-heading">
          <p className="section-label">{text.progress}</p>
          <h2 id="workflow-title">{text.howTitle}</h2>
        </div>
        <ol className="steps">
          {text.steps.map(([number, title, description]) => (
            <li className="step" key={number}>
              <span className="step-number">{number}</span>
              <div>
                <h3>{title}</h3>
                <p>{description}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="safety-banner section-wrap" aria-label={text.safetyTitle}>
        <span className="safety-icon" aria-hidden="true">
          ✓
        </span>
        <div>
          <h2>{text.safetyTitle}</h2>
          <p>{text.safety}</p>
        </div>
      </section>

      <footer className="footer section-wrap">
        <a className="brand footer-brand" href="#top">
          <span className="brand-mark" aria-hidden="true">
            C
          </span>
          <span>Context OS</span>
        </a>
        <p>{text.footer}</p>
        <span>© Context OS</span>
      </footer>
    </main>
  );
}
