const contentItems = [
  {
    id: "phrase",
    badge: { en: "Phrase", "zh-CN": "短句" },
    title: {
      en: "Make plans with confidence",
      "zh-CN": "学会自然地约时间",
    },
    description: {
      en: "Use 'How about...' to suggest a time without sounding too direct.",
      "zh-CN": "用 “How about...” 提出建议，语气更自然。",
    },
    example: {
      en: "How about meeting after class?",
      "zh-CN": "How about meeting after class?",
    },
  },
  {
    id: "vocabulary",
    badge: { en: "Vocabulary", "zh-CN": "词汇" },
    title: {
      en: "Keep the word 'available' handy",
      "zh-CN": "掌握 available 的常见用法",
    },
    description: {
      en: "It helps you talk about time, schedule, and readiness in one word.",
      "zh-CN": "它能同时表达时间安排、是否有空和是否可用。",
    },
    example: {
      en: "I am available after 6 p.m.",
      "zh-CN": "I am available after 6 p.m.",
    },
  },
  {
    id: "dialogue",
    badge: { en: "Dialogue", "zh-CN": "对话" },
    title: {
      en: "Spot the polite reply",
      "zh-CN": "观察礼貌回应怎么说",
    },
    description: {
      en: "Short back-and-forth examples show how native speakers confirm a plan.",
      "zh-CN": "简短来回对话展示确认安排时的自然表达。",
    },
    example: {
      en: "Sure, that works for me.",
      "zh-CN": "Sure, that works for me.",
    },
  },
];

const quizData = {
  question: {
    en: "Which reply best accepts a plan politely?",
    "zh-CN": "哪个回答最适合礼貌地接受安排？",
  },
  label: {
    en: "Quick practice",
    "zh-CN": "立即练习",
  },
  resetLabel: {
    en: "Try another round",
    "zh-CN": "再练一次",
  },
  options: [
    {
      id: "a",
      text: {
        en: "Maybe. I do not know anything.",
        "zh-CN": "Maybe. I do not know anything.",
      },
      correct: false,
    },
    {
      id: "b",
      text: {
        en: "Sure, that works for me.",
        "zh-CN": "Sure, that works for me.",
      },
      correct: true,
    },
    {
      id: "c",
      text: {
        en: "You decide everything for me.",
        "zh-CN": "You decide everything for me.",
      },
      correct: false,
    },
  ],
};

