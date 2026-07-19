const gamesEl = document.getElementById("games");
const drawBtn = document.getElementById("draw-btn");
const statsChart = document.getElementById("stats-chart");
const strategyBtns = document.querySelectorAll("#lotto-view .strategy-btn");
const countBtns = document.querySelectorAll("#lotto-view .count-btn");
const historyList = document.getElementById("history-list");
const clearHistoryBtn = document.getElementById("clear-history");
const toast = document.getElementById("toast");
const excludeGrid = document.getElementById("exclude-grid");
const checkInputsEl = document.getElementById("check-inputs");
const checkBtn = document.getElementById("check-btn");
const checkResults = document.getElementById("check-results");

const STRATEGY_LABEL = {
  reliability: "신뢰도",
  frequency: "빈도",
  mixed: "혼합",
  random: "무작위",
};

const HISTORY_KEY = "lotto_draw_history";
const HISTORY_LIMIT = 30;
const EXCLUDE_KEY = "lotto_exclude_numbers";

let currentStrategy = "reliability";
let currentCount = 1;
let excludedNumbers = new Set();

function colorRangeClass(num) {
  if (num <= 10) return "range-1";
  if (num <= 20) return "range-2";
  if (num <= 30) return "range-3";
  if (num <= 40) return "range-4";
  return "range-5";
}

function makeBall(num, extraClass) {
  const ball = document.createElement("div");
  ball.className = `ball ${extraClass || ""}`.trim();
  ball.textContent = num;
  return ball;
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.remove("show"), 1600);
}

function copyText(text) {
  navigator.clipboard
    .writeText(text)
    .then(() => showToast(`복사됨: ${text}`))
    .catch(() => showToast("복사에 실패했어요"));
}

function shareText(text) {
  if (navigator.share) {
    navigator.share({ title: "복권 번호 추첨기", text, url: location.href }).catch(() => {});
  } else {
    copyText(text);
  }
}

function copyGame(numbers) {
  copyText(numbers.join(", "));
}

function buildGameRow(index) {
  const row = document.createElement("div");
  row.className = "game-row";

  const top = document.createElement("div");
  top.className = "game-row-top";
  top.innerHTML = `<span class="game-label">GAME ${index + 1}</span>`;

  const copyBtn = document.createElement("button");
  copyBtn.className = "copy-btn";
  copyBtn.type = "button";
  copyBtn.textContent = "복사";
  top.appendChild(copyBtn);

  let shareBtn = null;
  if (navigator.share) {
    shareBtn = document.createElement("button");
    shareBtn.className = "copy-btn";
    shareBtn.type = "button";
    shareBtn.textContent = "공유";
    top.appendChild(shareBtn);
  }

  const balls = document.createElement("div");
  balls.className = "balls";
  for (let i = 0; i < 6; i++) {
    balls.appendChild(makeBall("?", "placeholder"));
  }

  const meta = document.createElement("div");
  meta.className = "game-meta";

  row.appendChild(top);
  row.appendChild(balls);
  row.appendChild(meta);

  return { row, balls, meta, copyBtn, shareBtn };
}

function animateGame(ballsEl, finalNumbers, onDone, delay) {
  const ballEls = Array.from(ballsEl.children);
  ballEls.forEach((el) => {
    el.classList.remove("placeholder");
    el.classList.add("rolling");
  });

  const rollTimer = setInterval(() => {
    ballEls.forEach((el) => {
      el.textContent = 1 + Math.floor(Math.random() * 45);
    });
  }, 60);

  setTimeout(() => {
    clearInterval(rollTimer);
    ballEls.forEach((el, i) => {
      setTimeout(() => {
        el.classList.remove("rolling");
        el.classList.add("settled");
        el.className = `ball settled ${colorRangeClass(finalNumbers[i])}`;
        el.textContent = finalNumbers[i];
      }, i * 80);
    });
    setTimeout(onDone, 6 * 80 + 100);
  }, delay);
}

function renderMeta(metaEl, game) {
  metaEl.innerHTML = `
    <span>합계 ${game.sum}</span>
    <span>홀${game.odd} 짝${game.even}</span>
    <span>저${game.low} 고${game.high}</span>
  `;
}

