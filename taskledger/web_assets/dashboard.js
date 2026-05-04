const refreshMs = __REFRESH_MS__;
const defaultTaskRef = __DEFAULT_TASK_REF__;
let selectedTaskRef = defaultTaskRef ?? "active";
let refreshTimer = null;
let refreshInFlight = false;
let pollingPaused = false;
let lastUpdatedText = "never";
let taskSearchQuery = "";
let taskStageFilter = "all";
const openDetailsKeys = new Set();

const STAGE_FILTERS = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "draft", label: "Draft" },
  { value: "review", label: "Review" },
  { value: "approved", label: "Approved" },
  { value: "implementation", label: "Implementing" },
  { value: "validation", label: "Validating" },
  { value: "failed", label: "Failed" },
  { value: "done", label: "Done" },
  { value: "cancelled", label: "Cancelled" },
];

const endpointState = {
  tasks: {
    key: null,
    etag: null,
    payload: null,
    error: null,
    lastRequestedAt: 0,
  },
  project: {
    key: null,
    etag: null,
    payload: null,
    error: null,
    lastRequestedAt: 0,
  },
  dashboard: {
    key: null,
    etag: null,
    payload: null,
    error: null,
    lastRequestedAt: 0,
  },
  events: {
    key: null,
    etag: null,
    payload: null,
    error: null,
    lastRequestedAt: 0,
  },
};

function apiTaskRef() {
  return selectedTaskRef === "active" ? "active" : selectedTaskRef;
}

function endpointPath(name) {
  if (name === "tasks") return "/api/tasks";
  if (name === "project") return "/api/project";
  const taskRef = encodeURIComponent(apiTaskRef());
  if (name === "dashboard") return "/api/dashboard?task=" + taskRef;
  return "/api/events?task=" + taskRef + "&limit=50";
}

function endpointCadence(name) {
  if (name === "tasks") return Math.max(refreshMs * 5, 5000);
  if (name === "project") return Math.max(refreshMs * 15, 15000);
  return refreshMs;
}

async function getJson(name, path) {
  const state = endpointState[name];
  if (state.key !== path) {
    state.key = path;
    state.etag = null;
    state.payload = null;
    state.error = null;
  }
  const headers = {};
  if (state.etag) {
    headers["If-None-Match"] = state.etag;
  }
  const response = await fetch(path, { headers });
  if (response.status === 304 && state.payload) {
    return { payload: state.payload, changed: false };
  }
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload?.error?.message || "HTTP " + response.status);
  }
  const previousPayload = state.payload;
  const previousRevision = previousPayload?.revision;
  state.etag = response.headers.get("ETag");
  state.payload = payload;
  return {
    payload,
    changed: previousPayload === null || payload?.revision !== previousRevision,
  };
}

function h(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = String(value);
    else if (key === "text") node.textContent = String(value);
    else if (key === "style") node.setAttribute("style", String(value));
    else if (key === "htmlFor") node.htmlFor = String(value);
    else if (key === "value") node.value = String(value);
    else if (
      key.startsWith("aria-") ||
      key.startsWith("data-") ||
      key === "role" ||
      key === "type" ||
      key === "placeholder" ||
      key === "id"
    ) {
      node.setAttribute(key, String(value));
    } else {
      node[key] = value;
    }
  }
  const list = (Array.isArray(children) ? children : [children]).flat(Infinity);
  for (const child of list) {
    if (child === null || child === undefined) continue;
    node.append(
      child && child.nodeType ? child : document.createTextNode(String(child))
    );
  }
  return node;
}

function clearNode(node) {
  if (node) node.replaceChildren();
}

function emptyState(text) {
  return h("div", { class: "empty-state", text });
}

function rememberDetailsState(root = document) {
  for (const node of root.querySelectorAll("details[data-detail-key]")) {
    const key = node.getAttribute("data-detail-key");
    if (!key) continue;
    if (node.open) openDetailsKeys.add(key);
    else openDetailsKeys.delete(key);
  }
}

function bindDetailsState(details, key, openByDefault = false) {
  details.setAttribute("data-detail-key", key);
  details.open = openDetailsKeys.has(key) ? true : openByDefault;
  details.addEventListener("toggle", () => {
    if (details.open) openDetailsKeys.add(key);
    else openDetailsKeys.delete(key);
  });
  return details;
}

function replaceContentPreservingDetails(container, children) {
  if (!container) return;
  rememberDetailsState(container);
  container.replaceChildren(...children.filter(Boolean));
}

function titleCase(value) {
  return String(value || "")
    .replace(/[_-]+/g, " ")
    .replace(/\\b\\w/g, (letter) => letter.toUpperCase());
}

function formatTimestamp(value) {
  if (!value) return "Unknown";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString();
}

function toneForStage(task) {
  const stage = task?.status_stage;
  const activeStage = task?.active_stage;
  if (activeStage === "validation" || stage === "plan_review") return "warning";
  if (stage === "failed_validation") return "danger";
  if (stage === "done") return "success";
  if (stage === "cancelled") return "muted";
  if (activeStage || stage === "approved" || stage === "implemented")
    return "info";
  return "muted";
}