const copy = {
  en: {
    localeLabel: "Interface",
    heroEyebrow: "English practice for real situations",
    heroTitle: "Study, practice, and get feedback in one lightweight flow.",
    heroDescription:
      "This prototype keeps the path simple: scan useful English, answer one quick task, then see what went well and what to do next.",
    pathLinks: {
      content: "1. Study content",
      practice: "2. Start practice",
      feedback: "3. Review feedback",
    },
    stats: {
      contentValue: "3",
      contentLabel: "bite-size lesson cards",
      practiceValue: "1",
      practiceLabel: "instant practice prompt",
      feedbackValue: "Live",
      feedbackLabel: "response after each choice",
    },
    journey: {
      contentTitle: "Read useful English",
      contentCopy: "See a phrase, a word, and a dialogue line before doing anything else.",
      practiceTitle: "Answer instantly",
      practiceCopy: "Tap one option on the same page to complete the mini exercise.",
      feedbackTitle: "Adjust with guidance",
      feedbackCopy: "The result panel explains your latest answer and suggests the next move.",
    },
    sections: {
      contentKicker: "Study content",
      contentTitle: "Start with concrete English you can use today.",
      contentDescription:
        "The lesson cards mix phrase, vocabulary, and dialogue so learners immediately know what they are studying.",
      practiceKicker: "Practice",
      practiceTitle: "Answer one focused question without extra setup.",
      practiceDescription:
        "A single tap starts the exercise. No login, no separate page, no hidden steps.",
      feedbackKicker: "Feedback",
      feedbackTitle: "See a result that explains what happened.",
      feedbackDescription:
        "Feedback connects directly to the practice choice and points to the next move.",
      nextLabel: "Next step",
      quizHelper: "Choose one reply. Feedback updates immediately after your tap.",
    },
    feedback: {
      answerLabel: "Latest answer",
      pickedLabel: "You picked",
      targetLabel: "Best answer",
      idleBadge: "Ready",
      idleScore: "0/1",
      idleAnswer: "No answer yet.",
      idleSummary: "Pick an answer to unlock feedback.",
      idleDetail: "The prototype shows score, correction, and encouragement after one action.",
      idleNext: "Review the lesson cards, then choose the reply that sounds natural and polite.",
      correctBadge: "Correct",
      correctScore: "1/1",
      correctSummary: "Nice choice. That reply sounds warm, clear, and natural.",
      correctDetail:
        "You matched the dialogue card language. Reusing familiar sentence shapes builds speaking confidence.",
      correctNext: "Try saying the sentence aloud, then adapt it with a new time or place.",
      incorrectBadge: "Keep going",
      incorrectScore: "0/1",
      incorrectSummary: "That option does not fit the situation yet.",
      incorrectDetail:
        "A better answer is 'Sure, that works for me.' It accepts the plan and keeps the tone friendly.",
      incorrectNext: "Look back at the dialogue card, then try the practice again.",
    },
  },
  "zh-CN": {
    localeLabel: "界面语言",
    heroEyebrow: "围绕真实场景的英语练习",
    heroTitle: "把学习内容、练习和反馈放进同一条轻量路径里。",
    heroDescription:
      "这个原型只保留最关键的动作：先看有用英语素材，再完成一个小练习，最后立即得到结果与下一步建议。",
    pathLinks: {
      content: "1. 看学习内容",
      practice: "2. 做练习",
      feedback: "3. 看反馈",
    },
    stats: {
      contentValue: "3",
      contentLabel: "张可浏览学习卡片",
      practiceValue: "1",
      practiceLabel: "个立即开始的练习",
      feedbackValue: "即时",
      feedbackLabel: "每次作答后的反馈",
    },
    journey: {
      contentTitle: "先读可直接使用的英语",
      contentCopy: "先看短句、词汇和对话例句，再进入练习。",
      practiceTitle: "立即完成一次作答",
      practiceCopy: "留在同一页点击一个选项，就能完成这个小练习。",
      feedbackTitle: "根据结果继续调整",
      feedbackCopy: "反馈区会解释你刚才的选择，并给出下一步建议。",
    },
    sections: {
      contentKicker: "学习内容",
      contentTitle: "先看到今天就能用上的英语表达。",
      contentDescription:
        "学习区同时提供短句、词汇和对话示例，让用户立刻知道自己在学什么。",
      practiceKicker: "练习",
      practiceTitle: "不经过复杂流程，直接开始一个聚焦练习。",
      practiceDescription:
        "点击选项就是开始，不需要登录、不需要跳页，也没有额外设置。",
      feedbackKicker: "反馈",
      feedbackTitle: "马上看到与你刚才行为相关的结果说明。",
      feedbackDescription:
        "反馈区直接说明答题结果、正确表达以及下一步怎么继续。",
      nextLabel: "下一步",
      quizHelper: "点击一个选项即可作答，反馈会在点击后立即刷新。",
    },
    feedback: {
      answerLabel: "最近一次作答",
      pickedLabel: "你的选择",
      targetLabel: "更佳回答",
      idleBadge: "待开始",
      idleScore: "0/1",
      idleAnswer: "还没有作答。",
      idleSummary: "先选一个答案，反馈会立刻出现。",
      idleDetail: "这个原型会在一次交互后展示分数、纠正提示和鼓励信息。",
      idleNext: "先浏览上方学习卡片，再选择一个听起来更自然礼貌的回应。",
      correctBadge: "答对了",
      correctScore: "1/1",
      correctSummary: "选择不错，这个回答自然、清楚，也更有礼貌。",
      correctDetail:
        "你用到了对话卡片里的表达模式。反复复用熟悉句型，有助于建立开口信心。",
      correctNext: "试着把这句话读出来，再替换成新的时间或地点继续说。",
      incorrectBadge: "继续练习",
      incorrectScore: "0/1",
      incorrectSummary: "这个选项暂时不适合当前场景。",
      incorrectDetail:
        "更合适的回答是 'Sure, that works for me.' 它明确接受安排，而且语气友好。",
      incorrectNext: "回看对话卡片，再重新做一次这个练习。",
    },
  },
};

const state = {
  locale: "en",
  answered: false,
  correct: false,
  selectedOptionId: null,
};