function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY)) || [];
  } catch {
    return [];
  }
}

function saveHistory(entries) {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, HISTORY_LIMIT)));
}

function renderHistory() {
  const entries = loadHistory();
  historyList.innerHTML = "";

  if (entries.length === 0) {
    historyList.innerHTML = '<p class="history-empty">아직 뽑은 기록이 없어요.</p>';
    return;
  }

  entries.forEach((entry) => {
    const item = document.createElement("div");
    item.className = "history-item";

    const tag = document.createElement("span");
    tag.className = "history-tag";
    tag.textContent = `${STRATEGY_LABEL[entry.strategy] || entry.strategy}`;

    const ballsWrap = document.createElement("span");
    ballsWrap.className = "history-balls";
    entry.numbers.forEach((num) => {
      ballsWrap.appendChild(makeBall(num, colorRangeClass(num)));
    });

    item.appendChild(tag);
    item.appendChild(ballsWrap);
    historyList.appendChild(item);
  });
}

function addToHistory(strategy, games) {
  const entries = loadHistory();
  games.forEach((game) => {
    entries.unshift({ strategy, numbers: game.numbers, ts: Date.now() });
  });
  saveHistory(entries);
  renderHistory();
}

async function draw() {
  drawBtn.disabled = true;
  drawBtn.textContent = "뽑는 중...";
  gamesEl.innerHTML = "";

  const rows = [];
  for (let i = 0; i < currentCount; i++) {
    const built = buildGameRow(i);
    gamesEl.appendChild(built.row);
    rows.push(built);
  }

  try {
    const excludeParam = Array.from(excludedNumbers).join(",");
    const res = await fetch(
      `/api/draw/${currentStrategy}?count=${currentCount}&exclude=${excludeParam}`
    );
    const data = await res.json();

    let remaining = data.games.length;
    data.games.forEach((game, i) => {
      rows[i].copyBtn.addEventListener("click", () => copyGame(game.numbers));
      if (rows[i].shareBtn) {
        rows[i].shareBtn.addEventListener("click", () => shareText(game.numbers.join(", ")));
      }
      animateGame(
        rows[i].balls,
        game.numbers,
        () => {
          renderMeta(rows[i].meta, game);
          remaining -= 1;
          if (remaining === 0) {
            addToHistory(data.strategy, data.games);
            drawBtn.disabled = false;
            drawBtn.textContent = "번호 뽑기";
          }
        },
        300 + i * 150
      );
    });
  } catch (e) {
    drawBtn.disabled = false;
    drawBtn.textContent = "번호 뽑기";
    showToast("오류가 발생했어요");
  }
}

async function loadStats() {
  const res = await fetch("/api/stats");
  const data = await res.json();
  statsChart.innerHTML = "";
  data.top.forEach((item) => {
    const row = document.createElement("div");
    row.className = "stat-row";
    row.innerHTML = `
      <span>${item.number}</span>
      <span class="stat-bar-track"><span class="stat-bar-fill" style="width:${item.score}%"></span></span>
      <span>${item.score}</span>
    `;
    statsChart.appendChild(row);
  });
}

function loadExcluded() {
  try {
    return new Set(JSON.parse(localStorage.getItem(EXCLUDE_KEY)) || []);
  } catch {
    return new Set();
  }
}

function saveExcluded() {
  localStorage.setItem(EXCLUDE_KEY, JSON.stringify(Array.from(excludedNumbers)));
}

function buildExcludeGrid() {
  excludeGrid.innerHTML = "";
  for (let num = 1; num <= 45; num++) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "exclude-num";
    btn.textContent = num;
    if (excludedNumbers.has(num)) btn.classList.add("selected");
    btn.addEventListener("click", () => {
      if (excludedNumbers.has(num)) {
        excludedNumbers.delete(num);
        btn.classList.remove("selected");
      } else {
        if (excludedNumbers.size >= 39) {
          showToast("최소 6개는 남겨둬야 해요");
          return;
        }
        excludedNumbers.add(num);
        btn.classList.add("selected");
      }
      saveExcluded();
    });
    excludeGrid.appendChild(btn);
  }
}