function toneForStatus(status) {
  if (
    status === "pass" ||
    status === "done" ||
    status === "finished" ||
    status === "accepted"
  )
    return "success";
  if (
    status === "fail" ||
    status === "failed" ||
    status === "failed_validation"
  )
    return "danger";
  if (status === "warn" || status === "plan_review" || status === "running")
    return "warning";
  if (
    status === "not_run" ||
    status === "open" ||
    status === "draft" ||
    status === "superseded"
  )
    return "muted";
  return "info";
}

function badge(label, tone = "muted") {
  return h("span", { class: "badge badge-" + tone, text: label || "-" });
}

function dashboardTaskKey() {
  return endpointState.dashboard.payload?.task?.id || apiTaskRef();
}

function lazyJsonDetails(summary, getPayload, key) {
  const details = bindDetailsState(h("details"), key);
  const pre = h("pre", {
    class: "debug-json",
    text: "Open to render payload.",
  });
  const renderPayload = () => {
    if (!details.open) return;
    pre.textContent = JSON.stringify(getPayload() ?? {}, null, 2);
    details.dataset.rendered = "true";
  };
  details.append(h("summary", { text: summary }), pre);
  details.addEventListener("toggle", renderPayload);
  queueMicrotask(renderPayload);
  return details;
}

function jsonDetails(summary, payload, key) {
  return lazyJsonDetails(summary, () => payload ?? {}, key || summary);
}

function copyCommand(command) {
  if (!command) return;
  navigator.clipboard?.writeText(command).catch(() => undefined);
}

function commandRow(command) {
  if (!command) return emptyState("No command available.");
  const button = h("button", {
    class: "copy-button",
    type: "button",
    text: "Copy",
  });
  button.addEventListener("click", () => copyCommand(command));
  return h("div", { class: "command-row" }, [
    h("code", { text: command }),
    button,
  ]);
}

function progressBar(done, total) {
  const safeDone = Number(done || 0);
  const safeTotal = Number(total || 0);
  const pct = safeTotal > 0 ? Math.round((safeDone / safeTotal) * 100) : 0;
  const track = h(
    "div",
    {
      class: "progress-track",
      role: "progressbar",
      "aria-valuenow": pct,
      "aria-valuemin": 0,
      "aria-valuemax": 100,
      "aria-label": pct + "% complete",
    },
    [h("div", { class: "progress-fill", style: "width:" + pct + "%" })]
  );
  return h("div", { class: "progress-block" }, [
    h("strong", { text: safeDone + " / " + safeTotal }),
    track,
    h("span", { class: "muted", text: pct + "% complete" }),
  ]);
}

function endpointMessage(name, emptyText) {
  const state = endpointState[name];
  if (state.payload) return null;
  if (state.error) return emptyText + " Error: " + state.error;
  return emptyText;
}

function endpointOrFallback(name, emptyText) {
  return endpointMessage(name, emptyText) || emptyText;
}

function cardSection(title, children, className = "") {
  const section = h("section", { class: ("card " + className).trim() });
  section.append(
    h("div", { class: "card-header" }, [h("h2", { text: title })])
  );
  const list = (Array.isArray(children) ? children : [children]).flat(Infinity);
  for (const child of list) {
    if (child) section.append(child);
  }
  return section;
}

function collapsibleCard(title, children, key, className = "") {
  const section = h("section", {
    class: ("card collapsible-card " + className).trim(),
  });
  const details = bindDetailsState(
    h("details", { class: "section-details" }),
    key
  );
  details.append(h("summary", { text: title }));
  const list = (Array.isArray(children) ? children : [children]).flat(Infinity);
  for (const child of list) {
    if (child) details.append(child);
  }
  section.append(details);
  return section;
}

function renderTaskFilters() {
  const container = document.getElementById("task-filters");
  clearNode(container);
  for (const filter of STAGE_FILTERS) {
    const button = h("button", {
      class: "chip",
      type: "button",
      text: filter.label,
      "data-active": String(taskStageFilter === filter.value),
    });
    button.addEventListener("click", () => {
      taskStageFilter = filter.value;
      renderTasks();
    });
    container.append(button);
  }
}

function taskMatchesFilter(task) {
  if (taskStageFilter === "all") return true;
  if (taskStageFilter === "active") return Boolean(task.active_stage);
  if (taskStageFilter === "review") return task.status_stage === "plan_review";
  if (taskStageFilter === "implementation")
    return (
      task.active_stage === "implementation" ||
      task.status_stage === "implemented"
    );
  if (taskStageFilter === "validation")
    return (
      task.active_stage === "validation" || task.status_stage === "validating"
    );
  if (taskStageFilter === "failed")
    return task.status_stage === "failed_validation";
  return task.status_stage === taskStageFilter;
}

function sortedTasks(tasks) {
  return [...(tasks || [])].sort((left, right) => {
    const leftStamp = left.updated_at || left.created_at || "";
    const rightStamp = right.updated_at || right.created_at || "";
    if (leftStamp || rightStamp) {
      return String(rightStamp).localeCompare(String(leftStamp));
    }
    return String(right.id || "").localeCompare(String(left.id || ""));
  });
}