const refs = {
  localeSelect: document.querySelector("#locale-select"),
  localeLabel: document.querySelector("#locale-label"),
  heroEyebrow: document.querySelector("#hero-eyebrow"),
  heroTitle: document.querySelector("#hero-title"),
  heroDescription: document.querySelector("#hero-description"),
  journeyContentTitle: document.querySelector("#journey-content-title"),
  journeyContentCopy: document.querySelector("#journey-content-copy"),
  journeyPracticeTitle: document.querySelector("#journey-practice-title"),
  journeyPracticeCopy: document.querySelector("#journey-practice-copy"),
  journeyFeedbackTitle: document.querySelector("#journey-feedback-title"),
  journeyFeedbackCopy: document.querySelector("#journey-feedback-copy"),
  statContentValue: document.querySelector("#stat-content-value"),
  statContentLabel: document.querySelector("#stat-content-label"),
  statPracticeValue: document.querySelector("#stat-practice-value"),
  statPracticeLabel: document.querySelector("#stat-practice-label"),
  statFeedbackValue: document.querySelector("#stat-feedback-value"),
  statFeedbackLabel: document.querySelector("#stat-feedback-label"),
  contentKicker: document.querySelector("#content-kicker"),
  contentTitle: document.querySelector("#content-title"),
  contentDescription: document.querySelector("#content-description"),
  lessonCards: document.querySelector("#lesson-cards"),
  practiceKicker: document.querySelector("#practice-kicker"),
  practiceTitle: document.querySelector("#practice-title"),
  practiceDescription: document.querySelector("#practice-description"),
  quizLabel: document.querySelector("#quiz-label"),
  quizQuestion: document.querySelector("#quiz-question"),
  quizOptions: document.querySelector("#quiz-options"),
  resetButton: document.querySelector("#reset-button"),
  quizHelper: document.querySelector("#quiz-helper"),
  feedbackKicker: document.querySelector("#feedback-kicker"),
  feedbackTitle: document.querySelector("#feedback-title"),
  feedbackDescription: document.querySelector("#feedback-description"),
  feedbackBadge: document.querySelector("#feedback-badge"),
  feedbackScore: document.querySelector("#feedback-score"),
  feedbackAnswer: document.querySelector("#feedback-answer"),
  feedbackSummary: document.querySelector("#feedback-summary"),
  feedbackDetail: document.querySelector("#feedback-detail"),
  feedbackPickedLabel: document.querySelector("#feedback-picked-label"),
  feedbackPickedValue: document.querySelector("#feedback-picked-value"),
  feedbackTargetLabel: document.querySelector("#feedback-target-label"),
  feedbackTargetValue: document.querySelector("#feedback-target-value"),
  feedbackNextLabel: document.querySelector("#feedback-next-label"),
  feedbackNextStep: document.querySelector("#feedback-next-step"),
  pathLinkContent: document.querySelector("#path-link-content"),
  pathLinkPractice: document.querySelector("#path-link-practice"),
  pathLinkFeedback: document.querySelector("#path-link-feedback"),
};

function getLocalizedValue(valueByLocale) {
  return valueByLocale[state.locale] ?? valueByLocale.en;
}

function getLocaleCopy() {
  return copy[state.locale];
}

function renderLessons() {
  refs.lessonCards.innerHTML = "";

  contentItems.forEach((item) => {
    const card = document.createElement("article");
    card.className = "lesson-card";

    const badge = document.createElement("span");
    badge.className = "lesson-chip";
    badge.textContent = getLocalizedValue(item.badge);

    const title = document.createElement("h3");
    title.textContent = getLocalizedValue(item.title);

    const description = document.createElement("p");
    description.textContent = getLocalizedValue(item.description);

    const example = document.createElement("p");
    example.className = "lesson-example";
    example.textContent = getLocalizedValue(item.example);

    card.append(badge, title, description, example);
    refs.lessonCards.append(card);
  });
}

function selectOption(optionId) {
  const selected = quizData.options.find((option) => option.id === optionId);
  state.answered = true;
  state.correct = Boolean(selected?.correct);
  state.selectedOptionId = optionId;
  renderPractice();
  renderFeedback();
}

function renderPractice() {
  refs.quizLabel.textContent = getLocalizedValue(quizData.label);
  refs.quizQuestion.textContent = getLocalizedValue(quizData.question);
  refs.resetButton.textContent = getLocalizedValue(quizData.resetLabel);
  refs.quizOptions.innerHTML = "";

  quizData.options.forEach((option) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "option-button";
    button.textContent = getLocalizedValue(option.text);

    if (state.answered) {
      if (option.correct) {
        button.classList.add("correct");
      } else if (!state.correct && option.id === state.selectedOptionId) {
        button.classList.add("incorrect");
      }
    }

    button.addEventListener("click", () => selectOption(option.id));
    refs.quizOptions.append(button);
  });
}