function rankLabel(matchCount, bonusMatch) {
  if (matchCount === 6) return "1등";
  if (matchCount === 5 && bonusMatch) return "2등";
  if (matchCount === 5) return "3등";
  if (matchCount === 4) return "4등";
  if (matchCount === 3) return "5등";
  return "낙첨";
}

function runCheck() {
  const inputs = Array.from(checkInputsEl.querySelectorAll(".check-num:not(.check-bonus)"));
  const bonusInput = checkInputsEl.querySelector(".check-bonus");

  const winNumbers = inputs
    .map((el) => parseInt(el.value, 10))
    .filter((n) => Number.isInteger(n) && n >= 1 && n <= 45);

  if (winNumbers.length !== 6 || new Set(winNumbers).size !== 6) {
    showToast("1~45 사이 서로 다른 6개 번호를 입력해주세요");
    return;
  }

  const bonus = parseInt(bonusInput.value, 10);
  const winSet = new Set(winNumbers);
  const entries = loadHistory();

  if (entries.length === 0) {
    checkResults.innerHTML = '<p class="check-empty">대조할 히스토리가 없어요. 먼저 번호를 뽑아보세요.</p>';
    return;
  }

  const scored = entries.map((entry) => {
    const matched = entry.numbers.filter((n) => winSet.has(n));
    const bonusMatch = Number.isInteger(bonus) && entry.numbers.includes(bonus);
    return { entry, matched, matchCount: matched.length, bonusMatch };
  });

  scored.sort((a, b) => b.matchCount - a.matchCount);

  checkResults.innerHTML = "";
  scored.slice(0, 10).forEach(({ entry, matched, matchCount, bonusMatch }) => {
    const row = document.createElement("div");
    row.className = "check-row";

    const rank = document.createElement("span");
    const label = rankLabel(matchCount, bonusMatch);
    rank.className = `check-rank ${matchCount >= 3 ? "hit" : ""}`;
    rank.textContent = `${label} (${matchCount}개)`;

    const ballsWrap = document.createElement("span");
    ballsWrap.className = "check-balls";
    entry.numbers.forEach((num) => {
      const ball = makeBall(num, colorRangeClass(num));
      if (winSet.has(num)) ball.classList.add("matched");
      ballsWrap.appendChild(ball);
    });

    row.appendChild(rank);
    row.appendChild(ballsWrap);
    checkResults.appendChild(row);
  });
}

strategyBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    strategyBtns.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentStrategy = btn.dataset.strategy;
  });
});

countBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    countBtns.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentCount = parseInt(btn.dataset.count, 10);
  });
});

clearHistoryBtn.addEventListener("click", (e) => {
  e.preventDefault();
  e.stopPropagation();
  localStorage.removeItem(HISTORY_KEY);
  renderHistory();
});

drawBtn.addEventListener("click", draw);
checkBtn.addEventListener("click", runCheck);

excludedNumbers = loadExcluded();
buildExcludeGrid();

loadStats();
renderHistory();

// initial placeholder row
const initial = buildGameRow(0);
gamesEl.appendChild(initial.row);

// ---------- game tab switching ----------

const gameTabs = document.querySelectorAll(".game-tab");
const lottoView = document.getElementById("lotto-view");
const pensionView = document.getElementById("pension-view");

gameTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    gameTabs.forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    const game = tab.dataset.game;
    lottoView.hidden = game !== "lotto";
    pensionView.hidden = game !== "pension";
  });
});

// ---------- 연금복권720+ ----------