function renderTaskCard(task, currentTaskId) {
  const selected = Boolean(
    task.id === selectedTaskRef ||
      task.slug === selectedTaskRef ||
      task.id === currentTaskId
  );
  const button = h("button", {
    class: "task-card",
    type: "button",
    "data-active": String(selected),
  });
  button.setAttribute("aria-current", selected ? "true" : "false");
  button.addEventListener("click", () => {
    selectedTaskRef = task.id;
    refreshSelection().catch(renderError);
  });
  const idLabel = [task.id, task.slug].filter(Boolean).join(" · ");
  const planLabel = task.accepted_plan_version
    ? "plan v" + task.accepted_plan_version + " accepted"
    : task.latest_plan_version
    ? "plan v" + task.latest_plan_version + " proposed"
    : "no plan";
  const activeLabel = task.active_stage
    ? "active: " + task.active_stage
    : "active: none";
  button.append(
    h("div", { class: "badge-row" }, [
      badge(
        task.active_stage
          ? titleCase(task.active_stage)
          : titleCase(task.status_stage || "draft"),
        toneForStage(task)
      ),
      task.priority ? badge("priority " + task.priority, "info") : null,
    ]),
    h("p", { class: "task-title", text: task.title || task.slug || task.id }),
    h("div", { class: "meta-line mono", text: idLabel || "-" }),
    h("div", { class: "meta-line", text: activeLabel }),
    h("div", { class: "meta-line", text: planLabel }),
    task.description_summary
      ? h("div", { class: "summary-line", text: task.description_summary })
      : null
  );
  return button;
}

function renderTasks() {
  renderTaskFilters();
  const tasksNode = document.getElementById("tasks");
  clearNode(tasksNode);
  const tasksPayload = endpointState.tasks.payload;
  if (!tasksPayload) {
    tasksNode.append(
      emptyState(endpointOrFallback("tasks", "Loading tasks..."))
    );
    return;
  }
  const currentTaskId = endpointState.dashboard.payload?.task?.id || null;
  const query = taskSearchQuery.trim().toLowerCase();
  const tasks = sortedTasks(tasksPayload.tasks).filter((task) => {
    const haystack = [task.title, task.slug, task.id].join(" ").toLowerCase();
    return (!query || haystack.includes(query)) && taskMatchesFilter(task);
  });
  if (tasks.length === 0) {
    tasksNode.append(
      emptyState("No tasks match the current search or filter.")
    );
    return;
  }
  for (const task of tasks) {
    tasksNode.append(renderTaskCard(task, currentTaskId));
  }
}

function renderHero(project, dashboard) {
  if (!dashboard) {
    return emptyState(
      endpointOrFallback("dashboard", "Loading dashboard summary...")
    );
  }
  const task = dashboard.task || {};
  const lock = dashboard.lock;
  const activeTask = project?.active_task || {};
  const hero = h("section", { class: "card hero-card active-task-hero" });
  hero.append(
    h("div", { class: "hero-title" }, [
      h("h2", { text: task.title || task.slug || task.id || "Active task" }),
      badge(task.status_stage || "unknown", toneForStage(task)),
      task.active_stage
        ? badge("active " + task.active_stage, "info")
        : badge("no active lock", "muted"),
    ]),
    h("p", {
      class: "section-subtitle",
      text:
        task.description_summary ||
        "Human-focused read-only review of the selected task.",
    }),
    h("div", { class: "hero-meta" }, [
      h("div", { class: "meta-row" }, [
        h("span", { class: "muted", text: "Task reference" }),
        h("strong", {
          class: "mono",
          text: [task.id, task.slug].filter(Boolean).join(" · ") || "-",
        }),
      ]),
      h("div", { class: "meta-row" }, [
        h("span", { class: "muted", text: "Lock state" }),
        h("strong", {
          text: lock ? lock.stage + " · " + lock.run_id : "No active lock",
        }),
      ]),
      h("div", { class: "meta-row" }, [
        h("span", { class: "muted", text: "Plan status" }),
        h("strong", {
          text: dashboard.plan
            ? "v" + dashboard.plan.version + " · " + dashboard.plan.status
            : "No plan proposed",
        }),
      ]),
      h("div", { class: "meta-row" }, [
        h("span", { class: "muted", text: "Project focus" }),
        h("strong", {
          text: activeTask.task_id
            ? (activeTask.slug || activeTask.task_id) +
              " · " +
              (project?.health || "not_checked")
            : project?.health || "not_checked",
        }),
      ]),
    ]),
    h("div", { class: "pill-row" }, [
      task.owner ? badge("owner " + task.owner, "info") : null,
      ...(task.labels || []).map((label) => badge(label, "muted")),
      task.created_at
        ? badge("created " + formatTimestamp(task.created_at), "muted")
        : null,
      task.updated_at
        ? badge("updated " + formatTimestamp(task.updated_at), "muted")
        : null,
    ])
  );
  return hero;
}

