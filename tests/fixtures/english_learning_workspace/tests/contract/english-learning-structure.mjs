import fs from "node:fs";
import path from "node:path";

const [, , proofPathArg] = process.argv;

if (!proofPathArg) {
  throw new Error("usage: node english-learning-structure.mjs <proof-output-path>");
}

const workspaceRoot = process.cwd();
const proofPath = path.resolve(workspaceRoot, proofPathArg);
const indexPath = path.resolve(workspaceRoot, "index.html");
const scriptPath = path.resolve(workspaceRoot, "script.js");

const indexHtml = fs.readFileSync(indexPath, "utf8");
const scriptJs = fs.readFileSync(scriptPath, "utf8");

function localeBlock(startMarker, endMarker) {
  const start = scriptJs.indexOf(startMarker);
  if (start === -1) {
    return "";
  }
  const end = scriptJs.indexOf(endMarker, start);
  return scriptJs.slice(start, end === -1 ? undefined : end);
}

function hasLocaleContract(block) {
  return (
    block.includes("heroTitle:") &&
    block.includes("sections: {") &&
    block.includes("contentKicker:") &&
    block.includes("practiceKicker:") &&
    block.includes("feedbackKicker:") &&
    block.includes("feedback: {") &&
    block.includes("nextLabel:")
  );
}

const englishBlock = localeBlock("  en: {", '  "zh-CN": {');
const chineseBlock = localeBlock('  "zh-CN": {', "const state =");

const checks = {
  englishLocaleContractPresent: hasLocaleContract(englishBlock),
  chineseLocaleContractPresent: hasLocaleContract(chineseBlock),
  switcherTargetsBothLocales:
    /<option value="en">/.test(indexHtml) && /<option value="zh-CN">/.test(indexHtml),
  primaryPathAnchorsStayStable:
    /href="#content"/.test(indexHtml) &&
    /href="#practice"/.test(indexHtml) &&
    /href="#feedback"/.test(indexHtml),
  feedbackPanelStillReferencesNextStep: /id="feedback-next-step"/.test(indexHtml),
  practiceFlowStillSupportsReset: /id="reset-button"/.test(indexHtml) && /resetLabel:/.test(scriptJs),
};

const result = {
  contract: "english-learning-structure",
  generated_at: new Date().toISOString(),
  pass: checks,
  summary: Object.values(checks).every(Boolean)
    ? "Locale switching and the three-stage learning structure remain intact."
    : "Language-switch or three-stage structure contract regressed.",
};

fs.mkdirSync(path.dirname(proofPath), { recursive: true });
fs.writeFileSync(proofPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