const pensionGamesEl = document.getElementById("pension-games");
const pensionDrawBtn = document.getElementById("pension-draw-btn");
const pensionStatsChart = document.getElementById("pension-stats-chart");
const pensionStrategyBtns = document.querySelectorAll("#pension-view .strategy-btn");
const pensionCountBtns = document.querySelectorAll("#pension-view .count-btn");
const pensionHistoryList = document.getElementById("pension-history-list");
const pensionClearHistoryBtn = document.getElementById("pension-clear-history");
const pensionCheckInputsEl = document.getElementById("pension-check-inputs");
const pensionCheckGroupSelect = document.getElementById("pension-check-group");
const pensionCheckBtn = document.getElementById("pension-check-btn");
const pensionCheckResults = document.getElementById("pension-check-results");

const PENSION_HISTORY_KEY = "pension_draw_history";
const PENSION_HISTORY_LIMIT = 30;
const PENSION_RANK_SCORE = { "1등": 7, "2등": 6, "3등": 5, "4등": 4, "5등": 3, "6등": 2, "7등": 1, "낙첨": 0 };

let pensionStrategy = "reliability";
let pensionCount = 1;

function makeGroupBadge(group, extraClass) {
  const badge = document.createElement("div");
  badge.className = `group-badge ${extraClass || ""}`.trim();
  if (group === "?") {
    badge.textContent = "?";
  } else {
    badge.innerHTML = `${group}<span class="group-label">조</span>`;
  }
  return badge;
}

function makeDigit(digit, extraClass) {
  const el = document.createElement("div");
  el.className = `digit ${extraClass || ""}`.trim();
  el.textContent = digit;
  return el;
}

function buildPensionGameRow(index) {
  const row = document.createElement("div");
  row.className = "game-row";

  const top = document.createElement("div");
  top.className = "game-row-top";
  top.innerHTML = `<span class="game-label">GAME ${index + 1}</span>`;

  const copyBtn = document.createElement("button");
  copyBtn.className = "copy-btn";
  copyBtn.type = "button";
  copyBtn.textContent = "복사";
  top.appendChild(copyBtn);

  let shareBtn = null;
  if (navigator.share) {
    shareBtn = document.createElement("button");
    shareBtn.className = "copy-btn";
    shareBtn.type = "button";
    shareBtn.textContent = "공유";
    top.appendChild(shareBtn);
  }

  const result = document.createElement("div");
  result.className = "pension-result";

  const groupBadge = makeGroupBadge("?", "placeholder");
  result.appendChild(groupBadge);

  const digitsEl = document.createElement("div");
  digitsEl.className = "digits";
  for (let i = 0; i < 6; i++) {
    digitsEl.appendChild(makeDigit("?", "placeholder"));
  }
  result.appendChild(digitsEl);

  const meta = document.createElement("div");
  meta.className = "game-meta";

  row.appendChild(top);
  row.appendChild(result);
  row.appendChild(meta);

  return { row, groupBadge, digitsEl, meta, copyBtn, shareBtn };
}

function animatePension(groupBadgeEl, digitsEl, finalGroup, finalNumber, onDone, delay) {
  const digitEls = Array.from(digitsEl.children);
  groupBadgeEl.classList.remove("placeholder");
  groupBadgeEl.classList.add("rolling");
  digitEls.forEach((el) => {
    el.classList.remove("placeholder");
    el.classList.add("rolling");
  });

  const rollTimer = setInterval(() => {
    groupBadgeEl.textContent = 1 + Math.floor(Math.random() * 5);
    digitEls.forEach((el) => {
      el.textContent = Math.floor(Math.random() * 10);
    });
  }, 60);

  setTimeout(() => {
    clearInterval(rollTimer);

    groupBadgeEl.className = "group-badge settled";
    groupBadgeEl.innerHTML = `${finalGroup}<span class="group-label">조</span>`;

    digitEls.forEach((el, i) => {
      setTimeout(() => {
        el.className = "digit settled";
        el.textContent = finalNumber[i];
      }, i * 80);
    });
    setTimeout(onDone, 6 * 80 + 100);
  }, delay);
}

function renderPensionMeta(metaEl, game) {
  metaEl.innerHTML = `<span>각 자리 합 ${game.digitSum}</span>`;
}

function copyPension(group, number) {
  const text = `${group}조 ${number}`;
  navigator.clipboard
    .writeText(text)
    .then(() => showToast(`복사됨: ${text}`))
    .catch(() => showToast("복사에 실패했어요"));
}