function renderMetrics(dashboard, events) {
  if (!dashboard) {
    return [
      emptyState(
        endpointOrFallback("dashboard", "Loading progress overview...")
      ),
    ];
  }
  const validationCriteria = dashboard.validation?.criteria || [];
  const passedValidation = validationCriteria.filter(
    (item) => item.satisfied
  ).length;
  const cards = [
    {
      title: "Todos",
      detail:
        (dashboard.todos?.done || 0) +
        " complete of " +
        (dashboard.todos?.total || 0),
      body: progressBar(
        dashboard.todos?.done || 0,
        dashboard.todos?.total || 0
      ),
    },
    {
      title: "Questions",
      detail:
        (dashboard.questions?.open || 0) +
        " open of " +
        (dashboard.questions?.total || 0),
      body: progressBar(
        (dashboard.questions?.total || 0) - (dashboard.questions?.open || 0),
        dashboard.questions?.total || 0
      ),
    },
    {
      title: "Validation",
      detail: passedValidation + " satisfied of " + validationCriteria.length,
      body: progressBar(passedValidation, validationCriteria.length),
    },
    {
      title: "Recent activity",
      detail: (events?.items || []).length + " recent entries",
      body: h("div", { class: "metric-value" }, [
        h("strong", {
          class: "metric-number",
          text: String((events?.items || []).length),
        }),
        h("span", { class: "muted", text: "Recent event tail" }),
      ]),
    },
  ];
  return cards.map((metric) =>
    h("section", { class: "card" }, [
      h("div", { class: "card-header" }, [
        h("h2", { text: metric.title }),
        h("span", { class: "muted", text: metric.detail }),
      ]),
      metric.body,
    ])
  );
}

function renderOverview(project, dashboard) {
  if (!project && !dashboard)
    return emptyState(
      endpointOrFallback("project", "Loading workspace summary...")
    );
  return h("div", { class: "list-grid" }, [
    h("div", { class: "item-card" }, [
      h("div", { class: "item-title" }, [h("strong", { text: "Workspace" })]),
      h("div", { class: "mini-meta" }, [
        h("span", { class: "muted", text: "Workspace root" }),
        h("code", { text: project?.workspace_root || "-" }),
        h("span", { class: "muted", text: "Project dir" }),
        h("code", { text: project?.project_dir || "-" }),
      ]),
    ]),
    h("div", { class: "item-card" }, [
      h("div", { class: "item-title" }, [
        h("strong", { text: "Selected task state" }),
      ]),
      h("div", { class: "mini-meta" }, [
        h("span", { class: "muted", text: "Stage" }),
        h("span", { text: dashboard?.task?.status_stage || "-" }),
        h("span", { class: "muted", text: "Active stage" }),
        h("span", { text: dashboard?.task?.active_stage || "none" }),
        h("span", { class: "muted", text: "Health" }),
        h("span", { text: project?.health || "unknown" }),
      ]),
    ]),
  ]);
}

function renderNextAction(dashboard) {
  const nextAction = dashboard?.next_action;
  if (!nextAction)
    return emptyState(
      endpointOrFallback("dashboard", "Loading next action...")
    );
  const task = dashboard?.task || {};
  const blockers = nextAction.blocking || [];
  const nextItem = nextAction.next_item;
  const todoProgress = nextAction.progress?.todos || {};
  const card = h("section", { class: "card next-action-card" });
  card.append(
    h("div", { class: "card-header" }, [
      h("h2", { text: "Do next" }),
      badge(
        nextAction.action || "none",
        toneForStatus(nextAction.action || "none")
      ),
    ]),
    h("p", {
      class: "section-subtitle",
      text: nextAction.reason || "No next action available.",
    })
  );
  card.append(
    h("div", { class: "item-card" }, [
      h("div", { class: "item-title" }, [
        h("strong", { text: task.title || task.slug || "Selected task" }),
        task.id ? h("code", { text: task.id }) : null,
      ]),
      h("div", { class: "mini-meta" }, [
        h("span", { class: "muted", text: "Stage" }),
        h("span", { text: task.status_stage || "-" }),
        h("span", { class: "muted", text: "Active" }),
        h("span", { text: task.active_stage || "none" }),
      ]),
    ])
  );
  if (nextAction.next_command) {
    card.append(
      h("div", { class: "item-card" }, [
        h("div", { class: "item-title" }, [h("strong", { text: "Inspect" })]),
        commandRow(nextAction.next_command),
      ])
    );
  }
  if (nextItem) {
    card.append(
      h("div", { class: "item-card" }, [
        h("div", { class: "item-title" }, [
          h("strong", { text: nextItem.id || "Next item" }),
          nextItem.kind ? badge(nextItem.kind, "info") : null,
        ]),
        nextItem.text ? h("p", { text: nextItem.text }) : null,
        nextItem.validation_hint
          ? h("div", { class: "mini-meta" }, [
              h("span", { class: "muted", text: "Validation" }),
            ])
          : null,
        nextItem.validation_hint ? commandRow(nextItem.validation_hint) : null,
        nextItem.done_command_hint
          ? h("div", { class: "mini-meta" }, [
              h("span", { class: "muted", text: "When done" }),
            ])
          : null,
        nextItem.done_command_hint
          ? commandRow(nextItem.done_command_hint)
          : null,
      ])
    );
  }
  if (Object.keys(todoProgress).length > 0) {
    card.append(
      h("div", { class: "item-card" }, [
        h("div", { class: "item-title" }, [
          h("strong", { text: "Todo progress" }),
        ]),
        h("p", {
          text:
            String(todoProgress.done || 0) +
            "/" +
            String(todoProgress.total || 0) +
            " done",
        }),
      ])
    );
  }
  if (blockers.length > 0) {
    card.append(
      h("div", { class: "list-grid" }, [
        h("h3", { text: "Blockers" }),
        h(
          "ul",
          { class: "clean-list" },
          blockers.map((blocker) =>
            h("li", {
              text: blocker.message || blocker.kind || "Blocking issue",
            })
          )
        ),
      ])
    );
  }
  return card;
}