function renderFeedback() {
  const localeCopy = getLocaleCopy();
  const selectedOption = quizData.options.find((option) => option.id === state.selectedOptionId);
  const targetOption = quizData.options.find((option) => option.correct);
  const feedbackState = !state.answered
    ? {
        badge: localeCopy.feedback.idleBadge,
        score: localeCopy.feedback.idleScore,
        answer: localeCopy.feedback.idleAnswer,
        summary: localeCopy.feedback.idleSummary,
        detail: localeCopy.feedback.idleDetail,
        next: localeCopy.feedback.idleNext,
        picked: localeCopy.feedback.idleAnswer,
      }
    : state.correct
      ? {
          badge: localeCopy.feedback.correctBadge,
          score: localeCopy.feedback.correctScore,
          answer: selectedOption ? getLocalizedValue(selectedOption.text) : localeCopy.feedback.idleAnswer,
          summary: localeCopy.feedback.correctSummary,
          detail: localeCopy.feedback.correctDetail,
          next: localeCopy.feedback.correctNext,
          picked: selectedOption ? getLocalizedValue(selectedOption.text) : localeCopy.feedback.idleAnswer,
        }
      : {
          badge: localeCopy.feedback.incorrectBadge,
          score: localeCopy.feedback.incorrectScore,
          answer: selectedOption ? getLocalizedValue(selectedOption.text) : localeCopy.feedback.idleAnswer,
          summary: localeCopy.feedback.incorrectSummary,
          detail: localeCopy.feedback.incorrectDetail,
          next: localeCopy.feedback.incorrectNext,
          picked: selectedOption ? getLocalizedValue(selectedOption.text) : localeCopy.feedback.idleAnswer,
        };

  refs.feedbackBadge.textContent = feedbackState.badge;
  refs.feedbackScore.textContent = feedbackState.score;
  refs.feedbackAnswer.textContent = `${localeCopy.feedback.answerLabel}: ${feedbackState.answer}`;
  refs.feedbackSummary.textContent = feedbackState.summary;
  refs.feedbackDetail.textContent = feedbackState.detail;
  refs.feedbackPickedLabel.textContent = localeCopy.feedback.pickedLabel;
  refs.feedbackPickedValue.textContent = feedbackState.picked;
  refs.feedbackTargetLabel.textContent = localeCopy.feedback.targetLabel;
  refs.feedbackTargetValue.textContent = targetOption
    ? getLocalizedValue(targetOption.text)
    : localeCopy.feedback.idleAnswer;
  refs.feedbackNextLabel.textContent = localeCopy.sections.nextLabel;
  refs.feedbackNextStep.textContent = feedbackState.next;
}

function renderShell() {
  const localeCopy = getLocaleCopy();
  document.documentElement.lang = state.locale;
  refs.localeSelect.value = state.locale;
  refs.localeLabel.textContent = localeCopy.localeLabel;
  refs.heroEyebrow.textContent = localeCopy.heroEyebrow;
  refs.heroTitle.textContent = localeCopy.heroTitle;
  refs.heroDescription.textContent = localeCopy.heroDescription;
  refs.pathLinkContent.textContent = localeCopy.pathLinks.content;
  refs.pathLinkPractice.textContent = localeCopy.pathLinks.practice;
  refs.pathLinkFeedback.textContent = localeCopy.pathLinks.feedback;
  refs.journeyContentTitle.textContent = localeCopy.journey.contentTitle;
  refs.journeyContentCopy.textContent = localeCopy.journey.contentCopy;
  refs.journeyPracticeTitle.textContent = localeCopy.journey.practiceTitle;
  refs.journeyPracticeCopy.textContent = localeCopy.journey.practiceCopy;
  refs.journeyFeedbackTitle.textContent = localeCopy.journey.feedbackTitle;
  refs.journeyFeedbackCopy.textContent = localeCopy.journey.feedbackCopy;
  refs.statContentValue.textContent = localeCopy.stats.contentValue;
  refs.statContentLabel.textContent = localeCopy.stats.contentLabel;
  refs.statPracticeValue.textContent = localeCopy.stats.practiceValue;
  refs.statPracticeLabel.textContent = localeCopy.stats.practiceLabel;
  refs.statFeedbackValue.textContent = localeCopy.stats.feedbackValue;
  refs.statFeedbackLabel.textContent = localeCopy.stats.feedbackLabel;
  refs.contentKicker.textContent = localeCopy.sections.contentKicker;
  refs.contentTitle.textContent = localeCopy.sections.contentTitle;
  refs.contentDescription.textContent = localeCopy.sections.contentDescription;
  refs.practiceKicker.textContent = localeCopy.sections.practiceKicker;
  refs.practiceTitle.textContent = localeCopy.sections.practiceTitle;
  refs.practiceDescription.textContent = localeCopy.sections.practiceDescription;
  refs.quizHelper.textContent = localeCopy.sections.quizHelper;
  refs.feedbackKicker.textContent = localeCopy.sections.feedbackKicker;
  refs.feedbackTitle.textContent = localeCopy.sections.feedbackTitle;
  refs.feedbackDescription.textContent = localeCopy.sections.feedbackDescription;
}

function render() {
  renderShell();
  renderLessons();
  renderPractice();
  renderFeedback();
}

refs.localeSelect.addEventListener("change", (event) => {
  state.locale = event.target.value;
  render();
});

refs.resetButton.addEventListener("click", () => {
  state.answered = false;
  state.correct = false;
  state.selectedOptionId = null;
  renderPractice();
  renderFeedback();
});

render();