function loadPensionHistory() {
  try {
    return JSON.parse(localStorage.getItem(PENSION_HISTORY_KEY)) || [];
  } catch {
    return [];
  }
}

function savePensionHistory(entries) {
  localStorage.setItem(PENSION_HISTORY_KEY, JSON.stringify(entries.slice(0, PENSION_HISTORY_LIMIT)));
}

function renderPensionHistory() {
  const entries = loadPensionHistory();
  pensionHistoryList.innerHTML = "";

  if (entries.length === 0) {
    pensionHistoryList.innerHTML = '<p class="history-empty">아직 뽑은 기록이 없어요.</p>';
    return;
  }

  entries.forEach((entry) => {
    const item = document.createElement("div");
    item.className = "history-item";

    const tag = document.createElement("span");
    tag.className = "history-tag";
    tag.textContent = `${STRATEGY_LABEL[entry.strategy] || entry.strategy}`;

    const result = document.createElement("span");
    result.className = "history-balls";
    result.textContent = `${entry.group}조 ${entry.number}`;

    item.appendChild(tag);
    item.appendChild(result);
    pensionHistoryList.appendChild(item);
  });
}

function addPensionToHistory(strategy, games) {
  const entries = loadPensionHistory();
  games.forEach((game) => {
    entries.unshift({ strategy, group: game.group, number: game.number, ts: Date.now() });
  });
  savePensionHistory(entries);
  renderPensionHistory();
}

async function pensionDraw() {
  pensionDrawBtn.disabled = true;
  pensionDrawBtn.textContent = "뽑는 중...";
  pensionGamesEl.innerHTML = "";

  const rows = [];
  for (let i = 0; i < pensionCount; i++) {
    const built = buildPensionGameRow(i);
    pensionGamesEl.appendChild(built.row);
    rows.push(built);
  }

  try {
    const res = await fetch(`/api/pension/draw/${pensionStrategy}?count=${pensionCount}`);
    const data = await res.json();

    let remaining = data.games.length;
    data.games.forEach((game, i) => {
      rows[i].copyBtn.addEventListener("click", () => copyPension(game.group, game.number));
      if (rows[i].shareBtn) {
        rows[i].shareBtn.addEventListener("click", () => shareText(`${game.group}조 ${game.number}`));
      }
      animatePension(
        rows[i].groupBadge,
        rows[i].digitsEl,
        game.group,
        game.number,
        () => {
          renderPensionMeta(rows[i].meta, game);
          remaining -= 1;
          if (remaining === 0) {
            addPensionToHistory(data.strategy, data.games);
            pensionDrawBtn.disabled = false;
            pensionDrawBtn.textContent = "번호 뽑기";
          }
        },
        300 + i * 150
      );
    });
  } catch (e) {
    pensionDrawBtn.disabled = false;
    pensionDrawBtn.textContent = "번호 뽑기";
    showToast("오류가 발생했어요");
  }
}

async function loadPensionStats() {
  const res = await fetch("/api/pension/stats");
  const data = await res.json();
  pensionStatsChart.innerHTML = "";
  data.groups.forEach((item) => {
    const row = document.createElement("div");
    row.className = "stat-row";
    row.innerHTML = `
      <span>${item.group}조</span>
      <span class="stat-bar-track"><span class="stat-bar-fill" style="width:${item.score}%"></span></span>
      <span>${item.score}</span>
    `;
    pensionStatsChart.appendChild(row);
  });
}

function pensionRank(guessGroup, guessNumber, entryGroup, entryNumber) {
  if (guessNumber === entryNumber) {
    return guessGroup === entryGroup ? "1등" : "2등";
  }
  let suffix = 0;
  for (let i = 5; i >= 0; i--) {
    if (guessNumber[i] === entryNumber[i]) {
      suffix += 1;
    } else {
      break;
    }
  }
  const byLen = { 5: "3등", 4: "4등", 3: "5등", 2: "6등", 1: "7등" };
  return byLen[suffix] || "낙첨";
}