function renderQuestionsSection(questions) {
  if (!questions)
    return emptyState(endpointOrFallback("dashboard", "Loading questions..."));
  if (!questions.items || questions.items.length === 0)
    return h("p", {
      class: "section-subtitle",
      text: "No planning questions are recorded.",
    });
  return h(
    "div",
    { class: "list-grid" },
    questions.items.map((item) =>
      h("div", { class: "item-card" }, [
        h("div", { class: "item-title" }, [
          h("strong", { text: item.question || item.text || item.id }),
          badge(item.status || "open", toneForStatus(item.status || "open")),
        ]),
        h("code", { text: item.id || "-" }),
        item.answer ? h("p", { text: item.answer }) : null,
      ])
    )
  );
}

function renderPlanSection(plans) {
  if (!plans || plans.length === 0)
    return emptyState("No plans have been proposed yet.");
  const taskKey = dashboardTaskKey();
  const latest = plans[plans.length - 1];
  const body = h("div", { class: "list-grid" }, [
    h("p", {
      class: "section-subtitle",
      text:
        "Latest plan v" +
        latest.plan_version +
        " · " +
        (latest.status || "unknown"),
    }),
  ]);
  if (latest.goal) body.append(h("p", { text: latest.goal }));
  if (latest.criteria?.length) {
    body.append(
      h(
        "div",
        { class: "criteria-grid" },
        latest.criteria.map((criterion) =>
          h("div", { class: "item-card" }, [
            h("div", { class: "item-title" }, [
              h("strong", { text: criterion.text || criterion.id }),
              criterion.id ? h("code", { text: criterion.id }) : null,
            ]),
            badge(
              criterion.mandatory === false ? "optional" : "mandatory",
              criterion.mandatory === false ? "muted" : "info"
            ),
          ])
        )
      )
    );
  }
  if (latest.todos?.length) {
    body.append(
      h(
        "div",
        { class: "list-grid" },
        latest.todos.map((todo) =>
          h("div", { class: "item-card" }, [
            h("div", { class: "item-title" }, [
              h("strong", { text: todo.text || todo.id }),
              todo.id ? h("code", { text: todo.id }) : null,
            ]),
            todo.validation_hint ? commandRow(todo.validation_hint) : null,
          ])
        )
      )
    );
  }
  if (latest.test_commands?.length) {
    body.append(
      h("div", { class: "list-grid" }, [
        h("h3", { text: "Test commands" }),
        ...latest.test_commands.map((command) => commandRow(command)),
      ])
    );
  }
  if (latest.expected_outputs?.length) {
    body.append(
      h(
        "ul",
        { class: "clean-list" },
        latest.expected_outputs.map((item) => h("li", { text: item }))
      )
    );
  }
  if (latest.body)
    body.append(
      jsonDetails(
        "Expanded plan body",
        latest.body,
        "plan.body." + taskKey + ".v" + latest.plan_version
      )
    );
  if (plans.length > 1) {
    const details = bindDetailsState(
      h("details"),
      "plan.previous_versions." + taskKey
    );
    details.append(
      h("summary", { text: "Previous versions" }),
      ...plans
        .slice(0, -1)
        .reverse()
        .map((plan) =>
          h("div", { class: "item-card" }, [
            h("div", { class: "item-title" }, [
              h("strong", { text: "v" + plan.plan_version }),
              badge(
                plan.status || "unknown",
                toneForStatus(plan.status || "unknown")
              ),
            ]),
            plan.goal ? h("p", { text: plan.goal }) : null,
            plan.body ? h("pre", { text: plan.body }) : null,
          ])
        )
    );
    body.append(details);
  }
  return body;
}

