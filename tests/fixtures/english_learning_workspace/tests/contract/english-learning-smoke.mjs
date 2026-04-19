import fs from "node:fs";
import path from "node:path";

const [, , proofPathArg] = process.argv;

if (!proofPathArg) {
  throw new Error("usage: node english-learning-smoke.mjs <proof-output-path>");
}

const workspaceRoot = process.cwd();
const proofPath = path.resolve(workspaceRoot, proofPathArg);
const indexPath = path.resolve(workspaceRoot, "index.html");
const scriptPath = path.resolve(workspaceRoot, "script.js");
const stylesPath = path.resolve(workspaceRoot, "styles.css");

const indexHtml = fs.readFileSync(indexPath, "utf8");
const scriptJs = fs.readFileSync(scriptPath, "utf8");
const stylesCss = fs.readFileSync(stylesPath, "utf8");

const checks = {
  hasContentSection: /<section[^>]+id="content"/.test(indexHtml),
  hasPracticeSection: /<section[^>]+id="practice"/.test(indexHtml),
  hasFeedbackSection: /<section[^>]+id="feedback"/.test(indexHtml),
  hasLessonCardsContainer: /id="lesson-cards"/.test(indexHtml),
  hasQuizOptionsContainer: /id="quiz-options"/.test(indexHtml),
  hasFeedbackSummarySurface:
    /id="feedback-score"/.test(indexHtml) &&
    /id="feedback-summary"/.test(indexHtml) &&
    /id="feedback-next-step"/.test(indexHtml),
  hasLanguageSelector:
    /<select[^>]+id="locale-select"/.test(indexHtml) &&
    /value="en"/.test(indexHtml) &&
    /value="zh-CN"/.test(indexHtml),
  shipsCoreAssets:
    /<link[^>]+href="\.\/styles\.css"/.test(indexHtml) &&
    /<script[^>]+src="\.\/script\.js"/.test(indexHtml),
  exposesThreeLearningCards: (scriptJs.match(/badge:\s*\{/g) || []).length >= 3,
  exposesInteractiveQuiz: /const quizData = \{/.test(scriptJs) && /correct:\s*true/.test(scriptJs),
  stylesPanelSurfaces: /\.panel\s*\{/.test(stylesCss) && /\.feedback-card\s*\{/.test(stylesCss),
};

const result = {
  contract: "english-learning-smoke",
  generated_at: new Date().toISOString(),
  pass: checks,
  summary: Object.values(checks).every(Boolean)
    ? "Core content, practice, feedback, and language-switch surfaces are present."
    : "One or more core prototype surfaces are missing from the workspace.",
};

fs.mkdirSync(path.dirname(proofPath), { recursive: true });
fs.writeFileSync(proofPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");