function runPensionCheck() {
  const guessGroup = parseInt(pensionCheckGroupSelect.value, 10);
  const digitInputs = Array.from(pensionCheckInputsEl.querySelectorAll(".pension-check-digit"));
  const digits = digitInputs.map((el) => el.value);

  if (digits.some((d) => d === "" || !/^[0-9]$/.test(d))) {
    showToast("0~9 사이 숫자 6자리를 모두 입력해주세요");
    return;
  }

  const guessNumber = digits.join("");
  const entries = loadPensionHistory();

  if (entries.length === 0) {
    pensionCheckResults.innerHTML = '<p class="check-empty">대조할 히스토리가 없어요. 먼저 번호를 뽑아보세요.</p>';
    return;
  }

  const scored = entries.map((entry) => {
    const rank = pensionRank(guessGroup, guessNumber, entry.group, entry.number);
    return { entry, rank, score: PENSION_RANK_SCORE[rank] };
  });

  scored.sort((a, b) => b.score - a.score);

  pensionCheckResults.innerHTML = "";
  scored.slice(0, 10).forEach(({ entry, rank, score }) => {
    const row = document.createElement("div");
    row.className = "check-row";

    const rankEl = document.createElement("span");
    rankEl.className = `check-rank ${score >= 3 ? "hit" : ""}`;
    rankEl.textContent = rank;

    const resultEl = document.createElement("span");
    resultEl.className = "check-balls";
    resultEl.textContent = `${entry.group}조 ${entry.number}`;

    row.appendChild(rankEl);
    row.appendChild(resultEl);
    pensionCheckResults.appendChild(row);
  });
}

pensionStrategyBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    pensionStrategyBtns.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    pensionStrategy = btn.dataset.strategy;
  });
});

pensionCountBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    pensionCountBtns.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    pensionCount = parseInt(btn.dataset.count, 10);
  });
});

pensionClearHistoryBtn.addEventListener("click", (e) => {
  e.preventDefault();
  e.stopPropagation();
  localStorage.removeItem(PENSION_HISTORY_KEY);
  renderPensionHistory();
});

pensionDrawBtn.addEventListener("click", pensionDraw);
pensionCheckBtn.addEventListener("click", runPensionCheck);

loadPensionStats();
renderPensionHistory();

const pensionInitial = buildPensionGameRow(0);
pensionGamesEl.appendChild(pensionInitial.row);

// ---------- 최근 당첨결과 ----------

async function loadLatestLotto() {
  const card = document.getElementById("lotto-latest");
  try {
    const res = await fetch("/api/latest/lotto");
    const data = await res.json();
    if (!data.ok || !data.result) return;

    const r = data.result;
    card.querySelector(".latest-title").textContent = `제${r.round}회 (${r.date}) 당첨번호`;

    const ballsWrap = card.querySelector(".latest-balls");
    ballsWrap.innerHTML = "";
    r.numbers.forEach((num) => {
      ballsWrap.appendChild(makeBall(num, colorRangeClass(num)));
    });
    const plus = document.createElement("span");
    plus.className = "latest-plus";
    plus.textContent = "+";
    ballsWrap.appendChild(plus);
    ballsWrap.appendChild(makeBall(r.bonus, `${colorRangeClass(r.bonus)} bonus`));

    card.hidden = false;
  } catch (e) {
    // stay hidden if the source is unavailable
  }
}

async function loadLatestPension() {
  const card = document.getElementById("pension-latest");
  try {
    const res = await fetch("/api/latest/pension");
    const data = await res.json();
    if (!data.ok || !data.result) return;

    const r = data.result;
    card.querySelector(".latest-title").textContent = `제${r.round}회 (${r.date}) 당첨결과`;

    const wrap = card.querySelector(".latest-balls");
    wrap.innerHTML = "";
    wrap.appendChild(makeGroupBadge(r.group));
    r.number.split("").forEach((d) => wrap.appendChild(makeDigit(d)));

    card.hidden = false;
  } catch (e) {
    // stay hidden if the source is unavailable
  }
}

loadLatestLotto();
loadLatestPension();