function renderTodosSection(todos, nextAction) {
  if (!todos)
    return emptyState(endpointOrFallback("dashboard", "Loading todos..."));
  const highlightedTodoId =
    nextAction?.next_item?.kind === "todo" ? nextAction.next_item.id : null;
  const items = [...(todos.items || [])].sort(
    (left, right) => Number(Boolean(left.done)) - Number(Boolean(right.done))
  );
  const taskKey = dashboardTaskKey();
  const todoCards = items.map((todo) => {
    const done = Boolean(todo.done || todo.status === "done");
    const card = h(
      "div",
      {
        class:
          "item-card" + (todo.id === highlightedTodoId ? " todo-next" : ""),
      },
      [
        h("div", { class: "item-title" }, [
          h("strong", { text: todo.text || todo.id }),
          badge(
            done ? "done" : todo.status || "open",
            toneForStatus(done ? "done" : todo.status || "open")
          ),
        ]),
        h("code", { text: todo.id || "-" }),
      ]
    );
    const lines = [];
    if (todo.evidence) lines.push("Evidence: " + todo.evidence);
    if (todo.source) lines.push("Source: " + todo.source);
    if (todo.active_at) lines.push("Active at: " + todo.active_at);
    if (lines.length > 0) {
      const details = bindDetailsState(
        h("details"),
        "todo." + taskKey + "." + (todo.id || todo.text || "todo") + ".details"
      );
      details.append(
        h("summary", { text: "Details" }),
        h(
          "ul",
          { class: "clean-list" },
          lines.map((line) => h("li", { text: line }))
        )
      );
      card.append(details);
    }
    return card;
  });
  return h("div", { class: "list-grid" }, [
    h("p", {
      class: "section-subtitle",
      text: (todos.done || 0) + " done of " + (todos.total || 0) + " total",
    }),
    progressBar(todos.done || 0, todos.total || 0),
    items.length === 0
      ? emptyState("No todos are recorded.")
      : h("div", { class: "list-grid" }, todoCards),
  ]);
}

function renderValidationSection(validation) {
  if (!validation)
    return emptyState(endpointOrFallback("dashboard", "Loading validation..."));
  const taskKey = dashboardTaskKey();
  const parts = [
    h("p", {
      class: "section-subtitle",
      text: validation.run_id
        ? "Validation run " +
          validation.run_id +
          " · " +
          (validation.can_finish_passed ? "ready to finish" : "checks remain")
        : "No validation run recorded",
    }),
  ];
  if ((validation.blockers || []).length > 0) {
    parts.push(
      h("div", { class: "item-card" }, [
        h("div", { class: "item-title" }, [h("strong", { text: "Blockers" })]),
        h(
          "ul",
          { class: "clean-list" },
          validation.blockers.map((blocker) =>
            h("li", {
              text:
                blocker.message ||
                blocker.ref ||
                blocker.kind ||
                "Blocking issue",
            })
          )
        ),
      ])
    );
  }
  parts.push(
    (validation.criteria || []).length === 0
      ? emptyState("No validation criteria were found.")
      : h(
          "div",
          { class: "criteria-grid" },
          validation.criteria.map((criterion) => {
            const card = h("div", { class: "item-card" }, [
              h("div", { class: "item-title" }, [
                h("strong", { text: criterion.text || criterion.id }),
                badge(
                  criterion.latest_status || "not_run",
                  toneForStatus(criterion.latest_status || "not_run")
                ),
              ]),
              h("code", { text: criterion.id || "-" }),
              criterion.has_waiver ? badge("waived", "warning") : null,
              criterion.evidence?.length
                ? h(
                    "ul",
                    { class: "clean-list" },
                    criterion.evidence.map((item) => h("li", { text: item }))
                  )
                : h("p", { class: "muted", text: "No evidence recorded." }),
            ]);
            if (criterion.history?.length || criterion.blockers?.length) {
              const details = bindDetailsState(
                h("details"),
                "validation." +
                  taskKey +
                  "." +
                  (criterion.id || "criterion") +
                  ".history"
              );
              details.append(
                h("summary", { text: "History and blockers" }),
                criterion.history?.length
                  ? h(
                      "ul",
                      { class: "clean-list" },
                      criterion.history.map((item) =>
                        h("li", {
                          text:
                            (item.check_id || "check") +
                            " · " +
                            (item.status || "unknown"),
                        })
                      )
                    )
                  : null,
                criterion.blockers?.length
                  ? h(
                      "ul",
                      { class: "clean-list" },
                      criterion.blockers.map((item) =>
                        h("li", {
                          text: item.message || item.kind || "blocker",
                        })
                      )
                    )
                  : null
              );
              card.append(details);
            }
            return card;
          })
        )
  );
  return h("div", { class: "list-grid" }, parts);
}

