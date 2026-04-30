(function () {
  function createProgressActivityProjector(deps = {}) {
    const localeText = deps.localeText || ((zh, en) => en || zh || "");
    const truncateText = deps.truncateText || ((value, maxLength = 140) => {
      const text = String(value || "").trim();
      return text.length > maxLength ? `${text.slice(0, maxLength - 1).trimEnd()}…` : text;
    });
    const stripMarkdown = deps.stripMarkdown || ((value) => String(value || ""));
    const activityHintKey = deps.activityHintKey || (() => "custom");

    const COMMAND_HINTS = [
      {
        pattern: /(^|\s)(npm|pnpm|yarn|bun)\s+(install|add)\b|\bpip\s+install\b|\buv\s+(sync|pip install)\b/,
        title: ["正在安装依赖", "Installing dependencies"],
        detail: [
          "首次拉依赖、编译原生模块，或者顺手下载浏览器时都会比较慢；先别急，等下一条安装日志冒出来。",
          "First-time installs, native module builds, or bundled browser downloads can take a while. Give it a moment for the next install log to appear.",
        ],
      },
      {
        pattern: /\b(playwright|chromium|webkit|firefox)\s+install\b/,
        title: ["正在准备浏览器环境", "Preparing browser binaries"],
        detail: [
          "这一步通常在下载浏览器二进制，网络和磁盘速度都会影响时长；装好后测试才会继续往下跑。",
          "This usually downloads browser binaries, so both network and disk speed affect the duration. Testing will continue once the browsers are ready.",
        ],
      },
      {
        pattern: /\b(pytest|playwright test|npx playwright test|vitest|jest|mocha|cypress|npm test|pnpm test|yarn test|bun test)\b/,
        title: ["正在跑测试", "Running tests"],
        detail: [
          "测试阶段可能会先等待浏览器启动、端口就绪或快照生成；下一条通过或失败信号一出来，这里就会更新。",
          "The test step may wait for browsers to boot, ports to open, or snapshots to generate. This card updates as soon as the next pass or fail signal appears.",
        ],
      },
      {
        pattern: /\b(npm run build|pnpm build|yarn build|bun run build|vite build|next build|cargo build|go build)\b/,
        title: ["正在构建项目", "Building the project"],
        detail: [
          "构建常常会先安静一阵子，等 bundler 或编译器把结果整合好才一起吐出来。",
          "Builds often stay quiet for a bit before the bundler or compiler flushes the next batch of output.",
        ],
      },
      {
        pattern: /\b(npm run dev|pnpm dev|yarn dev|bun run dev|vite|next dev|uvicorn|flask run|python -m http\.server|serve\b)\b/,
        title: ["正在启动本地服务", "Starting a local server"],
        detail: [
          "服务通常会先抢端口、热身依赖，再打印访问地址；看到 ready、listening 或 localhost 之前都算正常。",
          "Servers often need to claim a port and warm dependencies before printing the access URL. It is normal to wait until you see ready, listening, or localhost.",
        ],
      },
      {
        pattern: /\b(git clone|git fetch|git submodule)\b/,
        title: ["正在拉取代码", "Fetching code"],
        detail: [
          "这一步可能在同步远端仓库或子模块，网络稍慢时会安静一会儿。",
          "This may be syncing a remote repo or submodules, so a quiet pause is normal when the network is slow.",
        ],
      },
      {
        pattern: /\b(rg|ripgrep|find|fd)\b/,
        title: ["正在扫描工作区", "Scanning the workspace"],
        detail: [
          "它在搜文件或全文检索，项目越大越容易先安静一下；搜到结果会马上在控制台里冒出来。",
          "It is searching files or text across the workspace. Bigger projects can be quiet for a moment before results start appearing.",
        ],
      },
    ];

    function localizedPair(pair) {
      return localeText(pair[0], pair[1]);
    }

    function fallbackActivitySummary(stage, run) {
      const hints = {
        checks: {
          title: localeText("正在整理检查项", "Shaping the check list"),
          detail: localeText(
            "它正在把 Task、Guardrails 和当前工作区收拢成一组可判定的检查项；清单冻结后，这里会立刻换成更具体的细节。",
            "It is turning the Task, Guardrails, and current workspace into a set of checkable checks. As soon as that list freezes, this card will switch to something more concrete."
          ),
        },
        builder: {
          title: localeText("正在筹划这轮改动", "Planning this round of changes"),
          detail: localeText(
            "它多半在读代码、决定要改哪些文件；一旦开始落盘或跑命令，这里就会马上显示具体动作。",
            "It is likely reading code and deciding which files to touch. As soon as it writes files or runs commands, the concrete action will appear here."
          ),
        },
        inspector: {
          title: localeText("正在收集测试证据", "Collecting test evidence"),
          detail: localeText(
            "它可能在跑命令、看页面，或者对照源码核对行为；第一条命令、输出或结论一出现，这里就会跟着刷新。",
            "It may be running commands, checking the page, or comparing behavior against the source. The first command, output, or conclusion will show up here as soon as it lands."
          ),
        },
        gatekeeper: {
          title: localeText("正在整理验证结论", "Preparing the verification verdict"),
          detail: localeText(
            "它在消化检查项和测试证据，准备判断这一轮到底算不算通过。",
            "It is digesting the checks and test evidence to decide whether this round really passes."
          ),
        },
        guide: {
          title: localeText("正在寻找新方向", "Looking for a new direction"),
          detail: localeText(
            "它在分析为什么会停住，并尝试提出更清楚的推进方向。",
            "It is analyzing why progress stalled and trying to suggest a clearer direction."
          ),
        },
        custom: {
          title: localeText("正在推进当前步骤", "Advancing the current step"),
          detail: localeText(
            "这个步骤已经开始了，只是还没吐出足够具体的新信号。",
            "This step has started, but it has not emitted a concrete enough signal yet."
          ),
        },
        finished: {
          title: localeText("这一轮已经结束", "This run has finished"),
          detail: localeText(
            "这张卡现在只保留最后的关键信号，下面的时间线会给你完整经过。",
            "This card now keeps only the final signal; the timeline below shows the full path."
          ),
        },
      };
      return hints[activityHintKey(stage, run)] || {
        title: localeText("正在继续推进", "Still moving forward"),
        detail: localeText(
          "当前阶段已经开始，只是还没吐出足够具体的新信号。",
          "This stage has started, but it has not emitted a concrete enough signal yet."
        ),
      };
    }

    function commandProgressHint(command, stage, run) {
      const text = String(command || "").trim();
      const normalized = text.toLowerCase();
      const generic = {
        title: localeText("正在执行命令", "Running a command"),
        detail: localeText(
          "这条命令还在跑，控制台一冒出新行就会立刻显示在下面；长一点的静默通常只是它还没来得及吐日志。",
          "This command is still running. As soon as a new line appears, it will show up below. A quiet stretch often just means it has not emitted logs yet."
        ),
      };
      if (!text) {
        return generic;
      }
      const matched = COMMAND_HINTS.find((hint) => hint.pattern.test(normalized));
      if (matched) {
        return {
          title: localizedPair(matched.title),
          detail: localizedPair(matched.detail),
        };
      }
      const stageSpecific = {
        builder: localeText("它现在多半在落地改动，命令跑完后会继续写文件或整理推进方向。", "It is likely applying changes right now; once the command ends, it will continue writing files or planning the direction."),
        inspector: localeText("它现在在收集测试证据，命令跑完后通常会给出通过、失败或新的验证动作。", "It is gathering test evidence right now; once the command ends, it will usually produce a pass/fail signal or another verification action."),
        gatekeeper: localeText("它现在在补验证证据，这条命令结束后会更接近最终结论。", "It is filling in verification evidence; once this command ends, it will be closer to the final verdict."),
        checks: localeText("它在补足检查项上下文，命令跑完后会更快冻结本轮检查集。", "It is collecting context for the checks; once the command ends, it can freeze this run's check set."),
        guide: localeText("它在寻找突破口，命令跑完后会更容易给出新方向。", "It is probing for a better opening; once the command ends, it can suggest a clearer direction."),
        custom: localeText("它正在执行这个自定义步骤，命令结束后会更接近新的交接结果。", "It is executing this custom step right now; once the command ends, it will be closer to a fresh handoff."),
      };
      return {
        title: generic.title,
        detail: stageSpecific[activityHintKey(stage, run)] || generic.detail,
      };
    }

    function extractActivitySummary(event, stage, run) {
      if (!event) {
        return fallbackActivitySummary(stage, run);
      }
      const payload = event.payload || {};
      const item = payload.item || {};
      if (event.event_type === "codex_event") {
        if (payload.type === "command" && payload.message) {
          const hint = commandProgressHint(payload.message, stage, run);
          return {
            title: hint.title,
            detail: truncateText(`${String(payload.message).trim()} · ${hint.detail}`, 180),
          };
        }
        if (payload.type === "stdout" && payload.message) {
          const firstLine = String(payload.message).split("\n").find((line) => line.trim());
          if (firstLine) {
            return {
              title: localeText("刚刚有新输出", "Fresh output just arrived"),
              detail: truncateText(firstLine.trim(), 140),
            };
          }
        }
        if ((payload.type === "item.started" || payload.type === "item.updated") && item.type === "todo_list") {
          const total = (item.items || []).length;
          const completed = (item.items || []).filter((entry) => entry.completed).length;
          return {
            title: localeText("正在推进待办", "Working through the todo list"),
            detail: localeText(`当前完成 ${completed}/${total} 项。`, `Currently ${completed}/${total} tasks complete.`),
          };
        }
        if (payload.type === "item.completed" && item.type === "file_change") {
          const changed = (item.changes || []).map((change) => change.path?.split("/").pop()).filter(Boolean).join("、");
          return {
            title: localeText("刚刚写入了文件", "Files were just updated"),
            detail: changed ? truncateText(changed, 140) : localeText("已经有文件变更落地。", "The latest step wrote file changes."),
          };
        }
        if (payload.type === "item.completed" && item.type === "agent_message" && item.text) {
          return {
            title: localeText("模型刚给出一段结论", "The model just produced a conclusion"),
            detail: truncateText(stripMarkdown(item.text), 140),
          };
        }
        if (payload.type === "error") {
          return {
            title: localeText("当前阶段遇到了错误", "This stage hit an error"),
            detail: truncateText(String(payload.message || payload.error?.message || localeText("发生错误", "Error")).trim(), 140),
          };
        }
      }
      if (event.event_type === "role_execution_summary") {
        return {
          title: payload.ok ? localeText("这个阶段刚刚完成", "This stage just completed") : localeText("这个阶段刚刚失败", "This stage just failed"),
          detail: truncateText(String(payload.error || localeText("执行摘要已写入时间线。", "Execution summary was written to the timeline.")).trim(), 140),
        };
      }
      return fallbackActivitySummary(stage, run);
    }

    return {
      commandProgressHint,
      extractActivitySummary,
      fallbackActivitySummary,
    };
  }

  window.LooporaRunDetailProgressActivity = {createProgressActivityProjector};
})();