function renderRunsSection(runs) {
  if (!runs)
    return emptyState(endpointOrFallback("dashboard", "Loading runs..."));
  if (runs.length === 0)
    return emptyState("No implementation or validation runs are recorded.");
  const taskKey = dashboardTaskKey();
  return h(
    "div",
    { class: "timeline" },
    runs.map((run) => {
      const card = h("div", { class: "timeline-item" }, [
        h("div", { class: "item-title" }, [
          h("strong", {
            text: run.run_id + " · " + titleCase(run.run_type || "run"),
          }),
          badge(
            run.result || run.status || "unknown",
            toneForStatus(run.result || run.status || "unknown")
          ),
        ]),
        h("p", { text: run.summary || "No summary recorded." }),
        h("div", { class: "mini-meta" }, [
          h("span", { class: "muted", text: "Started" }),
          h("span", { text: formatTimestamp(run.started_at) }),
          h("span", { class: "muted", text: "Finished" }),
          h("span", {
            text: run.finished_at
              ? formatTimestamp(run.finished_at)
              : "In progress",
          }),
        ]),
      ]);
      card.append(
        jsonDetails(
          "Run details",
          run,
          "run." + taskKey + "." + (run.run_id || "run") + ".details"
        )
      );
      return card;
    })
  );
}

function renderChangesSection(changes) {
  if (!changes)
    return emptyState(endpointOrFallback("dashboard", "Loading changes..."));
  if (changes.length === 0)
    return emptyState("No implementation changes are recorded.");
  const taskKey = dashboardTaskKey();
  return h(
    "div",
    { class: "change-grid" },
    changes.map((change) => {
      const card = h("div", { class: "item-card" }, [
        h("div", { class: "item-title" }, [
          h("strong", {
            text: change.summary || change.path || change.change_id,
          }),
          badge(change.kind || "change", "info"),
        ]),
        h("code", { text: change.path || change.change_id || "-" }),
      ]);
      card.append(
        jsonDetails(
          "Change metadata",
          change,
          "change." +
            taskKey +
            "." +
            (change.change_id || change.path || "change") +
            ".metadata"
        )
      );
      return card;
    })
  );
}

function renderEventsSection(events) {
  if (!events)
    return emptyState(endpointOrFallback("events", "Loading events..."));
  if (!events.items || events.items.length === 0)
    return emptyState("No recent events are available.");
  const taskKey = dashboardTaskKey();
  return h(
    "div",
    { class: "timeline" },
    events.items.map((event, index) => {
      const actor =
        event.actor?.actor_name || event.actor?.actor_type || "unknown";
      const card = h("div", { class: "timeline-item" }, [
        h("div", { class: "item-title" }, [
          h("strong", { text: event.event || "event" }),
          h("span", { class: "muted mono", text: formatTimestamp(event.ts) }),
        ]),
        h("p", { text: actor }),
      ]);
      card.append(
        jsonDetails(
          "Event payload",
          event,
          "event." +
            taskKey +
            "." +
            (event.event_id || event.ts || String(index)) +
            ".payload"
        )
      );
      return card;
    })
  );
}

function renderRecentEventsCard(events) {
  return cardSection("Recent events", [
    h("p", {
      class: "section-subtitle",
      text: "Recent activity stays visible while secondary detail stays collapsed.",
    }),
    renderEventsSection(events),
  ]);
}

function renderRawSection(project, dashboard, events) {
  const taskKey = dashboardTaskKey();
  return collapsibleCard(
    "Debug / raw payload",
    [
      h("p", {
        class: "section-subtitle",
        text: "Debug payloads stay available without dominating the main dashboard.",
      }),
      h("div", { class: "raw-payload stack-gap" }, [
        lazyJsonDetails("Project payload", () => project || {}, "raw.project"),
        lazyJsonDetails(
          "Dashboard payload",
          () => dashboard || {},
          "raw.dashboard." + taskKey
        ),
        lazyJsonDetails(
          "Events payload",
          () => events || {},
          "raw.events." + taskKey
        ),
      ]),
    ],
    "section.debug." + taskKey,
    "raw-payload"
  );
}

function renderSections() {
  const project = endpointState.project.payload;
  const dashboard = endpointState.dashboard.payload;
  const events = endpointState.events.payload;
  const taskKey = dashboardTaskKey();
  const heroSlot = document.getElementById("hero-slot");
  heroSlot?.replaceChildren(renderHero(project, dashboard));
  const metricGrid = document.getElementById("metric-grid");
  metricGrid?.replaceChildren(...renderMetrics(dashboard, events));
  const rail = document.getElementById("rail-content");
  replaceContentPreservingDetails(rail, [
    renderNextAction(dashboard),
    renderRecentEventsCard(events),
  ]);
  const sections = document.getElementById("sections");
  replaceContentPreservingDetails(sections, [
    cardSection("Current summary", renderOverview(project, dashboard)),
    cardSection(
      "Todos",
      renderTodosSection(dashboard?.todos, dashboard?.next_action)
    ),
    collapsibleCard(
      "Plan",
      renderPlanSection(dashboard?.plans),
      "section.plan." + taskKey
    ),
    collapsibleCard(
      "Questions",
      renderQuestionsSection(dashboard?.questions),
      "section.questions." + taskKey
    ),
    collapsibleCard(
      "Validation",
      renderValidationSection(dashboard?.validation),
      "section.validation-card." + taskKey
    ),
    collapsibleCard(
      "Runs",
      renderRunsSection(dashboard?.runs),
      "section.runs." + taskKey
    ),
    collapsibleCard(
      "Changes",
      renderChangesSection(dashboard?.changes),
      "section.changes." + taskKey
    ),
    renderRawSection(project, dashboard, events),
  ]);
}

function setStatus() {
  const errors = Object.entries(endpointState)
    .filter(([, state]) => Boolean(state.error))
    .map(([name, state]) => name + " error: " + state.error);
  const headline = document.getElementById("status-headline");
  const detail = document.getElementById("status-detail");
  const selected = document.getElementById("selected-task-label");
  const updated = document.getElementById("last-updated-label");
  const liveStatus = document.getElementById("live-status-label");
  const toggleButton = document.getElementById("toggle-polling-button");
  const refreshButton = document.getElementById("refresh-now-button");
  const reviewState = refreshInFlight
    ? "Refreshing"
    : pollingPaused
    ? "Paused"
    : "Live";
  if (headline) {
    headline.textContent =
      reviewState === "Paused"
        ? "Dashboard updates are paused for focused review."
        : reviewState === "Refreshing"
        ? "Refreshing dashboard data..."
        : "Showing a read-only review of the selected task.";
  }
  if (detail) {
    detail.textContent =
      errors.length > 0
        ? errors.join(" · ")
        : pollingPaused
        ? "Automatic polling is paused. Use Refresh now to fetch current task state on demand."
        : "Polling dashboard and events every " +
          refreshMs +
          "ms with slower project and task refresh cadences.";
  }
  if (selected) {
    selected.textContent =
      endpointState.dashboard.payload?.task?.slug || apiTaskRef();
  }
  if (updated) {
    updated.textContent = lastUpdatedText;
  }
  if (liveStatus) {
    liveStatus.textContent = reviewState;
    liveStatus.className =
      reviewState === "Paused"
        ? "status-paused"
        : reviewState === "Refreshing"
        ? "status-refreshing"
        : "status-live";
  }
  if (toggleButton) {
    toggleButton.textContent = pollingPaused
      ? "Resume updates"
      : "Pause updates";
  }
  if (refreshButton) {
    refreshButton.disabled = refreshInFlight;
  }
}

function togglePolling() {
  pollingPaused = !pollingPaused;
  setStatus();
  if (!pollingPaused) {
    refresh().catch(renderError);
  }
}

function shouldRefresh(name, now) {
  const state = endpointState[name];
  const path = endpointPath(name);
  if (state.key !== path) return true;
  if (state.payload === null) return true;
  return now - state.lastRequestedAt >= endpointCadence(name);
}

async function refreshEndpoint(name, now) {
  const state = endpointState[name];
  state.lastRequestedAt = now;
  try {
    const result = await getJson(name, endpointPath(name));
    state.error = null;
    return result.changed;
  } catch (error) {
    const previousError = state.error;
    state.error = String(error);
    return state.payload === null || state.error !== previousError;
  }
}

async function refresh() {
  if (refreshInFlight) return;
  refreshInFlight = true;
  const changed = new Set();
  setStatus();
  try {
    const now = Date.now();
    const work = [];
    for (const name of ["project", "tasks", "dashboard", "events"]) {
      if (shouldRefresh(name, now)) {
        work.push(
          refreshEndpoint(name, now).then((didChange) => {
            if (didChange) changed.add(name);
          })
        );
      }
    }
    await Promise.allSettled(work);
    lastUpdatedText = new Date().toLocaleTimeString();
  } finally {
    refreshInFlight = false;
    if (changed.has("tasks")) renderTasks();
    if (
      changed.has("project") ||
      changed.has("dashboard") ||
      changed.has("events")
    ) {
      renderSections();
    }
    setStatus();
  }
}

async function refreshSelection() {
  endpointState.dashboard.key = null;
  endpointState.dashboard.etag = null;
  endpointState.dashboard.payload = null;
  endpointState.dashboard.error = null;
  endpointState.dashboard.lastRequestedAt = 0;
  endpointState.events.key = null;
  endpointState.events.payload = null;
  endpointState.events.lastRequestedAt = 0;
  endpointState.events.etag = null;
  endpointState.events.error = null;
  renderTasks();
  renderSections();
  setStatus();
  await refresh();
}

function scheduleRefresh(delay = refreshMs) {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => {
    if (pollingPaused) {
      setStatus();
      scheduleRefresh();
      return;
    }
    refresh()
      .catch(renderError)
      .finally(() => scheduleRefresh());
  }, delay);
}

function renderError(error) {
  endpointState.dashboard.error = String(error);
  setStatus();
  renderSections();
}

function setupControls() {
  const search = document.getElementById("task-search");
  search?.addEventListener("input", (event) => {
    taskSearchQuery = event.target?.value || "";
    renderTasks();
  });
  document
    .getElementById("toggle-polling-button")
    ?.addEventListener("click", () => {
      togglePolling();
    });
  document
    .getElementById("refresh-now-button")
    ?.addEventListener("click", () => {
      refresh().catch(renderError);
    });
}

setupControls();
renderTasks();
renderSections();
setStatus();
refresh()
  .catch(renderError)
  .finally(() => scheduleRefresh());
